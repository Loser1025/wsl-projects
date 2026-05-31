"""mimic_linux TUI — Textual アプリ本体。"""
from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Input, RichLog, Label, ListView, ListItem
from textual.containers import Vertical
from textual import work

if TYPE_CHECKING:
    from pathlib import Path

HELP_TEXT = """\
[bold green]使用可能なコマンド:[/bold green]
  [cyan]/exit[/cyan], [cyan]/quit[/cyan]  — アプリを終了
  [cyan]/help[/cyan]          — このヘルプを表示
  [cyan]/clear[/cyan]         — チャット履歴・会話履歴をクリア
  [cyan]/mode interactive[/cyan] — ReActモード（デフォルト）
  [cyan]/mode plan[/cyan]        — Plan-and-Executeモード
  [cyan]/status[/cyan]       — エージェントの状態を表示
  [cyan]/model[/cyan]        — モデルを選択
  [cyan]/undo[/cyan]         — 直前の変更をロールバック
  [cyan]/cd <path>[/cyan]    — 作業ディレクトリを変更
  [cyan]/sessions[/cyan]     — 過去セッション一覧
  [cyan]/stats[/cyan]        — ツール呼び出し統計

[dim]Ctrl+Q または /exit で終了  /  PageUp・PageDown でスクロール[/dim]"""

_STEP_ICONS = {
    "pending":  "⏳",
    "running":  "▶",
    "done":     "✓",
    "failed":   "✗",
    "retrying": "↻",
    "skipped":  "⊘",
}


# ── モーダル: 書き込み承認 ───────────────────────────────────────────

class ApprovalDialog(ModalScreen[bool]):
    """ファイル書き込み前の確認ダイアログ。Y → True / n → False。"""

    CSS = """
    ApprovalDialog {
        align: center middle;
    }

    #approval-box {
        width: 72;
        max-height: 32;
        border: double $warning;
        background: $surface;
        padding: 1 2;
    }

    #approval-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    #approval-prompt {
        color: $text;
        text-style: bold;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("y", "approve", "[Y] 承認", show=True),
        Binding("n", "reject", "[n] 却下", show=True),
        Binding("escape", "reject", "Esc", show=False),
    ]

    def __init__(self, tool_name: str, path: str, preview: str):
        super().__init__()
        self._tool_name = tool_name
        self._path = path
        self._preview_lines = preview[:1500].splitlines()[:25]

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box"):
            yield Label("  書き込み確認", id="approval-title")
            yield Label(f"  ツール : {self._tool_name}")
            yield Label(f"  ファイル: {self._path}")
            yield Label("")
            for line in self._preview_lines:
                yield Label(f"    {line}")
            yield Label("")
            yield Label("  実行しますか？  [Y] 承認  /  [n] 却下", id="approval-prompt")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)


# ── モーダル: モデル選択 ─────────────────────────────────────────────

class ModelSelectDialog(ModalScreen[Optional[str]]):
    """モデル選択ダイアログ。Enter で選択 / Escape でキャンセル。"""

    CSS = """
    ModelSelectDialog {
        align: center middle;
    }

    #model-box {
        width: 72;
        height: 22;
        border: double $accent;
        background: $surface;
        padding: 1 2;
    }

    #model-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #model-list {
        height: 12;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "キャンセル", show=True),
        Binding("enter", "select", "選択", show=True),
    ]

    def __init__(self, models: list[str], current: str = ""):
        super().__init__()
        self._models = models
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="model-box"):
            yield Label("  モデル選択", id="model-title")
            yield Label(f"  現在: {self._current}")
            yield Label("  ↑↓ で選択 / Enter で確定 / Esc でキャンセル")
            yield Label("")
            yield ListView(
                *[ListItem(Label(m)) for m in self._models],
                id="model-list",
            )

    def action_select(self) -> None:
        lv = self.query_one("#model-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._models):
            self.dismiss(self._models[idx])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── メインアプリ ─────────────────────────────────────────────────────

class MimicApp(App):
    CSS = """
    #chat {
        height: 1fr;
        padding: 0 1;
        background: $surface;
    }

    #status-bar {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
        dock: bottom;
    }

    #input-bar {
        height: auto;
        padding: 0 1 1 1;
        background: $panel;
        dock: bottom;
    }

    Input {
        width: 100%;
    }
    """

    TITLE = "mimic_linux TUI"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+c", "interrupt", "Interrupt", show=True),
        Binding("pageup", "scroll_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_down", "Scroll Down", show=False),
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
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._sys_monitor = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="chat", markup=True, highlight=True, wrap=True)
        yield Label("", id="status-bar")
        with Vertical(id="input-bar"):
            yield Input(placeholder="メッセージを入力... (Ctrl+Q で終了)", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self._event_loop = asyncio.get_event_loop()
        self._setup_tui_print()
        self._setup_approval_handler()
        self._init_sys_monitor()
        self.set_interval(2.0, self._update_status_bar)
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
            chat.write("[dim yellow]エージェント未接続 — デモモード[/dim yellow]")
        chat.write("[dim]/help でコマンド一覧を表示できます。[/dim]")

    def _init_sys_monitor(self) -> None:
        try:
            from .proc_observer import SystemMonitor
            self._sys_monitor = SystemMonitor()
        except Exception:
            self._sys_monitor = None

    def _update_status_bar(self) -> None:
        parts: list[str] = []
        if self._sys_monitor:
            try:
                snap = self._sys_monitor.snapshot()
                parts.append(f"CPU:{snap.cpu_percent:.0f}%")
                parts.append(f"MEM:{snap.mem_percent:.0f}%")
            except Exception:
                pass
        if self.tool_log:
            try:
                n = len(self.tool_log._records) if hasattr(self.tool_log, "_records") else 0
                parts.append(f"ツール:{n}回")
            except Exception:
                pass
        if self.active_config:
            parts.append(f"[{self.active_config.name}] {self._mode}")
        label = self.query_one("#status-bar", Label)
        label.update("  " + " | ".join(parts) if parts else "")

    # ── TUI 出力リダイレクト ────────────────────────────────────────

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

    # ── 書き込み承認ハンドラ ────────────────────────────────────────

    def _setup_approval_handler(self) -> None:
        from .tools import set_write_approval_handler

        def _approval_handler(tool_name: str, args: dict, preview: str) -> bool:
            if self._event_loop is None:
                return True
            path = args.get("path", "?")
            result: list[bool] = [True]
            done = threading.Event()

            async def _show_modal() -> None:
                approved = await self.push_screen_wait(
                    ApprovalDialog(tool_name, path, preview)
                )
                result[0] = bool(approved)
                done.set()

            asyncio.run_coroutine_threadsafe(_show_modal(), self._event_loop)
            done.wait(timeout=30)
            return result[0]

        set_write_approval_handler(_approval_handler)

    # ── スクロール操作 ────────────────────────────────────────────────

    def action_scroll_up(self) -> None:
        self.query_one("#chat", RichLog).scroll_up(amount=10)

    def action_scroll_down(self) -> None:
        self.query_one("#chat", RichLog).scroll_down(amount=10)

    # ── 入力処理 ──────────────────────────────────────────────────────

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
            self._cmd_model_async()

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

    # ── コマンド実装 ───────────────────────────────────────────────────

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

    @work(exclusive=False)
    async def _cmd_model_async(self) -> None:
        chat = self.query_one("#chat", RichLog)
        if self.active_config is None:
            chat.write("[yellow]エージェント未接続です。[/yellow]")
            return

        from .config import load_config
        from pathlib import Path
        base_dir = str(Path(__file__).parent)
        try:
            or_c, gem_c, mis_c, _ = load_config(base_dir)
        except SystemExit:
            or_c = gem_c = mis_c = None

        models: list[str] = []
        if or_c:
            models.append(f"[openrouter] {or_c.model}")
        if gem_c:
            models.append(f"[gemini] {gem_c.model}")
        if mis_c:
            models.append(f"[mistral] {mis_c.model}")

        if not models:
            chat.write("[yellow]利用可能なモデルが見つかりません。[/yellow]")
            return

        current = f"{self.active_config.name}/{self.active_config.model}"
        selected = await self.push_screen_wait(ModelSelectDialog(models, current))

        if selected is None:
            chat.write("[dim]モデル選択をキャンセルしました。[/dim]")
        else:
            chat.write(f"[green]選択されたモデル: {selected}[/green]")
            chat.write("[dim](モデル変更を反映するには再起動が必要です)[/dim]")

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

    # ── エージェント実行 ────────────────────────────────────────────────

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
            import traceback
            result = f"エラー: {e}"
            self.call_from_thread(
                self._write_markup,
                f"[red]{traceback.format_exc()}[/red]"
            )
        finally:
            self._agent_running = False
            self._interrupt_event.clear()
            self.call_from_thread(self._set_input_disabled, False)

        self.call_from_thread(self._on_agent_done, result)

    def _run_plan_mode(self, prompt: str) -> str:
        """Plan-and-Execute モード実行（on_step でリアルタイム表示）。"""
        if self.orchestrator is None:
            return "プランモードのオーケストレーターが未初期化です。"

        def _on_plan(steps) -> None:
            lines = [f"[bold yellow]📋 プラン ({len(steps)} ステップ):[/bold yellow]"]
            for s in steps:
                icon = _STEP_ICONS.get(s.status, "?")
                p = " [並列]" if s.parallel else ""
                lines.append(f"  {icon} {s.index}. {s.description}{p}")
            self.call_from_thread(self._write_markup, "\n".join(lines))

        def _on_step(step) -> None:
            icon = _STEP_ICONS.get(step.status, "?")
            color = {
                "running":  "yellow",
                "done":     "green",
                "failed":   "red",
                "retrying": "yellow",
                "skipped":  "dim",
            }.get(step.status, "white")
            msg = f"[{color}]  {icon} Step {step.index}: {step.description} [{step.status}][/{color}]"
            self.call_from_thread(self._write_markup, msg)

        return self.orchestrator.run_with_plan(
            prompt,
            on_plan=_on_plan,
            on_step=_on_step,
        )

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
