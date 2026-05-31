"""mimic_linux TUI — Textual アプリ本体。"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Input, RichLog
from textual.containers import Vertical

HELP_TEXT = """\
[bold green]使用可能なコマンド:[/bold green]
  [cyan]/exit[/cyan], [cyan]/quit[/cyan]  — アプリを終了
  [cyan]/help[/cyan]          — このヘルプを表示
  [cyan]/clear[/cyan]         — チャット履歴をクリア
  [cyan]/mode interactive[/cyan] — ReActモード
  [cyan]/mode plan[/cyan]        — Plan-and-Executeモード
  [cyan]/status[/cyan]       — エージェントの状態を表示
  [cyan]/model[/cyan]        — モデルを選択
  [cyan]/undo[/cyan]         — 直前の変更をロールバック
  [cyan]/cd <path>[/cyan]    — 作業ディレクトリを変更
  [cyan]/sessions[/cyan]     — 過去セッション一覧
  [cyan]/stats[/cyan]        — ツール呼び出し統計

[dim]Ctrl+Q または /exit で終了[/dim]"""


class MimicApp(App):
    CSS = """
    #chat {
        height: 1fr;
        padding: 0 1;
        background: $surface;
    }

    #input-bar {
        height: auto;
        padding: 0 1 1 1;
        background: $panel;
    }

    Input {
        width: 100%;
    }
    """

    TITLE = "mimic_linux TUI"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    # エージェント（Phase 3 で設定）
    agent = None
    orchestrator = None
    interactive_orch = None
    auto_git = None
    active_config = None
    tool_log = None
    sessions_dir = None
    _mode: str = "interactive"

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="chat", markup=True, highlight=True, wrap=True)
        with Vertical(id="input-bar"):
            yield Input(placeholder="メッセージを入力... (Ctrl+Q で終了)", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()
        chat = self.query_one("#chat", RichLog)
        chat.write("[bold green]mimic_linux TUI へようこそ。[/bold green]")
        chat.write("[dim]/help でコマンド一覧を表示できます。[/dim]")

    # ── 入力処理 ────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.clear()
        if not value:
            return
        self._handle_input(value)

    def _handle_input(self, value: str) -> None:
        chat = self.query_one("#chat", RichLog)

        # スラッシュコマンド処理
        if value.startswith("/"):
            self._handle_command(value, chat)
            return

        # エージェント未接続時はエコー
        if self.agent is None:
            chat.write(f"[bold cyan]You:[/bold cyan] {value}")
            chat.write("[dim yellow]（エージェント未接続 — Phase 3 で統合予定）[/dim yellow]")
            return

        # Phase 3 以降: エージェント呼び出し
        chat.write(f"[bold cyan]You:[/bold cyan] {value}")
        self._run_agent(value)

    def _handle_command(self, value: str, chat: RichLog) -> None:
        parts = value.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            self.exit()

        elif cmd == "/help":
            chat.write(HELP_TEXT)

        elif cmd == "/clear":
            chat.clear()
            if self.agent is not None and hasattr(self.agent, "conversation"):
                self.agent.conversation.clear()
            chat.write("[dim]チャット履歴をクリアしました。[/dim]")

        elif cmd == "/mode":
            mode = args.strip().lower()
            if mode in ("interactive", "plan"):
                self._mode = mode
                chat.write(f"[green]モードを [bold]{mode}[/bold] に切り替えました。[/green]")
            else:
                chat.write("[red]使用法: /mode interactive または /mode plan[/red]")

        elif cmd == "/status":
            self._cmd_status(chat)

        elif cmd == "/model":
            chat.write("[yellow]/model コマンドは Phase 5 で実装予定です。[/yellow]")

        elif cmd == "/undo":
            self._cmd_undo(chat)

        elif cmd == "/cd":
            self._cmd_cd(args.strip(), chat)

        elif cmd == "/sessions":
            chat.write("[yellow]/sessions コマンドは Phase 4 で実装予定です。[/yellow]")

        elif cmd == "/stats":
            self._cmd_stats(chat)

        else:
            chat.write(f"[red]不明なコマンド: {cmd}（/help で一覧確認）[/red]")

    def _cmd_status(self, chat: RichLog) -> None:
        if self.active_config is None:
            chat.write("[yellow]エージェント未接続です。[/yellow]")
            return
        chat.write(
            f"[bold]プロバイダー:[/bold] {self.active_config.name}\n"
            f"[bold]モデル:[/bold] {self.active_config.model}\n"
            f"[bold]モード:[/bold] {self._mode}\n"
            f"[bold]CWD:[/bold] {getattr(self.agent, 'cwd', '?')}"
        )

    def _cmd_undo(self, chat: RichLog) -> None:
        if self.auto_git is None:
            chat.write("[yellow]AutoGit が初期化されていません。[/yellow]")
            return
        try:
            result = self.auto_git.rollback()
            chat.write(f"[green]ロールバック完了: {result}[/green]")
        except Exception as e:
            chat.write(f"[red]ロールバック失敗: {e}[/red]")

    def _cmd_cd(self, path: str, chat: RichLog) -> None:
        import os
        from pathlib import Path
        if not path:
            chat.write(f"[bold]現在のCWD:[/bold] {getattr(self.agent, 'cwd', '?')}")
            return
        expanded = os.path.expanduser(path)
        resolved = Path(expanded).resolve()
        if not resolved.exists():
            chat.write(f"[red]ディレクトリが見つかりません: {resolved}[/red]")
            return
        if self.agent is not None:
            self.agent.cwd = str(resolved)
        chat.write(f"[green]CWD を変更しました: {resolved}[/green]")

    def _cmd_stats(self, chat: RichLog) -> None:
        if self.tool_log is None:
            chat.write("[yellow]ツールログが初期化されていません。[/yellow]")
            return
        chat.write(self.tool_log.stats_text())

    # ── エージェント呼び出し（Phase 3 で実装） ─────────────────────────

    def _run_agent(self, prompt: str) -> None:
        chat = self.query_one("#chat", RichLog)
        chat.write("[dim yellow]エージェント呼び出し未実装です。[/dim yellow]")
