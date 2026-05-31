"""
tui.py — Mimic 4 Textual UI
ModelSelectScreen → ChatScreen の2画面構成
"""
from __future__ import annotations

import re
import sys
import threading
from typing import Optional, Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Input, Label, RichLog
from textual.containers import Vertical

_ANSI_STRIP = re.compile(r'\033\[[^m]*m|\033\[\?[0-9;]*[hl]')

_CSS = """
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
#sel-progress {
    height: 1;
    background: transparent;
    padding: 0 1;
}
.input-bar {
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


def _write_log(log: RichLog, text: str) -> None:
    """テキストを行単位で RichLog に書き込む（ANSI対応）"""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for line in lines:
        try:
            log.write(Text.from_ansi(line) if line else "")
        except Exception:
            log.write(_ANSI_STRIP.sub("", line))


# ─────────────────────────────────────────────────────────────────────────────
# モデル選択画面
# ─────────────────────────────────────────────────────────────────────────────

class ModelSelectScreen(Screen):
    """モデル一覧取得 → 疎通確認 → 番号入力で選択"""

    BINDINGS = [
        Binding("ctrl+c", "cancel",    "終了",       show=True,  priority=True),
        Binding("ctrl+s", "stop_test", "テスト中断", show=True),
    ]

    def __init__(self, or_config, gemini_config, mistral_config) -> None:
        super().__init__()
        self._or_config      = or_config
        self._gemini_config  = gemini_config
        self._mistral_config = mistral_config
        self._working: list  = []
        self._ready          = False  # True = 選択モード / False = テスト中
        self._stop_test      = threading.Event()

    @property
    def _fallback(self):
        return self._or_config or self._gemini_config or self._mistral_config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="sel-log", highlight=False, markup=False, wrap=True)
        yield Label("", id="sel-progress")
        yield Vertical(
            Input(
                placeholder="  ❯  Enter で現時点の結果を表示 / Ctrl+S で中断",
                id="sel-input",
            ),
            id="sel-bar",
            classes="input-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._log("\n\033[1m\033[38;2;0;255;65mMULTI-PROVIDER MODEL SELECTOR\033[0m"
                  "  \033[38;2;0;200;100m·  LIVE API HEALTH CHECK\033[0m\n")
        self._log("\033[38;2;0;200;100m  モデル一覧を取得中...\033[0m\n")
        self.query_one("#sel-input", Input).focus()
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    # ── ログ出力 ────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        _write_log(self.query_one("#sel-log", RichLog), text)

    def _log_t(self, text: str) -> None:
        try:
            self.app.call_from_thread(self._log, text)
        except Exception:
            pass

    def _set_progress(self, n: int, total: int) -> None:
        """プログレスバーを Label に反映（メインスレッドから呼ぶ）"""
        filled  = int(34 * n / total)
        pct     = int(100 * n / total)
        bar_str = (
            f"  \033[38;2;0;160;45m[\033[0m"
            f"\033[38;2;0;255;65m{'█' * filled}\033[0m"
            f"\033[38;2;0;160;45m{'░' * (34 - filled)}\033[0m"
            f"\033[38;2;0;160;45m]\033[0m"
            f"  \033[38;2;255;255;255m{n}/{total}\033[0m"
            f"  \033[38;2;0;200;100m({pct}%)\033[0m"
        )
        try:
            self.query_one("#sel-progress", Label).update(Text.from_ansi(bar_str))
        except Exception:
            pass

    def _set_progress_t(self, n: int, total: int) -> None:
        try:
            self.app.call_from_thread(self._set_progress, n, total)
        except Exception:
            pass

    # ── バックグラウンド: 取得 & 疎通確認 ───────────────────────────

    def _fetch_thread(self) -> None:
        try:
            self._fetch_inner()
        except Exception as e:
            import traceback
            self._log_t(
                f"\033[38;2;255;0;60m  ✗ 取得エラー: {e}\033[0m\n"
                f"\033[38;2;0;200;100m{traceback.format_exc()}\033[0m\n"
            )
            self.app.call_from_thread(self.dismiss, self._fallback)

    def _fetch_inner(self) -> None:
        import io, builtins
        from concurrent.futures import ThreadPoolExecutor
        from .config import (
            fetch_free_models, fetch_gemini_models, fetch_mistral_models,
            _test_model,
            OPENROUTER_API_BASE, GEMINI_API_BASE, MISTRAL_API_BASE,
        )

        # fetch 関数内の print() を TUI ログへリダイレクト
        _orig_print = builtins.print
        def _tui_print(*args, **kwargs):
            text = " ".join(str(a) for a in args)
            if text.strip():
                self._log_t(f"\033[38;2;255;230;0m  {text}\033[0m\n")
        builtins.print = _tui_print

        # フェーズ1: モデル一覧取得
        or_models, gemini_models, mistral_models = [], [], []
        ex1   = ThreadPoolExecutor(max_workers=3)
        or_fut = ex1.submit(fetch_free_models,    self._or_config.api_keys[0])      if self._or_config      else None
        gm_fut = ex1.submit(fetch_gemini_models,  self._gemini_config.api_keys[0])  if self._gemini_config  else None
        mi_fut = ex1.submit(fetch_mistral_models, self._mistral_config.api_keys[0]) if self._mistral_config else None
        try:
            if or_fut:
                try:    or_models     = or_fut.result()
                except Exception as e: self._log_t(f"\033[38;2;255;230;0m  ⚠ OpenRouter 取得失敗: {e}\033[0m\n")
            if gm_fut:
                try:    gemini_models  = gm_fut.result()
                except Exception as e: self._log_t(f"\033[38;2;255;230;0m  ⚠ Gemini 取得失敗: {e}\033[0m\n")
            if mi_fut:
                try:    mistral_models = mi_fut.result()
                except Exception as e: self._log_t(f"\033[38;2;255;230;0m  ⚠ Mistral 取得失敗: {e}\033[0m\n")
        finally:
            builtins.print = _orig_print
            try:    ex1.shutdown(wait=False, cancel_futures=True)
            except TypeError: ex1.shutdown(wait=False)

        parts = []
        if self._or_config:      parts.append(f"\033[38;2;0;255;65mOpenRouter\033[0m: {len(or_models)} 件")
        if self._gemini_config:  parts.append(f"\033[38;2;0;255;65mGemini\033[0m: {len(gemini_models)} 件")
        if self._mistral_config: parts.append(f"\033[38;2;0;240;200mMistral\033[0m: {len(mistral_models)} 件")
        self._log_t(f"\033[38;2;0;255;65m  ✓\033[0m  {'  /  '.join(parts)}\n")

        all_entries = (
            [("or",      m) for m in or_models] +
            [("gemini",  m) for m in gemini_models] +
            [("mistral", m) for m in mistral_models]
        )
        total = len(all_entries)

        if total == 0:
            self._log_t("\033[38;2;255;230;0m  ⚠  モデル一覧の取得に失敗しました。現在の設定を使用します。\033[0m\n")
            self.app.call_from_thread(self.dismiss, self._fallback)
            return

        # フェーズ1完了後に中断指示があれば即 dismiss
        if self._stop_test.is_set():
            self._log_t("\033[38;2;255;230;0m  現在の設定を使用します。\033[0m\n")
            self.app.call_from_thread(self.dismiss, self._fallback)
            return

        # フェーズ2: 疎通確認
        self._log_t(f"\033[38;2;0;200;100m  疎通確認中... {total} 件  ← Enter で現時点の結果を表示\033[0m\n")

        results: dict[str, tuple[bool, float]] = {}
        lock   = threading.Lock()
        tested = [0]

        def _test(entry: tuple) -> None:
            if self._stop_test.is_set():
                return
            provider, mdl = entry
            mid = mdl["id"]
            if   provider == "or"      and self._or_config:
                ok, el = _test_model(self._or_config.api_keys[0],      mid, OPENROUTER_API_BASE)
            elif provider == "gemini"  and self._gemini_config:
                ok, el = _test_model(self._gemini_config.api_keys[0],  mid, GEMINI_API_BASE)
            elif provider == "mistral" and self._mistral_config:
                ok, el = _test_model(self._mistral_config.api_keys[0], mid, MISTRAL_API_BASE)
            else:
                ok, el = False, 0.0
            if self._stop_test.is_set():
                return
            with lock:
                results[f"{provider}:{mid}"] = (ok, el)
                tested[0] += 1
                self._set_progress_t(tested[0], total)

        ex2  = ThreadPoolExecutor(max_workers=10)
        futs = {ex2.submit(_test, e) for e in all_entries}
        try:
            for f in futs:
                try:    f.result()
                except Exception: pass
                if self._stop_test.is_set():
                    break
        finally:
            try:    ex2.shutdown(wait=False, cancel_futures=True)
            except TypeError: ex2.shutdown(wait=False)

        # フェーズ3: 結果集計
        working = sorted(
            [
                (prov, mdl, results[f"{prov}:{mdl['id']}"][1])
                for prov, mdl in all_entries
                if results.get(f"{prov}:{mdl['id']}", (False,))[0]
            ],
            key=lambda x: x[2],
        )

        if not working:
            self._log_t("\033[38;2;255;230;0m  ⚠  疎通できたモデルがありませんでした。現在の設定を使用します。\033[0m\n")
            self.app.call_from_thread(self.dismiss, self._fallback)
            return

        self.app.call_from_thread(self._show_table, working)

    # ── テーブル表示 & 入力受付 ─────────────────────────────────────

    def _show_table(self, working: list) -> None:
        self._working = working
        # プログレスバーを消去
        try:
            self.query_one("#sel-progress", Label).update("")
        except Exception:
            pass
        self._log(f"\n  \033[38;2;255;255;255m{len(working)} 件が稼働中\033[0m\n")

        prov_badge = {"or": ("OR", "\033[38;2;0;255;65m"),
                      "gemini":  ("GM", "\033[38;2;0;255;65m"),
                      "mistral": ("MI", "\033[38;2;0;240;200m")}

        for i, (provider, mdl, elapsed) in enumerate(working, 1):
            mid   = mdl.get("id", "")
            ctx   = mdl.get("context_length", 0)
            ctx_s = (f"{ctx // 1_000_000}M" if ctx >= 1_000_000
                     else f"{ctx // 1_000}K" if ctx >= 1_000
                     else str(ctx) if ctx else "─")
            badge, col = prov_badge.get(provider, ("??", "\033[38;2;0;200;100m"))
            is_top = i == 1
            star   = "★ " if is_top else "  "
            lat_c  = ("\033[1m\033[38;2;0;255;65m" if is_top
                      else "\033[38;2;0;240;200m" if elapsed < 3.0
                      else "\033[38;2;255;230;0m"  if elapsed < 8.0
                      else "\033[38;2;0;200;100m")
            self._log(
                f"  {col}{star}{str(i).rjust(3)}\033[0m"
                f"  [{col}{badge}\033[0m]"
                f"  \033[38;2;255;255;255m{mid[:50]:<50}\033[0m"
                f"  {lat_c}{elapsed:.1f}s\033[0m"
                f"  \033[38;2;0;200;220m{ctx_s}\033[0m"
            )

        # 凡例
        active = sum([bool(self._or_config), bool(self._gemini_config), bool(self._mistral_config)])
        if active > 1:
            leg = []
            if self._or_config:      leg.append("\033[38;2;0;255;65mOR\033[0m = OpenRouter")
            if self._gemini_config:  leg.append("\033[38;2;0;255;65mGM\033[0m = Google Gemini")
            if self._mistral_config: leg.append("\033[38;2;0;240;200mMI\033[0m = Mistral AI")
            self._log(f"\n  凡例: {'  /  '.join(leg)}\n")

        self._log("\n  \033[38;2;0;160;45m[ 0 ]  キャンセル (現在の設定を使用)\033[0m\n")
        inp = self.query_one("#sel-input", Input)
        inp.placeholder = "  ❯  番号を入力... (0でキャンセル)"
        inp.focus()
        self._ready = True

    # ── 入力処理 ────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inp = self.query_one("#sel-input", Input)
        inp.clear()

        # ── テスト中: Enter でテストを止めて結果表示 ────────────────
        if not self._ready:
            self._stop_test.set()
            self._log("\033[38;2;255;230;0m  ← テストを中断しています...\033[0m\n")
            return

        # ── 選択モード ──────────────────────────────────────────────
        raw = event.value.strip()

        if raw in ("", "0"):
            self.dismiss(self._fallback)
            return
        try:
            n = int(raw)
        except ValueError:
            self._log("\033[38;2;255;230;0m  ⚠  数字を入力してください\033[0m\n")
            return
        if not (1 <= n <= len(self._working)):
            self._log(f"\033[38;2;255;230;0m  ⚠  1〜{len(self._working)} の番号を入力してください\033[0m\n")
            return

        provider, mdl, _ = self._working[n - 1]
        sel_id  = mdl["id"]
        sel_ctx = mdl.get("context_length", 0)

        if provider == "or" and self._or_config:
            self._or_config.model = sel_id
            self._or_config.context_length = sel_ctx
            self._log(f"\033[38;2;0;255;65m  ✓  選択: [OR] {sel_id}\033[0m\n")
            self.dismiss(self._or_config)
        elif provider == "gemini" and self._gemini_config:
            self._gemini_config.model = sel_id
            self._gemini_config.context_length = sel_ctx
            self._log(f"\033[38;2;0;255;65m  ✓  選択: [GM] {sel_id}\033[0m\n")
            self.dismiss(self._gemini_config)
        elif provider == "mistral" and self._mistral_config:
            self._mistral_config.model = sel_id
            self._mistral_config.context_length = sel_ctx
            self._log(f"\033[38;2;0;240;200m  ✓  選択: [MI] {sel_id}\033[0m\n")
            self.dismiss(self._mistral_config)

    def action_stop_test(self) -> None:
        self._stop_test.set()
        self._log_t("\033[38;2;255;230;0m  テストを中断しました\033[0m\n")

    def action_cancel(self) -> None:
        self._stop_test.set()
        self.app.exit()


# ─────────────────────────────────────────────────────────────────────────────
# チャット画面
# ─────────────────────────────────────────────────────────────────────────────

class ChatScreen(Screen):
    """メインチャット画面"""

    BINDINGS = [
        Binding("ctrl+l", "clear_log", "クリア", show=True),
        Binding("ctrl+c", "quit_app",  "終了",   show=True, priority=True),
        Binding("escape", "quit_app",  "終了",   show=False),
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield Vertical(
            Input(placeholder="  ❯  メッセージを入力... (Ctrl+C で終了)", id="prompt"),
            id="input-bar",
            classes="input-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._log("\n\033[1m\033[38;2;0;255;65mMIMIC 4\033[0m"
                  f"  \033[38;2;0;200;100m[{self._config_name}]\033[0m"
                  f"  \033[38;2;0;240;200m{self._model_name}\033[0m\n")
        self._log(f"\033[38;2;0;200;100m  作業フォルダ: {self._cwd}\033[0m\n"
                  f"\033[38;2;0;200;100m  Ctrl+L: クリア  ·  Ctrl+C: 終了\033[0m\n")
        self.query_one("#prompt", Input).focus()

    # ── ログ出力 ────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        if not text:
            return
        _write_log(self.query_one("#log", RichLog), text)

    def _log_from_thread(self, text: str) -> None:
        try:
            self.call_from_thread(self._log, text)
        except Exception:
            pass

    # ── 入力処理 ────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one("#prompt", Input).clear()

        if not text:
            return
        if text.lower() in ("exit", "quit", "q"):
            self.app.exit()
            return
        if self._busy:
            self._log("\033[38;2;255;230;0m  ⚠ 実行中です。完了をお待ちください...\033[0m\n")
            return

        self._log(f"\n\033[1m\033[38;2;0;255;65m❯\033[0m"
                  f" \033[38;2;255;255;255m{text}\033[0m\n")

        self._busy  = True
        self._worker = threading.Thread(
            target=self._agent_thread,
            args=(text,),
            daemon=True,
        )
        self._worker.start()

    # ── アクション ─────────────────────────────────────────────────

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def action_quit_app(self) -> None:
        self.app.exit()

    # ── エージェント実行 ───────────────────────────────────────────

    def _agent_thread(self, user_input: str) -> None:
        """
        バックグラウンドスレッドでエージェントを実行する。
        sys.stdout を差し替えて \n 単位で RichLog へ転送する。
        flush() は部分行を送らない（RichLog.write が常に改行を付加するため）。
        """
        original_stdout = sys.stdout
        worker_tid      = threading.current_thread().ident
        app_ref         = self

        class _TuiLineBuffer:
            encoding  = "utf-8"
            errors    = "replace"
            softspace = 0

            def __init__(self_b) -> None:
                self_b._buf = ""

            def write(self_b, s: str) -> int:
                if not s:
                    return 0
                if threading.current_thread().ident != worker_tid:
                    try:
                        original_stdout.write(s)
                    except Exception:
                        pass
                    return len(s)

                self_b._buf += s

                # CR: スピナーフレームを破棄
                while "\r" in self_b._buf:
                    cr = self_b._buf.find("\r")
                    nl = self_b._buf.find("\n")
                    if nl != -1 and nl < cr:
                        app_ref._log_from_thread(self_b._buf[:nl + 1])
                        self_b._buf = self_b._buf[nl + 1:]
                    else:
                        self_b._buf = self_b._buf[cr + 1:]

                # 完全な行を送出
                while "\n" in self_b._buf:
                    nl = self_b._buf.find("\n")
                    app_ref._log_from_thread(self_b._buf[:nl + 1])
                    self_b._buf = self_b._buf[nl + 1:]

                return len(s)

            def flush(self_b) -> None:
                # 部分行は送らない（RichLog.write は常に改行を付加するため）
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
            if tui_buf._buf:
                app_ref._log_from_thread(tui_buf._buf + "\n")
                tui_buf._buf = ""
            sys.stdout = original_stdout
            self._orch._auto_mode = False
            self._log_from_thread("\n")
            self._busy = False
            try:
                self.call_from_thread(self.query_one("#prompt", Input).focus)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# メインアプリ
# ─────────────────────────────────────────────────────────────────────────────

class MimicApp(App):
    """Mimic 4 Textual メインアプリ — ModelSelectScreen → ChatScreen"""

    TITLE     = "MIMIC 4"
    SUB_TITLE = "THE HYBRID AI AGENT"
    CSS       = _CSS

    def __init__(
        self,
        or_config,
        gemini_config,
        mistral_config,
        orch_factory: Callable,
    ) -> None:
        super().__init__()
        self._or_config      = or_config
        self._gemini_config  = gemini_config
        self._mistral_config = mistral_config
        self._orch_factory   = orch_factory

    def on_mount(self) -> None:
        self.push_screen(
            ModelSelectScreen(
                self._or_config,
                self._gemini_config,
                self._mistral_config,
            ),
            callback=self._after_selection,
        )

    def _after_selection(self, selected_config) -> None:
        if selected_config is None:
            self.exit()
            return
        orch, config_name, model_name, cwd = self._orch_factory(selected_config)
        self.push_screen(ChatScreen(orch, config_name, model_name, cwd))
