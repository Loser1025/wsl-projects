# mimic_linux アーキテクチャ概要

mimic3 の Linux 最適化版。`python3 -m mimic_linux` で起動。
このファイルは Claude Code セッション間でコンテキストを引き継ぐためのもの。

---

## ファイル構成

| ファイル | 役割 | mimic3比 |
|---|---|---|
| `agent.py` | OpenRouterAgent (ReActループ本体) | 流用 |
| `autogit.py` | AutoGit / ReactLog | 流用 |
| `commands.py` | スラッシュコマンド定義 | 流用 |
| `config.py` | KeyManager / OpenRouterConfig / GoogleAIConfig | 流用 |
| `main.py` | interactive_loop / pipe_mode / auto_mode | 流用 |
| `orchestrator.py` | オーケストレーター。BASH_EXECUTOR_GUIDANCE を定義 | 修正済み |
| `utils.py` | C / ThinkAwareBuffer / PipelineTypewriter / TokenBucket | 流用 |
| `tools.py` | ToolRegistry + ファイルIO / web検索 / ブラウザ。末尾で Linux ツールをインポート | 修正済み |
| `__main__.py` | エントリポイント。readline・SIGTERM・MonitoringToolRegistry 組み込み | **大幅修正** |
| `tools_linux.py` | **新規**: `run_bash` (pty/プロセスグループ/SIGTERM→SIGKILL) | 新規 |
| `pipeline.py` | **新規**: `run_pipeline` (大量データ処理・ストリーム読み) | 新規 |
| `proc_observer.py` | **新規**: ProcessMonitor / SystemMonitor / Sample / Summary | 新規 |
| `monitoring.py` | **新規**: MonitoringToolRegistry / ToolCallLog / ToolCallRecord | 新規 |
| `tmux_orch.py` | **新規**: TmuxSession / TmuxPane (tmux管理) | 新規 |
| `monitor.py` | **新規**: MonitorDashboard (tmuxペインへリアルタイム描画) | 新規 |
| `mcp_server.py` | MCP サーバー。tmux/xterm でターミナル起動 | 修正済み |

---

## 起動方法

```bash
# 通常起動（インタラクティブモード）
python3 -m mimic_linux

# tmux ダッシュボード付き起動
python3 -m mimic_linux --tmux

# パイプモード（非対話）
python3 -m mimic_linux --prompt "タスク内容"

# オートモード（MCP連携）
python3 -m mimic_linux --auto-prompt "タスク内容"
```

---

## 監視アーキテクチャ

```
MonitoringToolRegistry（monitoring.py）
  ↑ ToolRegistry を継承。agent.py を変更せずに全ツールを横断計測。

  execute(tool_name, args):
    1. ProcessMonitor.start()      ← /proc/{pid} ポーリング開始
    2. super().execute()           ← 実際のツール実行
    3. ProcessMonitor.stop()       ← 集計（CPU最大・メモリ増分）
    4. _inline_display(record)     ← ターミナルにグレーで1行表示
    5. ToolCallLog.add(record)     ← セッション統計に追記
    6. _dashboard(record)          ← tmuxペイン更新（--tmux時のみ）

インライン表示例（tmuxなしでも常に動く）:
  ✓ run_bash 2.30s | CPU:max45% | MEM:+12MB
  ✓ read_file 0.02s | CPU:max2% | MEM:+0MB
```

---

## ツール一覧

| ツール | 説明 | 出力形式 |
|---|---|---|
| `run_bash` | bash実行（pty・プロセスグループkill） | [SUCCESS] or [FAILURE...] |
| `run_pipeline` | Unixパイプライン（大量データ向け） | [SUCCESS] or [FAILURE...] |
| `read_file` | ファイル読み込み | テキスト |
| `write_file` | ファイル書き込み（承認あり） | 完了メッセージ |
| `edit_file` | 行範囲指定編集 | 完了メッセージ |
| `patch_file` | old/new テキスト置換 | 完了メッセージ |
| `delete_file` | ファイル削除（ディレクトリは `run_bash rm -rf`） | 完了メッセージ |
| `move_file` | 移動・リネーム | 完了メッセージ |
| `list_directory` | ディレクトリ一覧 | テキスト |
| `search_files` | ファイル名検索 | テキスト |
| `get_repo_map` | リポジトリ構造マップ | テキスト |
| `web_search` | DuckDuckGo HTMLスクレイピング | テキスト |
| `fetch_webpage` | HTTP GET + HTMLクリーニング | テキスト |
| `read_tool_cache` | 長大ツール出力の続きを読む | テキスト |
| `update_scratchpad` | エージェントの自己記憶を更新 | 完了メッセージ |
| `browser_*` | Playwright（`enable_browser_tools()` で有効化） | テキスト |

---

## よく使うコマンド

```
/mode interactive    # ReActモードに切り替え
/mode plan          # Plan-and-Executeモードに切り替え
/status             # モデル・キー状態表示
/stats              # ツール呼び出し統計（今セッション）← Linux版新機能
/undo               # AutoGitでロールバック
/history            # ReActログ表示
/export [path]      # ReActログをMarkdown書き出し
/cd <path>          # 作業ディレクトリ変更
/clear              # 会話履歴クリア
/search <query>     # 過去セッション検索
/sessions [番号]    # 過去セッション一覧・詳細
```

---

## run_bash の仕様

```python
# tools_linux.py
run_bash(command, timeout=60, working_directory=None, shell="bash")

特徴:
  - pty.openpty() で疑似端末確保 → npm/git など対話的コマンドも動作
  - os.setsid() で新プロセスグループ
  - タイムアウト時: SIGTERM → 2秒待機 → SIGKILL（グループ全体）
  - 環境変数: LC_ALL=C.UTF-8 を自動付与
  - 出力: キャリッジリターン正規化済み
```

## run_pipeline の仕様

```python
# pipeline.py
run_pipeline(command, working_directory=None, timeout=120, max_lines=1000)

特徴:
  - pty なし・stdout を行単位でストリーム読み → 大量出力でもメモリ圧迫なし
  - max_lines を超えた場合は打ち切り通知付きで返す
  - プロセスグループ kill 対応
  - 出力が 10000 文字超の場合は cache_tool_output でチャンク化
```

---

## tmux ダッシュボード（--tmux モード）

```bash
python3 -m mimic_linux --tmux
```

```
┌──────────────────────────────────────────────────────────┐
│  MIMIC LINUX — MONITOR  2026-05-29 15:30:42             │
├──────────────────────────────────────────────────────────┤
│  CPU  [████████░░░░░░░░░░░░]  38.2%  Load: 1.24        │
│  MEM  [█████████████░░░░░░░]  64.1%  3.2/5.0 GB        │
├──────────────────────────────────────────────────────────┤
│  モデル: gemini-2.0-flash                               │
│  ツール: 14回  エラー: 0回  合計: 32.4s                  │
├──────────────────────────────────────────────────────────┤
│  直近の呼び出し:                                         │
│  ✓ run_bash       2.30s | CPU:max45% | MEM:+12MB       │
│  ✓ read_file      0.02s | CPU:max 2% | MEM: +0MB       │
│  ✓ run_pipeline   8.14s | CPU:max88% | MEM: +3MB       │
└──────────────────────────────────────────────────────────┘
```

---

## .env 設定

`mimic_linux/.env` に記述。パスは Linux/WSL 形式で書くこと。

```env
OPENROUTER_KEY_1=sk-or-...
OPENROUTER_MODEL=openrouter/owl-alpha
RPM_LIMIT=3

GEMINI_KEY_1=AIza...
GEMINI_MODEL=gemini-2.0-flash
RPM_LIMIT_GEMINI=15

SYSTEM_PROMPT=あなたは有能なAIアシスタントです。
DEFAULT_CWD=/home/user/projects    # WSL の場合 /mnt/c/... 形式
```

---

## 設計上の注意点

- `MonitoringToolRegistry` は `ToolRegistry` を継承し `_tools` を参照共有する。コピーではない。
- `BASH_EXECUTOR_GUIDANCE` は後方互換のため `POWERSHELL_EXECUTOR_GUIDANCE` エイリアスあり。
- readline 履歴は `~/.mimic_linux_history` に保存される（最大500件）。
- SIGTERM でグレースフルシャットダウン。SIGHUP は無視（サーバー運用向け）。
- `tools.py` 末尾で `tools_linux` と `pipeline` をインポートすることでツール登録が行われる。
- `monitor.py` の描画は `tmux send-keys` 経由なため、ANSIコードを直接埋め込む。
- `ProcessMonitor` は `os.getpid()` を渡しているため、Pythonプロセス自身のリソースを計測する。
