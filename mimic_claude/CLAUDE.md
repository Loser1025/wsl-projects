# mimic_claude アーキテクチャ概要

`mimic_linux` の Textual TUI 版。`python3 -m mimic_claude` で起動。
描画バグを解消するため UI 層を Textual に置き換えたコピー。

---

## ファイル構成

| ファイル | 役割 | mimic_linux 比 |
|---|---|---|
| `app.py` | **新規**: Textual TUI アプリ本体。MimicApp / WriteApprovalModal | 新規 |
| `utils.py` | `safe_print` に TUI コールバック追加 / `PipelineTypewriter` に `tui_mode` 追加 | 修正 |
| `__main__.py` | エントリポイント。readline・tmux 削除。TUI 起動 | 大幅修正 |
| `agent.py` | OpenRouterAgent (ReActループ本体) | 流用 |
| `autogit.py` | AutoGit / ReactLog | 流用 |
| `commands.py` | スラッシュコマンド定義 | 流用 |
| `config.py` | KeyManager / OpenRouterConfig / GoogleAIConfig | 流用 |
| `main.py` | pipe_mode / auto_mode のみ使用（interactive_loop は TUI 起動後は不使用） | 流用 |
| `orchestrator.py` | オーケストレーター | 流用 |
| `tools.py` | ToolRegistry + ファイルIO / web検索 / ブラウザ | 流用 |
| `tools_linux.py` | `run_bash` (pty/プロセスグループ/SIGTERM→SIGKILL) | 流用 |
| `pipeline.py` | `run_pipeline` (大量データ処理) | 流用 |
| `proc_observer.py` | ProcessMonitor / SystemMonitor | 流用 |
| `monitoring.py` | MonitoringToolRegistry / ToolCallLog | 流用 |
| `mcp_server.py` | MCP サーバー | 流用 |
| `monitor.py` | **削除**: tmux 専用のため廃止 | 削除 |
| `tmux_orch.py` | **削除**: tmux 専用のため廃止 | 削除 |

---

## 起動方法

```bash
# 通常起動（TUI インタラクティブモード）
python3 -m mimic_claude

# パイプモード（非対話）
python3 -m mimic_claude --prompt "タスク内容"

# オートモード（MCP連携）
python3 -m mimic_claude --auto-prompt "タスク内容"

# ステータス確認
python3 -m mimic_claude --status
```

---

## TUI アーキテクチャ

### 描画フロー

```
[agent thread]                     [main/asyncio thread]
    │                                      │
    │ safe_print(text)                     │
    │  → _tui_output_callback(text)        │
    │  → call_from_thread(log.write, ...)  │
    │                                 RichLog.write(Text.from_ansi(text))
    │                                      │
    │ PipelineTypewriter.feed(chunk)       │
    │  → _tui_mode=True                    │
    │  → call _tui_output_callback(chunk)  │
    │                                 RichLog.write(Text.from_ansi(chunk))
```

### 書き込み承認フロー

```
[agent thread]                     [main/asyncio thread]
    │                                      │
    │ approval_handler(tool, args, preview)│
    │  → _ApprovalReq を作成              │
    │  → call_from_thread(_show_approval)  │
    │  → req.wait(timeout=30)             │ WriteApprovalModal を push_screen_wait
    │      (threading.Event でブロック)   │ Y/n → req.respond(bool)
    │  ← True/False を受け取る            │
```

### スレッドモデル

- **メインスレッド**: Textual の asyncio イベントループ
- **エージェントスレッド**: `@work(thread=True)` で起動。`call_from_thread()` で UI 更新
- エージェントスレッド中は Input が `disabled=True` → 二重実行防止

---

## UI コンポーネント

### MimicApp

- `Header` - タイトル・モデル名・時計
- `RichLog (#chat-log)` - 全出力（ANSI → Rich Text変換）
- `Input (#user-input)` - ユーザー入力
- `Footer` - キーバインド一覧

### WriteApprovalModal

- ファイル書き込み確認ダイアログ
- Y キー / 承認ボタン → True を返す
- n キー / Escape / 拒否ボタン → False を返す
- 30秒タイムアウトで自動承認（`_ApprovalReq.wait()`）

---

## キーバインド

| キー | 動作 |
|---|---|
| Enter | メッセージ送信 / コマンド実行 |
| Ctrl+Q | 終了 |
| Ctrl+L | 画面クリア |
| PageUp | スクロール上 |
| PageDown | スクロール下 |
| Ctrl+Home | 先頭へ |
| Ctrl+End | 末尾へ |

---

## TUI 版スラッシュコマンド

| コマンド | 動作 | 変更点 |
|---|---|---|
| `/mode interactive\|plan` | モード切り替え | TUI 内で処理 |
| `/model [名前]` | モデル確認・変更 | stdin なしで処理（選択UI なし） |
| `/search <クエリ>` | 過去セッション検索 | 全件自動注入（選択ダイアログなし） |
| `/undo` | AutoGit ロールバック | TUI 内で処理 |
| `/clear` | 画面 + 会話履歴クリア | TUI 内で処理 |
| `/status` | モデル・キー状態表示 | safe_print 経由でログに出力 |
| `/stats` | ツール統計 | safe_print 経由でログに出力 |
| `/help` | コマンド一覧 | safe_print 経由でログに出力 |
| `/cd <パス>` | 作業ディレクトリ変更 | safe_print 経由でログに出力 |
| `/sessions [番号]` | セッション一覧 | safe_print 経由でログに出力 |
| `exit` / `quit` / `q` | TUI 終了 | TUI 内で処理 |

---

## utils.py の変更点

### `safe_print` TUI ブリッジ

```python
# 追加された関数
set_tui_output(fn)  # コールバック登録（None で解除）
set_tui_mode(bool)  # PipelineTypewriter 用フラグ

# 変更された関数
safe_print(*args, **kwargs)
# _tui_output_callback が設定されていればそちらへ、
# なければ従来の print() 動作
```

### `PipelineTypewriter` TUI モード

```python
PipelineTypewriter(auto_mode=False)
# _tui_mode_global=True のとき:
#   - start() でスレッドを起動しない
#   - feed(chunk) で直接 _tui_output_callback(chunk) を呼ぶ
#   - finalize() でバッファのフラッシュなし（即時送信済み）
```

---

## .env 設定

`mimic_claude/.env` に記述（mimic_linux と同じ形式）。

```env
OPENROUTER_KEY_1=sk-or-...
OPENROUTER_MODEL=openrouter/owl-alpha
RPM_LIMIT=3

GEMINI_KEY_1=AIza...
GEMINI_MODEL=gemini-2.0-flash
RPM_LIMIT_GEMINI=15

SYSTEM_PROMPT=あなたは有能なAIアシスタントです。
DEFAULT_CWD=/home/user/projects
```
