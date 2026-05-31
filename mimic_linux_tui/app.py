"""mimic_linux TUI — Textual アプリ本体。"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Input, RichLog
from textual.containers import Vertical
from textual import work

if TYPE_CHECKING:
    from pathlib import Path
    from .agent import OpenRouterAgent
    from .orchestrator import AgentOrchestrator, InteractiveOrchestrator
    from .autogit import AutoGit
    from .monitoring import ToolCallLog

HELP_TEXT = """\
[bold green]使用可能なコマンド:[/bold green]
  [cyan]/exit[/cyan], [cyan]/quit[/cyan]  — アプリを終了
  [cyan]/help[/cyan]          — このヘルプを表示
  [cyan]/clear[/cyan]         — チャット履歴・会話履歴をクリア
  [cyan]/mode interactive[/cyan] — ReActモード（デフォルト）
  [cyan]/mode plan[/cyan]        — Plan-and-Executeモード
  [cyan]/status[/cyan]       — エージェントの状態を表示
  [cyan]/model[/cyan]        — モデルを選択（Phase 5）
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

    #status-label {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }
    """

    TITLE = "mimic_linux TUI"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+c", "interrupt", "Interrupt", show=True),
    ]

    def __init__(
        self,
        agent=None,
        orchestrator=None,
        interactive_orch=None,
        auto_git=None,
        active_config=None,
        tool_log=None,
        sessions_dir=None,
        plan_prompt: str = "",
        react_prompt: str = "",
    ):
        super().__init__()
        self.agent = agent
        self.orchestrator = orchestrator
        self.interactive_orch = interactive_orch
        self.auto_git = auto_git
        self.active_config = active_config
        self.tool_log = tool_log
        self.sessions_dir = sessions_dir
        self._plan_prompt = plan_prompt
        self._react_prompt = react_prompt
        self._mode: str = "interactive"
        self._agent_running = False
        self._interrupt_event = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="chat", markup=True, highlight=True, wrap=True)
        with Vertical(id="input-bar"):
            yield Input(placeholder="メッセージを入力... (Ctrl+Q で終了)", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self._setup_tui_print()
        self._setup_approval_handler()
        self.query_one("#input", Input).focus()
        chat = self.query_one("#chat", RichLog)
        chat.write("[bold green]mimic_linux TUI へようこそ。[/bold green]")
        if self.active_config:
            chat.write(
                f"[dim]プロバイダー: {self.active_config.name} | "
                f"モデル: {self.active_config.model}[/dim]"
            )
            chat.write(f"[dim]CWD: {getattr(self.agent, 'cwd', '?')}[/dim]")
        else:
            chat.write("[dim yellow]エージェント未接続 — Phase 3 で統合予定[/dim yellow]")
        chat.write("[dim]/help でコマンド一覧を表示できます。[/dim]")

    # ── TUI 出力リダイレクト ──────────────────────────────────────────

    def _setup_tui_print(self) -> None:
        from .utils import set_tui_print_fn

        def _tui_write(text: str) -> None:
            self.call_from_thread(self._write_ansi, text)

        set_tui_print_fn(_tui_write)

    def _write_ansi(self, text: str) -> None:
        chat = self.query_one("#chat", RichLog)
        rich_text = Text.from_ansi(text)
        chat.write(rich_text)

    def _write_markup(self, text: str) -> None:
        chat = self.query_one("#chat", RichLog)
        chat.write(text)

    # ── 書き込み承認ハンドラ（Phase 5 でモーダル化） ────────────────

    def _setup_approval_handler(self) -> None:
        from .tools import set_write_approval_handler

        def _approval_handler(tool_name: str, args: dict, preview: str) -> bool:
            path = args.get("path", "?")
            # Phase 5 まではコンソール確認なしで自動承認
            self.call_from_thread(
                self._write_markup,
                f"[yellow]  書き込み承認: {tool_name} → {path} (自動承認)[/yellow]"
            )
            return True

        set_write_approval_handler(_approval_handler)

    # ── 入力処理 ────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.clear()
        if not value:
            return
        if self._agent_running:
            chat = self.query_one("#chat", RichLog)
            chat.write("[dim red]エージェント実行中です。Ctrl+C で中断できます。[/dim red]")
            return
        self._handle_input(value)

    def _handle_input(self, value: str) -> None:
        chat = self.query_one("#chat", RichLog)

        if value.startswith("/"):
            self._handle_command(value, chat)
            return

        chat.write(f"[bold cyan]You:[/bold cyan] {value}")

        if self.agent is None:
            chat.write("[dim yellow]（エージェント未接続）[/dim yellow]")
            return

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
            chat.write("[dim]チャット・会話履歴をクリアしました。[/dim]")

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
            chat.write("[yellow]/model は Phase 5 で実装されます。[/yellow]")

        elif cmd == "/undo":
            self._cmd_undo(chat)

        elif cmd == "/cd":
            self._cmd_cd(args.strip(), chat)

        elif cmd == "/sessions":
            self._cmd_sessions(args.strip(), chat)

        elif cmd == "/stats":
            self._cmd_stats(chat)

        else:
            chat.write(f"[red]不明なコマンド: {cmd}（/help で一覧確認）[/red]")

    # ── コマンド実装 ────────────────────────────────────────────────────

    def _cmd_status(self, chat: RichLog) -> None:
        if self.active_config is None:
            chat.write("[yellow]エージェント未接続です。[/yellow]")
            return
        cwd = getattr(self.agent, "cwd", "?")
        history_len = len(getattr(self.agent, "conversation", []))
        chat.write(
            f"[bold]プロバイダー:[/bold] {self.active_config.name}\n"
            f"[bold]モデル:[/bold]       {self.active_config.model}\n"
            f"[bold]モード:[/bold]       {self._mode}\n"
            f"[bold]CWD:[/bold]         {cwd}\n"
            f"[bold]会話履歴:[/bold]    {history_len} メッセージ"
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

    def _cmd_sessions(self, args: str, chat: RichLog) -> None:
        if self.sessions_dir is None:
            chat.write("[yellow]セッションディレクトリが設定されていません。[/yellow]")
            return
        from pathlib import Path
        sessions = sorted(Path(self.sessions_dir).glob("*.jsonl"), reverse=True)
        if not sessions:
            chat.write("[dim]セッションが見つかりません。[/dim]")
            return

        if args.isdigit():
            idx = int(args) - 1
            if 0 <= idx < len(sessions):
                self._show_session_detail(sessions[idx], chat)
            else:
                chat.write(f"[red]番号が範囲外です: {args}[/red]")
            return

        lines = ["[bold]過去のセッション:[/bold]"]
        for i, s in enumerate(sessions[:20], 1):
            lines.append(f"  [cyan]{i:2d}.[/cyan] {s.stem}")
        chat.write("\n".join(lines))

    def _show_session_detail(self, path, chat: RichLog) -> None:
        import json
        lines = ["[bold]セッション詳細:[/bold] " + path.stem]
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    event = rec.get("event", "?")
                    content = str(rec.get("content", ""))[:120]
                    lines.append(f"  [dim]{event}:[/dim] {content}")
        except Exception as e:
            lines.append(f"[red]読み込みエラー: {e}[/red]")
        chat.write("\n".join(lines))

    def _cmd_stats(self, chat: RichLog) -> None:
        if self.tool_log is None:
            chat.write("[yellow]ツールログが初期化されていません。[/yellow]")
            return
        chat.write(self.tool_log.stats_text())

    # ── エージェント実行 ─────────────────────────────────────────────

    def action_interrupt(self) -> None:
        if self._agent_running:
            self._interrupt_event.set()
            chat = self.query_one("#chat", RichLog)
            chat.write("[yellow]  [割り込み] 中断を要求しました...[/yellow]")

    @work(thread=True, exclusive=True)
    def _run_agent(self, prompt: str) -> None:
        self._agent_running = True
        self._interrupt_event.clear()
        self.call_from_thread(self._set_input_disabled, True)

        try:
            if self._mode == "interactive":
                result = self.interactive_orch.run_react(prompt)
            else:
                result = self._run_plan_mode(prompt)
        except Exception as e:
            result = f"エラー: {e}"
        finally:
            self._agent_running = False
            self._interrupt_event.clear()
            self.call_from_thread(self._set_input_disabled, False)

        self.call_from_thread(self._on_agent_done, result)

    def _run_plan_mode(self, prompt: str) -> str:
        if self.orchestrator is None:
            return "プランモードのオーケストレーターが未初期化です。"
        return self.orchestrator.run_with_plan(prompt)

    def _set_input_disabled(self, disabled: bool) -> None:
        inp = self.query_one("#input", Input)
        inp.disabled = disabled
        if not disabled:
            inp.focus()
            inp.placeholder = "メッセージを入力... (Ctrl+Q で終了)"
        else:
            inp.placeholder = "エージェント実行中... (Ctrl+C で中断)"

    def _on_agent_done(self, result: str) -> None:
        chat = self.query_one("#chat", RichLog)
        chat.write("[dim green]── 完了 ──[/dim green]")
