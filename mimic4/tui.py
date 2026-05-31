"""
tui.py — Mimic 4 Textual UI
入力と出力を完全分離したクリーンなターミナルUI
"""
from __future__ import annotations

import re
import sys
import threading
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Input, RichLog
from textual.containers import Vertical

# ANSI SGR以外の制御シーケンスを除去するパターン（フォールバック用）
_ANSI_STRIP = re.compile(r'\033\[[^m]*m|\033\[\?[0-9;]*[hl]')


class MimicApp(App):
    """Mimic 4 Textual メインアプリ"""

    TITLE = "MIMIC 4"
    SUB_TITLE = "THE HYBRID AI AGENT"

    CSS = """
    App {
        background: transparent;
    }

    Screen {
        background: transparent;
    }

    RichLog {
        height: 1fr;
        background: transparent;
        border: none;
        padding: 0 1;
        scrollbar-color: #00a02d transparent;
    }

    #input-bar {
        height: 3;
        background: transparent;
        border-top: solid #00a02d;
        padding: 0 1;
        align: left middle;
    }

    Input {
        width: 1fr;
        height: 1;
        background: transparent;
        color: #00ff41;
        border: none;
    }

    Input:focus {
        border: none;
    }

    Header {
        background: transparent;
        color: #00ff41;
        text-style: bold;
    }

    Footer {
        background: transparent;
        color: #00a02d;
    }
    """

    BINDINGS = [
        Binding("ctrl+l", "clear_log", "クリア", show=True),
        Binding("ctrl+c", "quit", "終了", show=True, priority=True),
        Binding("escape", "quit", "終了", show=False),
    ]

    def __init__(
        self,
        interactive_orch,
        config_name: str,
        model_name: str,
        cwd: str,
    ) -> None:
        super().__init__()
        self._orch        = interactive_orch
        self._config_name = config_name
        self._model_name  = model_name
        self._cwd         = cwd
        self._busy        = False
        self._worker: Optional[threading.Thread] = None

    # ── レイアウト ───────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield Vertical(
            Input(placeholder="  ❯  メッセージを入力... (Ctrl+C で終了)", id="prompt"),
            id="input-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._log("\n\033[1m\033[38;2;0;255;65mMIMIC 4\033[0m"
                  f"  \033[38;2;0;200;100m[{self._config_name}]\033[0m"
                  f"  \033[38;2;0;240;200m{self._model_name}\033[0m\n")
        self._log(f"\033[38;2;0;200;100m  作業フォルダ: {self._cwd}\033[0m\n"
                  f"\033[38;2;0;200;100m  Ctrl+L: クリア  ·  Ctrl+C: 終了\033[0m\n")
        self.query_one("#prompt", Input).focus()

    # ── 出力 ─────────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        """メインスレッドから RichLog に書き込む (ANSI対応)"""
        if not text:
            return
        log = self.query_one("#log", RichLog)
        try:
            log.write(Text.from_ansi(text.rstrip("\n")))
        except Exception:
            plain = _ANSI_STRIP.sub("", text)
            log.write(plain.rstrip("\n"))

    def _log_from_thread(self, text: str) -> None:
        """ワーカースレッドから RichLog に書き込む (スレッドセーフ)"""
        try:
            self.call_from_thread(self._log, text)
        except Exception:
            pass

    # ── 入力 ─────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one("#prompt", Input).clear()

        if not text:
            return

        if text.lower() in ("exit", "quit", "q"):
            self.exit()
            return

        if self._busy:
            self._log("\033[38;2;255;230;0m  ⚠ 実行中です。完了をお待ちください...\033[0m\n")
            return

        # ユーザー入力を表示
        self._log(f"\n\033[1m\033[38;2;0;255;65m❯\033[0m"
                  f" \033[38;2;255;255;255m{text}\033[0m\n")

        # ワーカースレッドを起動
        self._busy = True
        self._worker = threading.Thread(
            target=self._agent_thread,
            args=(text,),
            daemon=True,
        )
        self._worker.start()

    # ── アクション ───────────────────────────────────────────────────

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    # ── エージェント実行 ─────────────────────────────────────────────

    def _agent_thread(self, user_input: str) -> None:
        """
        バックグラウンドスレッドでエージェントを実行する。

        sys.stdout を _TuiLineBuffer に差し替えて
        safe_print / PipelineTypewriter の全出力を RichLog へ転送する。
        スピナーの \\r 上書きはバッファを破棄して無視する。
        """
        original_stdout = sys.stdout
        worker_tid      = threading.current_thread().ident
        app_ref         = self

        # ── CR対応ラインバッファ ──────────────────────────────────
        class _TuiLineBuffer:
            encoding  = "utf-8"
            errors    = "replace"
            softspace = 0

            def __init__(self_b) -> None:
                self_b._buf = ""

            def write(self_b, s: str) -> int:
                if not s:
                    return 0
                # ワーカー以外はオリジナルへ
                if threading.current_thread().ident != worker_tid:
                    try:
                        original_stdout.write(s)
                    except Exception:
                        pass
                    return len(s)

                self_b._buf += s

                # CR でバッファをリセット（スピナーフレームを破棄）
                while "\r" in self_b._buf:
                    cr = self_b._buf.find("\r")
                    nl = self_b._buf.find("\n")
                    if nl != -1 and nl < cr:
                        # CR より前に改行あり → その行を送出
                        app_ref._log_from_thread(self_b._buf[:nl + 1])
                        self_b._buf = self_b._buf[nl + 1:]
                    else:
                        # CR 以前を破棄
                        self_b._buf = self_b._buf[cr + 1:]

                # 改行で区切って送出
                while "\n" in self_b._buf:
                    nl = self_b._buf.find("\n")
                    app_ref._log_from_thread(self_b._buf[:nl + 1])
                    self_b._buf = self_b._buf[nl + 1:]

                return len(s)

            def flush(self_b) -> None:
                # 部分行は送らない。\n が来たときだけ _log_from_thread に渡す。
                # finally ブロックで残余バッファを明示的にフラッシュする。
                try:
                    original_stdout.flush()
                except Exception:
                    pass

            def fileno(self_b) -> int:
                try:
                    return original_stdout.fileno()
                except Exception:
                    return -1

            def isatty(self_b) -> bool:
                return False

        # PipelineTypewriter のアニメーション無効 (auto_mode=True → 直接 stdout 書き込み)
        self._orch._auto_mode = True
        tui_buf = _TuiLineBuffer()
        sys.stdout = tui_buf

        try:
            self._orch.run_react(user_input)
        except KeyboardInterrupt:
            self._log_from_thread(
                "\n\033[38;2;255;230;0m  [割り込み] Ctrl+C\033[0m\n"
            )
        except Exception as e:
            import traceback
            self._log_from_thread(
                f"\n\033[38;2;255;0;60m  ✗ {e}\033[0m\n"
                f"\033[38;2;0;200;100m{traceback.format_exc()}\033[0m\n"
            )
        finally:
            # \n なしで終わった末尾行を明示的に書き出す
            if tui_buf._buf:
                app_ref._log_from_thread(tui_buf._buf + "\n")
                tui_buf._buf = ""
            sys.stdout = original_stdout
            self._orch._auto_mode = False
            self._log_from_thread("\n")
            self._busy = False
            # 入力欄にフォーカスを戻す
            try:
                self.call_from_thread(self.query_one("#prompt", Input).focus)
            except Exception:
                pass
