"""mimic_claude Textual TUI アプリ本体。"""
from __future__ import annotations

import ctypes
import threading
from typing import Optional, Callable

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Input, Label, Markdown, RichLog, Static


# ── メインアプリ ──────────────────────────────────────────────────────

class MimicApp(App):
    """mimic_claude Textual TUI アプリ。"""

    TITLE = "mimic_claude"

    CSS = """
    Screen      { layout: vertical; background: #050f05; }
    #title-art  { height: 11; background: #050f05; padding: 0 0; overflow-x: hidden; }
    #chat-log   { height: 1fr; border: solid #00a02d; background: #050f05;
                  scrollbar-color: #00ff41; padding: 0 1; }
    #ai-stream  { height: auto; min-height: 0; padding: 0 2;
                  background: #050f05; border-left: solid #00a02d;
                  margin: 0 0 0 1; }
    #input-bar  { height: 3; border: solid #00ff41; padding: 0 1; }
    Input       { background: #050f05; color: #ffffff; border: none; }
    Footer      { background: #050f05; color: #00c864; }
    Markdown    { background: #050f05; }
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
        # 書き込み承認: エージェントスレッドが Y/n を待つためのコールバック
        self._approval_callback: Optional[Callable[[str], None]] = None
        # AI レスポンスストリームバッファ（Markdown.update() 用）
        self._ai_buf      = ""
        self._ai_buf_lock = threading.Lock()

    # ── 構成 ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("", id="title-art")     # ASCII アートタイトル
        yield RichLog(id="chat-log", highlight=False, markup=False, wrap=True)
        yield Markdown("", id="ai-stream")   # AI レスポンスストリーム表示領域
        with Vertical(id="input-bar"):
            yield Input(
                placeholder="❯ メッセージを入力  (/help でコマンド一覧)",
                id="user-input",
            )
        yield Footer()

    # ── 初期化 ────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        from .utils import set_tui_output, set_tui_mode, set_tui_stream, get_ascii_art_str
        from .tools import set_write_approval_handler

        self._log = self.query_one("#chat-log", RichLog)
        set_tui_mode(True)
        set_tui_output(self._output_callback)
        set_tui_stream(self._stream_callback)
        set_write_approval_handler(self._make_approval_handler())

        # 100ms ごとに AI バッファを Markdown ウィジェットへ反映する（Web チャットと同方式）
        self.set_interval(0.1, self._tick_ai_stream)

        cfg = self._ctx["active_config"]
        cwd = self._ctx["agent"].cwd

        # ASCII アートタイトルを表示（サブタイトルにモデル情報を埋め込む）
        subtitle = f"{cfg.model}  ·  {cwd}"
        art_text = Text.from_ansi(get_ascii_art_str(subtitle))
        self.query_one("#title-art", Static).update(art_text)

        self._write_direct(f"作業Dir: {cwd}\n")
        self._write_direct("─" * 60 + "\n")
        self.query_one("#user-input", Input).focus()

    # ── 出力コールバック ──────────────────────────────────────────────

    def _safe_write_line(self, line: str) -> None:
        """1行を RichLog に書く。メインスレッド・ワーカースレッド両方から安全に呼べる。
        Textual 8.x では call_from_thread をメインスレッドから呼ぶと RuntimeError が
        発生するため、その場合は直接 write() にフォールバックする。
        """
        if self._log is None:
            return
        rich_text = Text.from_ansi(line)
        try:
            self.call_from_thread(self._log.write, rich_text)
        except RuntimeError:
            # メインスレッド（イベントループ）からの呼び出し → 直接書く
            try:
                self._log.write(rich_text)
            except Exception:
                pass
        except Exception:
            pass

    def _output_callback(self, text: str) -> None:
        """safe_print / PipelineTypewriter から呼ばれる。どのスレッドからでも安全。
        RichLog.write() は 1 呼び出し = 1 行扱いなので \n 単位でバッファしてから書く。
        """
        if self._log is None:
            return
        with self._out_buf_lock:
            self._out_buf += text
            lines = self._out_buf.split("\n")
            self._out_buf = lines[-1]  # 末尾の未完行をバッファに残す
            complete = lines[:-1]
        for line in complete:
            self._safe_write_line(line)

    def _flush_output_buf(self) -> None:
        """未完行バッファを強制フラッシュする（エージェント完了時に呼ぶ）。"""
        with self._out_buf_lock:
            remaining = self._out_buf
            self._out_buf = ""
        if remaining:
            self._safe_write_line(remaining)

    def _update_title(self) -> None:
        """モデル名・CWD 変更時にアートのサブタイトル行を更新する。"""
        from .utils import get_ascii_art_str
        cfg     = self._ctx["active_config"]
        cwd     = self._ctx["agent"].cwd
        subtitle = f"{cfg.model}  ·  {cwd}"
        try:
            art_text = Text.from_ansi(get_ascii_art_str(subtitle))
            self.query_one("#title-art", Static).update(art_text)
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

    # ── 書き込み承認（元の mimic_linux と同じテキストベース） ────────────

    _APPROVAL_TIMEOUT = 30  # 秒

    def _make_approval_handler(self):
        """エージェントスレッドから呼ばれる書き込み承認ハンドラを返す。
        元の interactive_loop の _react_approval_handler と同等の動作。
        ダイアログの代わりにチャットログにプロンプトを表示し、
        Input を一時解放して Y/n を受け取る。30秒で自動承認。
        """
        app = self

        def handler(tool_name: str, args: dict, preview: str) -> bool:
            from .utils import safe_print, C

            path = args.get("path", "?")
            safe_print(C.yellow(f"\n  ┌─ 書き込み確認 ──────────────────────────────────────"))
            safe_print(C.yellow(f"  │  ツール : {tool_name}"))
            safe_print(C.yellow(f"  │  ファイル: {path}"))
            safe_print(C.yellow(f"  │"))
            for line in (preview or "").splitlines()[:20]:
                safe_print(C.gray(f"  │  {line}"))
            safe_print(C.yellow(f"  └──────────────────────────────────────────────────────"))
            safe_print(
                C.bold_green(
                    f"  実行しますか？ [Y/n] ({app._APPROVAL_TIMEOUT}秒で自動承認): "
                ),
                end="",
            )

            # Input を承認モードで一時解放
            done   = threading.Event()
            result = [True]

            def on_response(resp: str) -> None:
                result[0] = resp.strip().lower() in ("y", "")
                done.set()

            app.call_from_thread(app._enter_approval_mode, on_response)
            timed_out = not done.wait(timeout=app._APPROVAL_TIMEOUT)

            if timed_out:
                safe_print(C.gray(f"\n  ⏱ {app._APPROVAL_TIMEOUT}秒経過 → 自動承認"))
                result[0] = True
                # タイムアウト時は承認モードを解除する
                app.call_from_thread(app._exit_approval_mode)

            if result[0]:
                safe_print(C.green("  ✓ 承認しました"))
            else:
                safe_print(C.red("  ✗ 拒否しました（処理を中断します）"))
            return result[0]

        return handler

    def _enter_approval_mode(
        self,
        callback: Callable[[str], None],
        placeholder: str = "",
    ) -> None:
        """メインスレッドで入力待ちモードに入る。Input を解放してユーザー入力を受け取れるようにする。
        承認ハンドラ・/search 選択の両方で共用する。
        """
        self._approval_callback = callback
        inp = self.query_one("#user-input", Input)
        inp.disabled    = False
        inp.placeholder = placeholder or (
            f"Y/n を入力（Enter で承認・n で拒否・{self._APPROVAL_TIMEOUT}秒で自動承認）"
        )
        inp.focus()

    def _exit_approval_mode(self) -> None:
        """タイムアウト時に承認モードを解除してエージェント実行中の状態に戻す。"""
        self._approval_callback = None
        if self._agent_busy:
            inp = self.query_one("#user-input", Input)
            inp.disabled    = True
            inp.placeholder = "⏳ 実行中... (Ctrl+C で中断)"

    # ── AI レスポンスストリーム（Markdown.update() 方式） ─────────────

    def _stream_callback(self, text: str) -> None:
        """PipelineTypewriter から生 Markdown テキストが来る（どのスレッドからでも安全）。
        バッファに追記するだけ。実際の Markdown.update() は _tick_ai_stream() が行う。
        """
        with self._ai_buf_lock:
            self._ai_buf += text

    def _tick_ai_stream(self) -> None:
        """100ms ごとにバッファ全体で Markdown ウィジェットを更新する（メインスレッド）。
        Web チャットアプリと同じ仕組み: 毎フレーム全文を再パースして差分更新する。
        """
        with self._ai_buf_lock:
            text = self._ai_buf
        if not text:
            return
        try:
            self.query_one("#ai-stream", Markdown).update(text)
        except Exception:
            pass

    def _bake_ai_response(self) -> None:
        """AI レスポンス完了時に Markdown ウィジェットの内容を RichLog に焼き込んで履歴に残す。
        焼き込みには rich.markdown.Markdown を使い、RichLog が正式にレンダリングする。
        """
        with self._ai_buf_lock:
            text = self._ai_buf
            self._ai_buf = ""
        if not text or self._log is None:
            return
        # 最終状態で Markdown ウィジェットを更新してから RichLog に移す
        try:
            self.query_one("#ai-stream", Markdown).update("")
        except Exception:
            pass
        try:
            self._log.write(RichMarkdown(text))
        except Exception:
            self._log.write(Text.from_ansi(text))

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

        from .utils import set_tui_stream
        set_tui_mode(False)
        set_tui_output(None)
        set_tui_stream(None)
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

        # ── 承認 / 選択 入力待ちモード ───────────────────────────────────
        if self._approval_callback is not None:
            callback = self._approval_callback
            self._approval_callback = None
            callback(text)  # on_response(resp) を呼ぶ
            # エージェント実行中（承認ハンドラ）→ 再度無効化
            # エージェント未実行（/search 選択）→ 通常状態に戻す
            if self._agent_busy:
                event.input.disabled    = True
                event.input.placeholder = "⏳ 実行中... (Ctrl+C で中断)"
            else:
                event.input.disabled    = False
                event.input.placeholder = "❯ メッセージを入力  (/help でコマンド一覧)"
            return

        if not text:
            return

        if text.lower() in ("exit", "quit", "q"):
            self.action_quit_app()
            return

        if text.startswith("/"):
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

        if cmd == "search":
            self._cmd_search(rest)
            return

        match = cmd_registry.route(text)
        if match:
            _, handler, args = match
            handler(self._ctx["agent"], args)
            # /cd 実行後は CWD が変わるのでタイトルを更新
            if cmd == "cd":
                self._update_title()
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
            self._update_title()
        else:
            current = self._ctx["agent"]._config.model
            self._write_direct(
                f"  現在のモデル: {current}\n"
                "  変更: /model <モデル名>\n"
            )

    # ── /search ──────────────────────────────────────────────────────

    def _cmd_search(self, query: str) -> None:
        """/search コマンド。元の CLI と同じテキスト入力方式で注入選択を行う。"""
        from .commands import _search_sessions

        if not query:
            self._write_direct("  使い方: /search <検索ワード>\n")
            return

        sd   = self._ctx["sessions_dir"]
        hits = _search_sessions(sd, query)
        if not hits:
            self._write_direct(f"  「{query}」に一致するログが見つかりませんでした。\n")
            return

        # ヒット一覧を表示
        self._write_direct(f"\n🔍 「{query}」 — {len(hits)} 件ヒット\n")
        for i, h in enumerate(hits, 1):
            self._write_direct(f"  [{i}] {h['file']}  {h['ts']}\n")
            self._write_direct(f"    Q: {h['user'][:100]}\n")
            if h["result"]:
                self._write_direct(f"    A: {h['result'][:150]}\n")
        self._write_direct(
            "  コンテキストに注入しますか？ [番号をカンマ区切り / all / n]: "
        )

        # Input を一時解放して選択を受け取る（元コードの stdin.readline と同等）
        def on_response(resp: str) -> None:
            resp = resp.strip().lower()
            if not resp or resp == "n":
                return

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

        self._enter_approval_mode(
            on_response,
            placeholder="番号カンマ区切り / all で全件 / n またはEnterでキャンセル",
        )

    # ── エージェント実行 ──────────────────────────────────────────────

    def _start_agent(self, user_input: str) -> None:
        self._agent_busy = True
        # AI バッファをクリアして新しいレスポンス受け取り準備
        with self._ai_buf_lock:
            self._ai_buf = ""
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
        self._flush_output_buf()       # 未完行バッファを書き出す
        self._bake_ai_response()       # AI レスポンスを RichLog に焼き込む
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
