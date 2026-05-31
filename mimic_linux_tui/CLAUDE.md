# mimic_linux_tui アーキテクチャ概要

mimic_linux の Textual TUI 版。`python3 -m mimic_linux_tui` で起動。
コピー元 (`mimic_linux/`) は一切変更していない。

---

## 起動方法

```bash
# TUI 起動
python3 -m mimic_linux_tui

# または
cd /home/loser/wsl-projects/mimic_linux_tui
./run.sh
```

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `__main__.py` | エントリポイント。エージェント初期化 → MimicApp 起動 |
| `app.py` | Textual アプリ本体。全 UI ロジックを担当 |
| `agent.py` | OpenRouterAgent (mimic_linux からコピー) |
| `orchestrator.py` | オーケストレーター (mimic_linux からコピー) |
| `tools.py` | ToolRegistry (mimic_linux からコピー) |
| `tools_linux.py` | Linux 向けツール (mimic_linux からコピー) |
| `commands.py` | スラッシュコマンド定義 (mimic_linux からコピー) |
| `config.py` | 設定ロード (mimic_linux からコピー) |
| `utils.py` | ユーティリティ (TUI 向け safe_print リダイレクト追加) |
| `autogit.py` | AutoGit (mimic_linux からコピー) |
| `monitoring.py` | MonitoringToolRegistry / ToolCallLog (mimic_linux からコピー) |
| `proc_observer.py` | SystemMonitor (mimic_linux からコピー) |
| `pipeline.py` | run_pipeline (mimic_linux からコピー) |
| `mcp_server.py` | MCP サーバー (mimic_linux からコピー) |
| `.env` | シンボリックリンク → mimic_linux/.env |

コピー元に存在する `monitor.py` と `tmux_orch.py` は tmux 専用のため含めていない。

---

## アーキテクチャ

```
__main__.py
  └─ load_config() + 各種初期化
  └─ MimicApp(agent, orchestrator, ...).run()

MimicApp (app.py)
  ├─ Header
  ├─ RichLog #chat          ← safe_print / PipelineTypewriter の出力先
  ├─ Label #status-bar      ← CPU/MEM/ツール数 (2秒ごと更新)
  ├─ Input #input           ← ユーザー入力
  └─ Footer                 ← キーバインド表示

  on_mount():
    set_tui_print_fn(→ RichLog)   ← safe_print を TUI にリダイレクト
    set_write_approval_handler()  ← ApprovalDialog を表示

  _run_agent() [worker thread]:
    interactive: interactive_orch.run_react(prompt)
    plan:        orchestrator.run_with_plan(prompt, on_step=...)
```

---

## utils.py の変更点 (mimic_linux からの差分)

- `_tui_print_fn` グローバル変数と `set_tui_print_fn()` 関数を追加
- `safe_print`: `_tui_print_fn` が設定済みなら TUI にリダイレクト
- `PipelineTypewriter._run()`: TUI モード時は行単位でバッファして `_tui_print_fn` に流す
- `PipelineTypewriter.feed()`: auto_mode 時も同様に TUI 対応

---

## スラッシュコマンド

| コマンド | 動作 |
|---|---|
| `/help` | ヘルプ表示 |
| `/exit` `/quit` | 終了 |
| `/clear` | チャット + 会話履歴クリア |
| `/mode interactive\|plan` | モード切替 |
| `/status` | エージェント状態表示 |
| `/model` | モデル選択ダイアログ |
| `/undo` | AutoGit ロールバック |
| `/cd <path>` | 作業ディレクトリ変更 |
| `/sessions [番号]` | セッション一覧・詳細 |
| `/stats` | ツール統計 |

---

## キーバインド

| キー | 動作 |
|---|---|
| Ctrl+Q | 終了 |
| Ctrl+C | エージェント中断 |
| PageUp / PageDown | チャットスクロール |
| Y / n | 承認ダイアログで承認 / 却下 |
