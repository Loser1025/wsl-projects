"""mimic_claude Textual TUI アプリ本体。"""
from __future__ import annotations

import asyncio
import ctypes
import queue
import threading
from typing import Optional

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static


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
    """ファイル書き込み確認ダイアログ。Y/n またはボタンで応答する。"""

    DEFAULT_CSS = """
    WriteApprovalModal { align: center middle; }
    WriteApprovalModal > Vertical {
        background: #0a1a0a; border: solid #00ff41;
        padding: 1 2; width: 72; max-height: 32;
    }
    WriteApprovalModal .title  { text-style: bold; color: #00ff41; margin-bottom: 1; }
    WriteApprovalModal .meta   { color: #00c864; }
    WriteApprovalModal .preview-box {
        color: #00c864; background: #050f05; border: solid #00a02d;
        height: 12; overflow-y: auto; padding: 0 1; margin-top: 1;
    }
    WriteApprovalModal .buttons {
        layout: horizontal; align: center middle; height: 3; margin-top: 1;
    }
    WriteApprovalModal Button { width: 14; margin: 0 1; }
    """

    BINDINGS = [
        Binding("y",      "approve", "[Y] 承認", show=True),
        Binding("n",      "reject",  "[n] 却下", show=True),
        Binding("escape", "reject",  "Esc",       show=False),
    ]

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

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


# ── /search 注入選択ダイアログ ────────────────────────────────────────

class SearchSelectionModal(ModalScreen):
    """過去セッション検索の注入選択ダイアログ。元の CLI と同じ入力形式。"""

    DEFAULT_CSS = """
    SearchSelectionModal { align: center middle; }
    SearchSelectionModal > Vertical {
        background: #0a1a0a; border: solid #00ff41;
        padding: 1 2; width: 76; max-height: 36;
    }
    SearchSelectionModal .title  { text-style: bold; color: #00ff41; margin-bottom: 1; }
    SearchSelectionModal .hit    { color: #00c864; }
    SearchSelectionModal .hint   { color: #00dcb4; margin-top: 1; }
    SearchSelectionModal Input   { margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "キャンセル", show=True)]

    def __init__(self, query: str, hits: list[dict]):
        super().__init__()
        self._query = query
        self._hits  = hits

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"🔍 「{self._query}」 — {len(self._hits)} 件ヒット",
                classes="title",
            )
            for i, h in enumerate(self._hits, 1):
                yield Label(f"  [{i}] {h['file']}  {h['ts']}", classes="hit")
                yield Label(f"    Q: {h['user'][:80]}", classes="hit")
                if h["result"]:
                    yield Label(f"    A: {h['result'][:100]}", classes="hit")
            yield Label(
                "コンテキストに注入しますか？\n"
                "  番号をカンマ区切り / all で全件 / Enter か n でキャンセル",
                classes="hint",
            )
            yield Input(placeholder="例: 1,3  /  all  /  n", id="sel-input")

    def on_mount(self) -> None:
        self.query_one("#sel-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


# ── メインアプリ ──────────────────────────────────────────────────────

class MimicApp(App):
    """mimic_claude Textual TUI アプリ。"""

    TITLE = "mimic_claude"

    CSS = """
    Screen    { layout: vertical; background: #050f05; }
    #chat-log { height: 1fr; border: solid #00a02d; background: #050f05;
                scrollbar-color: #00ff41; padding: 0 1; }
    #input-bar { height: 3; border: solid #00ff41; padding: 0 1; }
    Input     { background: #050f05; color: #ffffff; border: none; }
    Footer    { background: #050f05; color: #00c864; }
    Header    { background: #050f05; color: #00ff41; }
    """

    BINDINGS = [
        Binding("ctrl+c",    "interrupt",   "中断",     show=True),
        Binding("ctrl+q",    "quit_app",    "終了",     show=True),
        Binding("ctrl+l",    "clear_log",   "画面クリア", show=False),
        Binding("pageup",    "scroll_up",   "↑",        show=False),
        Binding("pagedown",  "scroll_down", "↓",        show=False),
        Binding("ctrl+home", "scroll_top",  "先頭",     show=False),
        Binding("ctrl+end",  "scroll_end",  "末尾",     show=False),
    ]

    def __init__(self, ctx: dict):
        super().__init__()
        self._ctx                         = ctx
        self._current_mode                = "interactive"
        self._log: Optional[RichLog]      = None
        self._agent_busy                  = False
        self._worker_thread_id: Optional[int] = None  # Ctrl+C 中断用
        # 行バッファ: RichLog.write() は1呼び出し=1行のため \n 単位で書く
        self._out_buf      = ""
        self._out_buf_lock = threading.Lock()

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
        """safe_print / PipelineTypewriter から呼ばれる。どのスレッドからでも安全。
        RichLog.write() は 1 呼び出し = 1 行扱いなので \n 単位でバッファしてから書く。
        """
        if self._log is None:
            return
        with self._out_buf_lock:
            self._out_buf += text
            lines = self._out_buf.split("\n")
            self._out_buf = lines[-1]          # 末尾の未完行をバッファに残す
            complete = lines[:-1]
        for line in complete:
            try:
                self.call_from_thread(self._log.write, Text.from_ansi(line))
            except Exception:
                pass

    def _flush_output_buf(self) -> None:
        """未完行バッファを強制フラッシュする（エージェント完了時に呼ぶ）。"""
        with self._out_buf_lock:
            remaining = self._out_buf
            self._out_buf = ""
        if remaining and self._log:
            try:
                self.call_from_thread(self._log.write, Text.from_ansi(remaining))
            except Exception:
                pass

    def _write_direct(self, text: str) -> None:
        """メインスレッドから直接 RichLog に書く。複数行を適切に分割する。"""
        if self._log is None:
            return
        lines = text.split("\n")
        for i, line in enumerate(lines):
            # 最後の要素が空文字（末尾の \n）の場合はスキップ
            if i == len(lines) - 1 and line == "":
                break
            self._log.write(Text.from_ansi(line))

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

    def action_interrupt(self) -> None:
        """Ctrl+C: エージェント実行中なら中断、それ以外は何もしない。
        元の interactive_loop の KeyboardInterrupt ハンドラと同等の動作。
        PyThreadState_SetAsyncExc で worker スレッドに KeyboardInterrupt を送出する。
        agent.py / orchestrator.py の各 except KeyboardInterrupt がそれを受け取る。
        """
        if not self._agent_busy or self._worker_thread_id is None:
            return
        self._write_direct("\n  [割り込み] Ctrl+C — 中断を要求しました...\n")
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(self._worker_thread_id),
            ctypes.py_object(KeyboardInterrupt),
        )

    def action_quit_app(self) -> None:
        """終了前にセッションを保存する（元の exit/quit と同じ動作）。"""
        from .utils import set_tui_output, set_tui_mode

        sessions_dir  = self._ctx.get("sessions_dir")
        react_log     = self._ctx["interactive_orch"].react_log

        if sessions_dir and react_log.entries:
            try:
                result = react_log.save_session(sessions_dir)
                self._write_direct(f"  [Session] {result}\n")
            except Exception as e:
                self._write_direct(f"  [Session] 保存失敗: {e}\n")

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
            parts = text.lstrip("/").split(maxsplit=1)
            cmd   = parts[0].lower() if parts else ""
            rest  = parts[1].strip() if len(parts) > 1 else ""
            # /search だけ async worker で処理（push_screen_wait が必要なため）
            if cmd == "search":
                self._run_search(rest)
                return
            self._handle_command(text)
            return

        if self._agent_busy:
            self._write_direct("⚠ エージェント実行中です。Ctrl+C で中断できます。\n")
            return

        self._write_direct(f"\n⚡ ❯ {text}\n")
        self._start_agent(text)

    # ── コマンド処理 ──────────────────────────────────────────────────

    def _handle_command(self, text: str) -> None:
        from .commands import cmd_registry

        parts = text.lstrip("/").split()
        cmd   = parts[0].lower() if parts else ""
        rest  = text[len(parts[0]) + 1:].strip() if len(parts) > 1 else ""

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

        if cmd == "undo":
            result = self._ctx["auto_git"].rollback(self._ctx["agent"].cwd)
            self._write_direct(f"  [AutoGit] {result}\n")
            return

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
        """モード切り替え。元の switch_mode() と同様に react_log もクリアする。"""
        arg = arg.strip().lower()
        if arg in ("interactive", "react", "i"):
            self._current_mode = "interactive"
            self._ctx["agent"].set_system_prompt(self._ctx["react_prompt"])
            self._ctx["agent"].clear_history()
            self._ctx["interactive_orch"].react_log.clear()   # ← 元コードと同じ
            self._write_direct("⚡ モード: Interactive (ReAct)  会話履歴をリセットしました。\n")
        elif arg in ("plan", "p"):
            self._current_mode = "plan"
            self._ctx["agent"].set_system_prompt(self._ctx["plan_prompt"])
            self._ctx["agent"].clear_history()
            self._ctx["interactive_orch"].react_log.clear()   # ← 元コードと同じ
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

    # ── /search (async: push_screen_wait が必要) ─────────────────────

    @work(exclusive=False)
    async def _run_search(self, query: str) -> None:
        """/search コマンド。元の CLI と同じ選択インタフェースをモーダルで提供する。"""
        from .commands import _search_sessions

        if not query:
            self._write_direct("  使い方: /search <検索ワード>\n")
            return

        sd   = self._ctx["sessions_dir"]
        hits = _search_sessions(sd, query)
        if not hits:
            self._write_direct(f"  「{query}」に一致するログが見つかりませんでした。\n")
            return

        # ヒット一覧を表示してからモーダルで選択させる
        self._write_direct(f"\n🔍 「{query}」 — {len(hits)} 件ヒット\n")
        for i, h in enumerate(hits, 1):
            self._write_direct(f"  [{i}] {h['file']}  {h['ts']}\n")
            self._write_direct(f"    Q: {h['user'][:100]}\n")
            if h["result"]:
                self._write_direct(f"    A: {h['result'][:150]}\n")

        # 選択ダイアログ（元 CLI の stdin 入力と同等）
        resp = await self.push_screen_wait(SearchSelectionModal(query, hits))
        resp = (resp or "").strip().lower()

        if not resp or resp == "n":
            return

        # 元コードと同じ選択ロジック
        if resp == "all":
            selected = hits
        else:
            selected = []
            for token in resp.split(","):
                token = token.strip()
                if token.isdigit():
                    idx = int(token) - 1
                    if 0 <= idx < len(hits):
                        selected.append(hits[idx])

        if not selected:
            return

        inject_lines = [f"[過去セッションの参考情報（/search {query}）]"]
        for h in selected:
            inject_lines.append(f"\nUser: {h['full_user']}")
            if h["full_result"]:
                inject_lines.append(f"Result: {h['full_result']}")
        inject_text = "\n".join(inject_lines)
        agent = self._ctx["agent"]
        agent.conversation.append({"role": "user",      "content": inject_text})
        agent.conversation.append({"role": "assistant", "content": "了解しました。参考情報を確認しました。"})
        self._write_direct(f"  ✓ {len(selected)} 件をコンテキストに注入しました。\n")

    # ── エージェント実行 ──────────────────────────────────────────────

    def _start_agent(self, user_input: str) -> None:
        self._agent_busy = True
        inp = self.query_one("#user-input", Input)
        inp.disabled    = True
        inp.placeholder = "⏳ 実行中... (Ctrl+C で中断)"
        if self._current_mode == "interactive":
            self._run_react(user_input)
        else:
            self._run_plan(user_input)

    def _on_agent_done(self) -> None:
        self._agent_busy       = False
        self._worker_thread_id = None
        self._flush_output_buf()   # 未完行バッファを書き出す
        inp = self.query_one("#user-input", Input)
        inp.disabled    = False
        inp.placeholder = "❯ メッセージを入力  (/help でコマンド一覧)"
        if self._log:
            self._log.write(Text.from_ansi("─" * 60))
        inp.focus()

    @work(thread=True, exclusive=True)
    def _run_react(self, user_input: str) -> None:
        self._worker_thread_id = threading.current_thread().ident
        try:
            self._ctx["interactive_orch"].run_react(user_input)
        except KeyboardInterrupt:
            # 元の interactive_loop と同じメッセージ
            from .utils import C
            if self._log:
                self.call_from_thread(
                    self._log.write,
                    Text.from_ansi(C.yellow("\n\n  [割り込み] Ctrl+C — ツール実行を中断しました。\n")),
                )
        except Exception as e:
            if self._log:
                self.call_from_thread(
                    self._log.write, Text.from_ansi(f"\nエラー: {e}\n")
                )
        finally:
            self.call_from_thread(self._on_agent_done)

    @work(thread=True, exclusive=True)
    def _run_plan(self, user_input: str) -> None:
        self._worker_thread_id = threading.current_thread().ident

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
            msg      = f"  {icon} Step {step.index}: {step.description}{parallel}\n"
            if self._log:
                self.call_from_thread(self._log.write, Text.from_ansi(msg))

        try:
            self._ctx["orchestrator"].run_with_plan(
                user_input,
                on_plan = on_plan,
                on_step = on_step,
            )
        except KeyboardInterrupt:
            from .utils import C
            if self._log:
                self.call_from_thread(
                    self._log.write,
                    Text.from_ansi(C.yellow("\n\n  [割り込み] Ctrl+C — プランを中断しました。\n")),
                )
        except Exception as e:
            if self._log:
                self.call_from_thread(
                    self._log.write, Text.from_ansi(f"\nプランエラー: {e}\n")
                )
        finally:
            self.call_from_thread(self._on_agent_done)

    def _show_plan_header(self, steps: list) -> None:
        self._write_direct("\n実行計画\n" + "─" * 40 + "\n")
        for s in steps:
            parallel = " [並列]" if s.parallel else ""
            self._write_direct(f"  Step {s.index}: {s.description}{parallel}\n")
        self._write_direct("─" * 40 + "\n\n")
