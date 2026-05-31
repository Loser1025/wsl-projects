"""mimic_claude Textual TUI アプリ本体。"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import TYPE_CHECKING

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static

if TYPE_CHECKING:
    pass


# ── 承認リクエスト用ヘルパー ──────────────────────────────────────────

class _ApprovalReq:
    """エージェントスレッドから書き込み承認を要求するためのオブジェクト。"""
    def __init__(self, tool_name: str, args: dict, preview: str):
        self.tool_name = tool_name
        self.args      = args
        self.preview   = preview
        self._q: queue.Queue[bool] = queue.Queue(maxsize=1)

    def respond(self, approved: bool) -> None:
        self._q.put(approved)

    def wait(self, timeout: float = 30.0) -> bool:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return True  # タイムアウト → 自動承認（元の動作と同様）


# ── 書き込み承認ダイアログ ────────────────────────────────────────────

class WriteApprovalModal(ModalScreen):
    """ファイル書き込み確認ダイアログ。Y/n または ボタンで応答する。"""

    DEFAULT_CSS = """
    WriteApprovalModal {
        align: center middle;
    }
    WriteApprovalModal > Vertical {
        background: #0a1a0a;
        border: solid #00ff41;
        padding: 1 2;
        width: 72;
        max-height: 32;
    }
    WriteApprovalModal .title {
        text-style: bold;
        color: #00ff41;
        margin-bottom: 1;
    }
    WriteApprovalModal .meta {
        color: #00c864;
    }
    WriteApprovalModal .preview-box {
        color: #00c864;
        background: #050f05;
        border: solid #00a02d;
        height: 12;
        overflow-y: auto;
        padding: 0 1;
        margin-top: 1;
    }
    WriteApprovalModal .buttons {
        layout: horizontal;
        align: center middle;
        height: 3;
        margin-top: 1;
    }
    WriteApprovalModal Button {
        width: 14;
        margin: 0 1;
    }
    """

    def __init__(self, req: _ApprovalReq):
        super().__init__()
        self._req = req

    def compose(self) -> ComposeResult:
        path    = self._req.args.get("path", "?")
        preview = self._req.preview[:800] if self._req.preview else "(プレビューなし)"
        with Vertical():
            yield Label("書き込み確認", classes="title")
            yield Label(f"ツール : {self._req.tool_name}", classes="meta")
            yield Label(f"ファイル: {path}", classes="meta")
            yield Static(preview, classes="preview-box")
            with Vertical(classes="buttons"):
                yield Button("承認 [Y]", id="yes", variant="success")
                yield Button("拒否 [n]", id="no",  variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)


# ── メインアプリ ──────────────────────────────────────────────────────

class MimicApp(App):
    """mimic_claude Textual TUI アプリ。"""

    TITLE = "mimic_claude"

    CSS = """
    Screen {
        layout: vertical;
        background: #050f05;
    }
    #chat-log {
        height: 1fr;
        border: solid #00a02d;
        background: #050f05;
        scrollbar-color: #00ff41;
        padding: 0 1;
    }
    #input-bar {
        height: 3;
        border: solid #00ff41;
        padding: 0 1;
    }
    Input {
        background: #050f05;
        color: #ffffff;
        border: none;
    }
    Footer {
        background: #050f05;
        color: #00c864;
    }
    Header {
        background: #050f05;
        color: #00ff41;
    }
    """

    BINDINGS = [
        ("ctrl+q",    "quit_app",    "終了"),
        ("ctrl+l",    "clear_log",   "画面クリア"),
        ("pageup",    "scroll_up",   "↑"),
        ("pagedown",  "scroll_down", "↓"),
        ("ctrl+home", "scroll_top",  "先頭"),
        ("ctrl+end",  "scroll_end",  "末尾"),
    ]

    def __init__(self, ctx: dict):
        super().__init__()
        self._ctx           = ctx
        self._current_mode  = "interactive"
        self._log: RichLog | None = None
        self._agent_busy    = False

    # ── 構成 ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="chat-log", highlight=False, markup=False, wrap=True)
        with Vertical(id="input-bar"):
            yield Input(
                placeholder="❯ メッセージを入力  (/help でコマンド一覧)",
                id="user-input",
            )
        yield Footer()

    # ── 初期化 ────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        from .utils import set_tui_output, set_tui_mode
        from .tools import set_write_approval_handler

        self._log = self.query_one("#chat-log", RichLog)

        set_tui_mode(True)
        set_tui_output(self._output_callback)
        set_write_approval_handler(self._make_approval_handler())

        cfg = self._ctx["active_config"]
        self.sub_title = f"{cfg.model}  ·  {self._ctx['agent'].cwd}"

        self._write_direct("mimic_claude TUI\n")
        self._write_direct(f"モデル : {cfg.model}\n")
        self._write_direct(f"作業Dir: {self._ctx['agent'].cwd}\n")
        self._write_direct("─" * 60 + "\n")
        self.query_one("#user-input", Input).focus()

    # ── 出力コールバック ──────────────────────────────────────────────

    def _output_callback(self, text: str) -> None:
        """safe_print / PipelineTypewriter から呼ばれる。どのスレッドからでも安全。"""
        if self._log is None:
            return
        try:
            rich_text = Text.from_ansi(text)
            self.call_from_thread(self._log.write, rich_text)
        except Exception:
            pass

    def _write_direct(self, text: str) -> None:
        """メインスレッドから直接 RichLog に書く（call_from_thread 不要）。"""
        if self._log is None:
            return
        self._log.write(Text.from_ansi(text))

    # ── 書き込み承認 ──────────────────────────────────────────────────

    def _make_approval_handler(self):
        """エージェントスレッドから呼ばれる書き込み承認ハンドラを返す。"""
        app = self

        def handler(tool_name: str, args: dict, preview: str) -> bool:
            req = _ApprovalReq(tool_name, args, preview)
            app.call_from_thread(app._show_approval, req)
            return req.wait(timeout=30)

        return handler

    def _show_approval(self, req: _ApprovalReq) -> None:
        """メインスレッドで承認モーダルを表示し、結果を req に返す。"""
        async def _push() -> None:
            result = await self.push_screen_wait(WriteApprovalModal(req))
            req.respond(bool(result))

        asyncio.ensure_future(_push())

    # ── キーバインド・アクション ──────────────────────────────────────

    def action_quit_app(self) -> None:
        from .utils import set_tui_output, set_tui_mode
        set_tui_mode(False)
        set_tui_output(None)
        self.exit()

    def action_clear_log(self) -> None:
        if self._log:
            self._log.clear()

    def action_scroll_up(self) -> None:
        if self._log:
            self._log.scroll_page_up()

    def action_scroll_down(self) -> None:
        if self._log:
            self._log.scroll_page_down()

    def action_scroll_top(self) -> None:
        if self._log:
            self._log.scroll_home()

    def action_scroll_end(self) -> None:
        if self._log:
            self._log.scroll_end()

    # ── 入力処理 ──────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return

        if text.lower() in ("exit", "quit", "q"):
            self.action_quit_app()
            return

        if text.startswith("/"):
            self._handle_command(text)
            return

        if self._agent_busy:
            self._write_direct("⚠ エージェント実行中です。完了後に入力してください。\n")
            return

        self._write_direct(f"\n⚡ ❯ {text}\n")
        self._start_agent(text)

    # ── コマンド処理 ──────────────────────────────────────────────────

    def _handle_command(self, text: str) -> None:
        """スラッシュコマンドをルーティングする。"""
        from .commands import cmd_registry

        parts = text.lstrip("/").split()
        cmd   = parts[0].lower() if parts else ""
        rest  = text[len(parts[0]) + 1:].strip() if len(parts) > 1 else ""

        # TUI 独自処理が必要なコマンド
        if cmd in ("exit", "quit"):
            self.action_quit_app()
            return

        if cmd == "clear":
            self.action_clear_log()
            self._ctx["agent"].clear_history()
            self._write_direct("会話履歴と画面をクリアしました。\n")
            return

        if cmd == "mode":
            self._cmd_mode(rest)
            return

        if cmd == "model":
            self._cmd_model(rest)
            return

        if cmd == "search":
            self._cmd_search_tui(rest)
            return

        if cmd == "undo":
            result = self._ctx["auto_git"].rollback(self._ctx["agent"].cwd)
            self._write_direct(f"  [AutoGit] {result}\n")
            return

        # cmd_registry に委譲（safe_print → _output_callback でログに出る）
        match = cmd_registry.route(text)
        if match:
            _, handler, args = match
            handler(self._ctx["agent"], args)
        else:
            self._write_direct(
                f"  不明なコマンド: {text}\n"
                "  /help でコマンド一覧を確認してください。\n"
            )

    def _cmd_mode(self, arg: str) -> None:
        arg = arg.strip().lower()
        if arg in ("interactive", "react", "i"):
            self._current_mode = "interactive"
            self._ctx["agent"].set_system_prompt(self._ctx["react_prompt"])
            self._ctx["agent"].clear_history()
            self._write_direct("⚡ モード: Interactive (ReAct)  会話履歴をリセットしました。\n")
        elif arg in ("plan", "p"):
            self._current_mode = "plan"
            self._ctx["agent"].set_system_prompt(self._ctx["plan_prompt"])
            self._ctx["agent"].clear_history()
            self._write_direct("≡  モード: Plan-and-Execute  会話履歴をリセットしました。\n")
        else:
            label = "Interactive (ReAct)" if self._current_mode == "interactive" else "Plan-and-Execute"
            self._write_direct(
                f"  現在: {label}\n"
                "  切替: /mode interactive  /mode plan\n"
            )

    def _cmd_model(self, arg: str) -> None:
        if arg:
            self._ctx["agent"]._config.model = arg
            self._ctx["agent"].clear_history()
            self._write_direct(f"✓ モデルを変更しました: {arg}\n  会話履歴をリセットしました。\n")
            self.sub_title = f"{arg}  ·  {self._ctx['agent'].cwd}"
        else:
            current = self._ctx["agent"]._config.model
            self._write_direct(
                f"  現在のモデル: {current}\n"
                "  変更: /model <モデル名>\n"
            )

    def _cmd_search_tui(self, query: str) -> None:
        """TUI版 /search: ヒット表示 + 全件をコンテキストに自動注入する。"""
        from .commands import _search_sessions

        if not query:
            self._write_direct("  使い方: /search <検索ワード>\n")
            return

        sd   = self._ctx["sessions_dir"]
        hits = _search_sessions(sd, query)
        if not hits:
            self._write_direct(f"  「{query}」に一致するログが見つかりませんでした。\n")
            return

        self._write_direct(f"\n🔍 「{query}」 — {len(hits)} 件ヒット\n")
        for i, h in enumerate(hits, 1):
            self._write_direct(f"  [{i}] {h['file']}  {h['ts']}\n")
            self._write_direct(f"    Q: {h['user'][:100]}\n")
            if h["result"]:
                self._write_direct(f"    A: {h['result'][:150]}\n")

        # 全件をコンテキストに注入
        lines = [f"[過去セッションの参考情報（/search {query}）]"]
        for h in hits:
            lines.append(f"\nUser: {h['full_user']}")
            if h["full_result"]:
                lines.append(f"Result: {h['full_result']}")
        inject_text = "\n".join(lines)
        agent = self._ctx["agent"]
        agent.conversation.append({"role": "user",      "content": inject_text})
        agent.conversation.append({"role": "assistant", "content": "了解しました。参考情報を確認しました。"})
        self._write_direct(f"  ✓ {len(hits)} 件をコンテキストに注入しました。\n")

    # ── エージェント実行 ──────────────────────────────────────────────

    def _start_agent(self, user_input: str) -> None:
        self._agent_busy = True
        inp = self.query_one("#user-input", Input)
        inp.disabled    = True
        inp.placeholder = "⏳ 実行中..."
        if self._current_mode == "interactive":
            self._run_react(user_input)
        else:
            self._run_plan(user_input)

    def _on_agent_done(self) -> None:
        """エージェント完了後にメインスレッドで呼ばれる。"""
        self._agent_busy = False
        inp = self.query_one("#user-input", Input)
        inp.disabled    = False
        inp.placeholder = "❯ メッセージを入力  (/help でコマンド一覧)"
        if self._log:
            self._log.write(Text.from_ansi("\n" + "─" * 60 + "\n"))
        inp.focus()

    @work(thread=True)
    def _run_react(self, user_input: str) -> None:
        try:
            self._ctx["interactive_orch"].run_react(user_input)
        except Exception as e:
            msg = f"\nエラー: {e}\n"
            self.call_from_thread(
                self._log.write, Text.from_ansi(msg)
            )
        finally:
            self.call_from_thread(self._on_agent_done)

    @work(thread=True)
    def _run_plan(self, user_input: str) -> None:
        def on_plan(steps: list) -> None:
            self.call_from_thread(self._show_plan_header, steps)

        def on_step(step) -> None:
            icons = {
                "running":  "▶",
                "done":     "✓",
                "failed":   "✗",
                "retrying": "↻",
                "skipped":  "⏭",
            }
            icon     = icons.get(step.status, " ")
            parallel = " ⚡" if getattr(step, "parallel", False) else ""
            msg = f"  {icon} Step {step.index}: {step.description}{parallel}\n"
            if self._log:
                self.call_from_thread(self._log.write, Text.from_ansi(msg))

        try:
            self._ctx["orchestrator"].run_with_plan(
                user_input,
                on_plan = on_plan,
                on_step = on_step,
            )
        except Exception as e:
            msg = f"\nプランエラー: {e}\n"
            if self._log:
                self.call_from_thread(self._log.write, Text.from_ansi(msg))
        finally:
            self.call_from_thread(self._on_agent_done)

    def _show_plan_header(self, steps: list) -> None:
        """メインスレッドでプラン一覧を表示する。"""
        self._write_direct("\n実行計画\n" + "─" * 40 + "\n")
        for s in steps:
            parallel = " [並列]" if s.parallel else ""
            self._write_direct(f"  Step {s.index}: {s.description}{parallel}\n")
        self._write_direct("─" * 40 + "\n\n")
