"""
tui.py — Mimic 4 Textual UI
入力と出力を完全分離したクリーンなターミナルUI

レイアウト:
  ┌─────────────────────────────────────┐
  │  [RichLog — AI出力・ツール結果]      │  ← スクロール可能、上部大半
  │                                     │
  ├─────────────────────────────────────┤
  │  ❯  ユーザー入力欄                  │  ← 常に下部に固定
  └─────────────────────────────────────┘
"""
from __future__ import annotations

import sys
import threading
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.containers import Vertical
from textual import work


class MimicApp(App):
    """Mimic 4 Textual メインアプリ"""

    TITLE = "MIMIC 4"
    SUB_TITLE = "THE HYBRID AI AGENT"

    CSS = """
    Screen {
        background: #080808;
        layers: base;
    }

    RichLog {
        height: 1fr;
        background: #0a0a0a;
        border: none;
        padding: 0 1;
        scrollbar-color: #00a02d #080808;
    }

    #input-bar {
        height: 3;
        background: #0d0d0d;
        border-top: solid #00a02d;
        padding: 0 1;
        align: left middle;
    }

    Input {
        width: 1fr;
        height: 1;
        background: #0d0d0d;
        color: #00ff41;
        border: none;
        padding: 0 0;
    }

    Input:focus {
        border: none;
    }

    Header {
        background: #001800;
        color: #00ff41;
        text-style: bold;
    }

    Footer {
        background: #001800;
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
        self._orch         = interactive_orch
        self._config_name  = config_name
        self._model_name   = model_name
        self._cwd          = cwd
        self._busy         = False  # エージェント実行中フラグ

    # ────────────────────────────────────────────────────────────────
    # レイアウト
    # ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield Vertical(
            Input(placeholder="  ❯  メッセージを入力... (Ctrl+C で終了)", id="prompt"),
            id="input-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        log.write(Text.from_ansi(
            f"\n\033[1m\033[38;2;0;255;65mMIMIC 4\033[0m"
            f"  \033[38;2;0;200;100m[{self._config_name}]\033[0m"
            f"  \033[38;2;0;240;200m{self._model_name}\033[0m\n"
        ))
        log.write(Text.from_ansi(
            f"\033[38;2;0;200;100m  作業フォルダ: {self._cwd}\033[0m\n"
            f"\033[38;2;0;200;100m  Ctrl+L: クリア  ·  Ctrl+C: 終了\033[0m\n"
        ))
        self.query_one(Input).focus()

    # ────────────────────────────────────────────────────────────────
    # 出力ヘルパー
    # ────────────────────────────────────────────────────────────────

    def _write(self, text: str) -> None:
        """メインスレッドから RichLog に ANSI テキストを書き込む"""
        if not text:
            return
        try:
            self.query_one(RichLog).write(Text.from_ansi(text), end="")
        except Exception:
            pass

    def _write_from_thread(self, text: str) -> None:
        """ワーカースレッドから RichLog にスレッドセーフに書き込む"""
        try:
            self.call_from_thread(self._write, text)
        except Exception:
            pass

    # ────────────────────────────────────────────────────────────────
    # 入力処理
    # ────────────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return

        # 終了コマンド
        if text.lower() in ("exit", "quit", "q"):
            self.exit()
            return

        # エージェント実行中は受け付けない
        if self._busy:
            self._write(
                "\033[38;2;255;230;0m  ⚠ 実行中です。完了をお待ちください...\033[0m\n"
            )
            return

        # ユーザー入力をログに表示
        self._write(
            f"\n\033[1m\033[38;2;0;255;65m❯\033[0m"
            f" \033[38;2;255;255;255m{text}\033[0m\n"
        )
        self._run_agent(text)

    # ────────────────────────────────────────────────────────────────
    # アクション
    # ────────────────────────────────────────────────────────────────

    def action_clear_log(self) -> None:
        self.query_one(RichLog).clear()

    # ────────────────────────────────────────────────────────────────
    # エージェント実行 (ワーカースレッド)
    # ────────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True)
    def _run_agent(self, user_input: str) -> None:
        """
        ワーカースレッドでエージェントを実行する。

        sys.stdout を _TuiLineBuffer に差し替えることで
        safe_print / PipelineTypewriter の全出力を RichLog へ転送する。

        _TuiLineBuffer は CR (\\r) をシミュレートし、スピナーのフレームを
        バッファ破棄で無視しつつ、完全な行のみ TUI へ送る。
        """
        original_stdout = sys.stdout
        worker_tid       = threading.current_thread().ident
        app_ref          = self          # クロージャ用

        # ── CR 対応ラインバッファ ──────────────────────────────────
        class _TuiLineBuffer:
            encoding  = "utf-8"
            errors    = "replace"
            softspace = 0

            def __init__(self_buf) -> None:
                self_buf._buf = ""

            def write(self_buf, s: str) -> int:
                if not s:
                    return 0
                # ワーカー以外のスレッドはオリジナルへ流す
                if threading.current_thread().ident != worker_tid:
                    original_stdout.write(s)
                    return len(s)

                self_buf._buf += s

                # CR (\r) 処理: スピナーの上書きを模倣してバッファをリセット
                while "\r" in self_buf._buf:
                    cr_pos = self_buf._buf.find("\r")
                    nl_pos = self_buf._buf.find("\n")
                    if nl_pos != -1 and nl_pos < cr_pos:
                        # CR より前に改行あり → まずその行を転送
                        line, self_buf._buf = (
                            self_buf._buf[:nl_pos + 1],
                            self_buf._buf[nl_pos + 1:],
                        )
                        app_ref._write_from_thread(line)
                    else:
                        # CR 以前の内容を捨てる（スピナーフレームを無視）
                        self_buf._buf = self_buf._buf[cr_pos + 1:]

                # 改行で区切って転送
                while "\n" in self_buf._buf:
                    nl_pos = self_buf._buf.find("\n")
                    line, self_buf._buf = (
                        self_buf._buf[:nl_pos + 1],
                        self_buf._buf[nl_pos + 1:],
                    )
                    app_ref._write_from_thread(line)

                return len(s)

            def flush(self_buf) -> None:
                if self_buf._buf:
                    app_ref._write_from_thread(self_buf._buf)
                    self_buf._buf = ""
                try:
                    original_stdout.flush()
                except Exception:
                    pass

            def fileno(self_buf) -> int:
                try:
                    return original_stdout.fileno()
                except Exception:
                    return -1

            def isatty(self_buf) -> bool:
                return False

        # ── 実行 ─────────────────────────────────────────────────────
        self.call_from_thread(setattr, self, "_busy", True)
        sys.stdout = _TuiLineBuffer()
        self._orch._auto_mode = True   # PipelineTypewriter アニメーション無効

        try:
            self._orch.run_react(user_input)
        except KeyboardInterrupt:
            self._write_from_thread(
                "\n\033[38;2;255;230;0m  [割り込み] Ctrl+C\033[0m\n"
            )
        except Exception as e:
            self._write_from_thread(
                f"\n\033[38;2;255;0;60m  ✗ {e}\033[0m\n"
            )
        finally:
            sys.stdout.flush()
            sys.stdout = original_stdout
            self._orch._auto_mode = False
            self._write_from_thread("\n")
            self.call_from_thread(setattr, self, "_busy", False)
            self.call_from_thread(self.query_one(Input).focus)
