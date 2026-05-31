# mimic_linux — tmux・Monitor 機能 安全除去計画書

> **作成日**: 2026-07-01
> **対象リポジトリ**: `/home/loser/wsl-projects/mimic_linux`
> **ゴール**: tmux 連携とリアルタイムダッシュボード（Monitor）機能を安全に削除し、
>           本体のエージェント機能には一切影響を与えない。

---

## 1. 現状分析

### 1.1 機能概要

| 機能 | 役割 | 配置ファイル |
|------|------|-------------|
| **tmux オーケストレーション** | セッション/ペイン管理、`--tmux` フラグ時の自動起動 | `tmux_orch.py` (189行) |
| **Monitor ダッシュボード** | ANSI アートダッシュボードを `/tmp/mimic_monitor.ansi` に 1 秒ごと書き込み | `monitor.py` (245行) |
| **監視インフラ** | ツール呼び出し計測、プロセス/system リソース監視 | `monitoring.py` (228行), `proc_observer.py` (291行) |

### 1.2 ファイル間依存関係図

```
__main__.py (エントリポイント)
  ├── import tmux_orch          ← 削除対象
  ├── import monitor            ← 削除対象
  ├── import monitoring         ← 編集が必要
  └── import proc_observer      ← 残す（内部でも使用可）

mcp_server.py (MCPサーバー)
  ├── _ensure_log_monitor()     ← tmux/xterm ウィンドウ起動（編集必要）
  └── _agent_terminal()         ← tmux/xterm フォールバック（編集必要）

tmux_orch.py                    ← 削除対象
monitor.py                      ← 削除対象
monitoring.py                   ← 編集が必要（dashboard_fn, _Spinner関連）
proc_observer.py                ← 残す

main.py                         ← 編集不要（非依存）
tools.py                        ← 編集不要（非依存）
orchestrator.py                 ← 編集不要（非依存）
commands.py                     ← 編集不要（非依存）
config.py                       ← 編集不要（非依存）
agent.py                        ← 編集不要（非依存）
utils.py                        ← 編集不要（非依存）
autogit.py                      ← 編集不要（非依存）
pipeline.py                     ← 編集不要（非依存）
tools_linux.py                  ← 編集不要（非依存）
```

### 1.3 影響範囲サマリ

| 操作 | ファイル | 種別 |
|------|----------|------|
| **削除** | `tmux_orch.py` | 完全削除 |
| **削除** | `monitor.py` | 完全削除 |
| **編集** | `__main__.py` | tmux 関連コードの除去 |
| **編集** | `monitoring.py` | ダッシュボード連携部分の除去 |
| **編集** | `mcp_server.py` | `_ensure_log_monitor()`, `_agent_terminal()` の tmux/xterm 部分修正 |
| **編集不要** | その他全ファイル | 影響なし |

---

## 2. 安全除去の基本方針

1. **削除前に全変更を `git commit` / `git branch` で保護する**
2. **1ファイルずつ変更し、各ステップで動作確認する**
3. **import エラーが残らないよう、参照元も同時に修正する**
4. **監視ロジック（`monitoring.py`, `proc_observer.py`）は残す** — ツール呼び出し統計（`/stats` コマンド）が使えるようにするため

---

## 3. ステップバイステップ実施手順

### Step 0: 作業ブランチ作成とバックアップ

```bash
cd /home/loser/wsl-projects/mimic_linux
git checkout -b feature/remove-tmux-monitor
git add -A
git commit -m "checkpoint: before tmux/monitor removal"
```

---

### Step 1: `__main__.py` の tmux 関連コードを除去

**ファイル**: `__main__.py`（220行）

#### 1a. import 文の修正

**削除する import（3箇所）**:
```python
# 削除する行:
from .tmux_orch import inside_tmux, relaunch_inside_tmux   # L66付近
from .monitor import MonitorDashboard                       # 関数内
from .proc_observer import SystemMonitor                    # _start_tmux_dashboard内
```

**修正後の import セクション**（該当部分）:
```python
# tmux 関連 import はすべて削除
# monitoring 系は残す（ツール統計に必要）
from .monitoring import MonitoringToolRegistry, ToolCallLog
```

#### 1b. `--tmux` フラグ処理ブロックの削除

**削除範囲**: `main()` 関数内の `use_tmux` 関連コード

```python
# ── 削除ブロック ──────────────────────────────────────
_args = sys.argv[1:]
use_tmux = "--tmux" in _args          # ← 削除
_args_clean = [a for a in _args if a != "--tmux"]  # ← 削除

# tmux チェックをモデル選択より先に実行
if use_tmux:                           # ← ここから
    import shutil
    if shutil.which("tmux"):
        from .tmux_orch import inside_tmux, relaunch_inside_tmux
        if not inside_tmux():
            relaunch_inside_tmux("mimic")
            return                     # ← ここまで削除
# ──────────────────────────────────────────────────────
```

**修正後**: `_args_clean` → `_args` に統一（`--tmux` フィルタリングをやめる）

```python
_args = sys.argv[1:]
# --tmux は無視される（存在してもエラーにしない）
_args = [a for a in _args if a != "--tmux"]
```

#### 1c. tmux ダッシュボード起動コードの削除

**削除範囲**: `main()` 関数末尾の `if use_tmux:` ブロック

```python
# ── 削除ブロック ──────────────────────────────────────
    # ── tmux ダッシュボード起動（--tmux フラグ時のみ）────────────
    if use_tmux:
        _start_tmux_dashboard(
            tool_log, active_config, mon_tools,
            get_cwd     = lambda: agent.cwd,
            get_history = lambda: len(agent.conversation),
        )
# ──────────────────────────────────────────────────────
```

#### 1d. `_start_tmux_dashboard()` 関数の完全削除

**削除範囲**: `__main__.py` 末尾の関数定義全体

```python
# ── 完全削除 ──────────────────────────────────────────
def _start_tmux_dashboard(tool_log, active_config, mon_registry=None,
                          get_cwd=None, get_history=None):
    """..."""
    # ...（全コード削除）
# ──────────────────────────────────────────────────────
```

#### 1e. 修正後の `__main__.py` の import 一覧

```python
from __future__ import annotations
import os
import sys
import signal
import logging
from pathlib import Path

from .utils import safe_print, C, set_log_sink
from .commands import register_search_command, register_sessions_command
from .tools import set_sessions_dir, tools as _base_tools
from . import config as _cfg
from .config import load_config, select_model_interactively_multi
from .agent import OpenRouterAgent, AccountRotator
from .autogit import AutoGit
from .orchestrator import (InteractiveOrchestrator, AgentOrchestrator,
                            BASH_EXECUTOR_GUIDANCE, REACT_SYSTEM_PROMPT)
from .main import interactive_loop, pipe_mode, auto_mode
from .monitoring import MonitoringToolRegistry, ToolCallLog
```

---

### Step 2: `monitoring.py` のダッシュボード連携部分を除去

**ファイル**: `monitoring.py`（228行）

#### 2a. `MonitoringToolRegistry.__init__` の `dashboard_fn` 引数削除

**修正前**:
```python
def __init__(
    self,
    base: ToolRegistry,
    log: ToolCallLog,
    display_fn: Optional[Callable[[ToolCallRecord], None]] = None,
    dashboard_fn: Optional[Callable[[ToolCallRecord], None]] = None,  # ← 削除
):
    self._tools        = base._tools
    self._log          = log
    self._display      = display_fn
    self._dashboard    = dashboard_fn   # ← 削除
    self._lock         = threading.Lock()
    self.current_tool: Optional[str] = None
```

**修正後**:
```python
def __init__(
    self,
    base: ToolRegistry,
    log: ToolCallLog,
    display_fn: Optional[Callable[[ToolCallRecord], None]] = None,
):
    self._tools        = base._tools
    self._log          = log
    self._display      = display_fn
    self._lock         = threading.Lock()
    self.current_tool: Optional[str] = None
```

#### 2b. `execute()` 内のダッシュボード更新コード削除

**修正前**:
```python
        # ── tmux ダッシュボード更新 ──
        if self._dashboard:
            self._dashboard(record)
```

**修正後**: この4行ブロックを完全削除

#### 2c. `__main__.py` での `MonitoringToolRegistry` 構築コード修正

**修正前** (`__main__.py`):
```python
mon_tools = MonitoringToolRegistry(
    base       = _base_tools,
    log        = tool_log,
    display_fn = _inline_display,
)
```

**修正後**: 変更なし（`dashboard_fn` を渡していないため、Step 2a のデフォルト値削除でOK）

> **注意**: `dashboard_fn` のデフォルト値を `None` から完全に引数自体を削除すること。
> 既存呼び出しが `dashboard_fn=...` と明示的に渡していないことを確認済み。

---

### Step 3: `mcp_server.py` の tmux/xterm 依存部分を修正

**ファイル**: `mcp_server.py`（321行）

#### 3a. `_ensure_log_monitor()` 関数の修正

**現状**: tmux セッションにログ監視ペインを開く、xterm にフォールバック

**修正方針**: ログ監視ウィンドウ起動を完全に無効化（関数内身をパスにする）

**修正前**:
```python
def _ensure_log_monitor():
    global _monitor_launched
    if _monitor_launched:
        return
    try:
        if shutil.which("tmux"):
            ret = subprocess.run(["tmux", "has-session", "-t", "mimic"], capture_output=True)
            if ret.returncode == 0:
                subprocess.Popen([...])  # tmux new-window
            else:
                subprocess.Popen([...])  # tmux new-session
        elif shutil.which("xterm"):
            subprocess.Popen([...])  # xterm
        _monitor_launched = True
    except Exception:
        pass
```

**修正後**:
```python
def _ensure_log_monitor():
    """ログ監視ウィンドウ起動（現在は無効化済み）。"""
    global _monitor_launched
    _monitor_launched = True  # 何もしないが、呼び出し元の整合性のため
```

#### 3b. `_agent_terminal()` 関数の修正

**現状**: tmux セッション or xterm でターミナルを起動

**修正方針**: ターミナル自動起動を廃止し、手動実行ガイドを返す

**修正後**:
```python
def _agent_terminal(task: str, working_dir: str | None) -> str:
    """ターミナル起動（現在は手動実行ガイドを返す）。"""
    cwd = working_dir or str(V4_DIR)
    py  = sys.executable
    task_preview = task[:300].replace('"', "'")
    return (
        "ターミナル自動起動は無効化されています。\n"
        f"手動で次のコマンドを実行してください:\n"
        f"  cd {cwd} && {py} -m mimic_linux\n\n"
        f"以下のタスクをターミナルに貼り付けてください:\n"
        f"{'─'*50}\n{task_preview}\n{'─'*50}"
    )
```

---

### Step 4: `tmux_orch.py` の削除

```bash
rm /home/loser/wsl-projects/mimic_linux/tmux_orch.py
```

**削除理由**: `__main__.py` と `mcp_server.py` の参照をすべて除去したため、
            他ファイルからの import は存在しない。

---

### Step 5: `monitor.py` の削除

```bash
rm /home/loser/wsl-projects/mimic_linux/monitor.py
```

**削除理由**: `__main__.py` の `_start_tmux_dashboard()` を完全削除したため、
            他ファイルからの import は存在しない。

---

### Step 6: 動作確認

```bash
# 1. 構文チェック
cd /home/loser/wsl-projects
python -c "import mimic_linux"

# 2. ヘルプ表示（エラーが出ないことを確認）
python -m mimic_linux --status

# 3. 通常起動（インタラクティブモード）
python -m mimic_linux

# 4. 旧 --tmux フラグで起動（エラーが出ないこと）
python -m mimic_linux --tmux --status

# 5. /stats コマンドが使えること（monitoring.py が生きている確認）
# インタラクティブモードで /stats と入力

# 6. MCPサーバー起動確認
python -m mimic_linux.mcp_server
# (Ctrl+C で終了)
```

---

### Step 7: 最終コミット

```bash
cd /home/loser/wsl-projects/mimic_linux
git add -A
git commit -m "refactor: remove tmux and monitor dashboard features

- Delete tmux_orch.py (TmuxPane, TmuxSession, relaunch_inside_tmux)
- Delete monitor.py (MonitorDashboard, ANSI dashboard rendering)
- Edit __main__.py: remove --tmux flag handling, _start_tmux_dashboard()
- Edit monitoring.py: remove dashboard_fn parameter, dashboard update code
- Edit mcp_server.py: disable _ensure_log_monitor(), simplify _agent_terminal()
- Keep monitoring.py and proc_observer.py intact (tool stats still work)"
```

---

## 4. 削除されるコード量の見積もり

| ファイル | 操作 | 削除行数 | 備考 |
|----------|------|---------|------|
| `tmux_orch.py` | 完全削除 | ~189行 | ファイルごと削除 |
| `monitor.py` | 完全削除 | ~245行 | ファイルごと削除 |
| `__main__.py` | 部分編集 | ~45行削除 | import + --tmux処理 + _start_tmux_dashboard関数 |
| `monitoring.py` | 部分編集 | ~10行削除 | dashboard_fn引数 + 更新コード |
| `mcp_server.py` | 部分編集 | ~30行削除 | _ensure_log_monitor + _agent_terminal |
| **合計** | | **~519行** | |

---

## 5. リスク評価と対策

| リスク | 影響度 | 対策 |
|--------|--------|------|
| import エラー（tmux_orch, monitor 参照残り） | 🔴 高 | Step 6 の `python -c "import mimic_linux"` で確認 |
| `--tmux` フラグで起動時のクラッシュ | 🔴 高 | Step 1b でフラグを無視するよう修正 |
| `MonitoringToolRegistry` の `dashboard_fn` 引数エラー | 🟡 中 | Step 2a で引数削除 + 呼び出し側確認 |
| MCP サーバーからのターミナル起動の失敗 | 🟡 中 | Step 3b で手動実行ガイドに置換 |
| `/stats` コマンドが動かなくなる | 🟢 低 | `monitoring.py` のコアは残すため影響なし |
| `proc_observer.py` が使えなくなる | 🟢 低 | 単独で動作するモジュールのため影響なし |

---

## 6. 残る機能（削除後の動作保証）

| 機能 | 状態 |
|------|------|
| ReAct エージェントループ | ✅ 完全動作 |
| Plan-and-Execute モード | ✅ 完全動作 |
| ツール実行（bash, read, write, grep 等） | ✅ 完全動作 |
| AutoGit バックアップ | ✅ 完全動作 |
| セッションログ（JSONL） | ✅ 完全動作 |
| `/stats` コマンド（ツール統計） | ✅ 完全動作 |
| `/search` コマンド（セッション検索） | ✅ 完全動作 |
| MCP サーバー（agent_run） | ✅ 完全動作 |
| プロセスリソース計測（CPU/MEM） | ✅ 完全動作 |
| tmux ダッシュボード | ❌ 削除 |
| `--tmux` フラグ | ❌ 無視される |
| ログ監視ウィンドウ自動起動 | ❌ 無効化 |
| ターミナル自動起動（MCP） | ❌ 手動ガイドに変更 |

---

## 7. 巻き戻し手順（問題発生時）

```bash
# 作業ブランチを破棄して元に戻す
cd /home/loser/wsl-projects/mimic_linux
git checkout main  # or master
git branch -D feature/remove-tmux-monitor
```

---

## 8. 補足: モジュール構成（削除後）

```
mimic_linux/
├── __init__.py          # 変更なし
├── __main__.py          # 編集済み（tmux/monitor コード除去）
├── main.py              # 変更なし
├── agent.py             # 変更なし
├── config.py            # 変更なし
├── tools.py             # 変更なし
├── tools_linux.py       # 変更なし
├── utils.py             # 変更なし
├── orchestrator.py      # 変更なし
├── commands.py          # 変更なし
├── monitoring.py        # 編集済み（dashboard_fn 除去）
├── proc_observer.py     # 変更なし
├── autogit.py           # 変更なし
├── pipeline.py          # 変更なし
├── mcp_server.py        # 編集済み（tmux/xterm 起動除去）
├── test_keys.py         # 変更なし
├── test_nemotron.py     # 変更なし
├── run.sh               # 変更なし
├── pyproject.toml       # 変更なし
└── .env / .env.example  # 変更なし

（tmux_orch.py → 削除）
（monitor.py → 削除）
```
