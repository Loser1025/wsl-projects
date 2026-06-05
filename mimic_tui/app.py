"""mimic_claude Textual TUI アプリ本体 (2ペイン・サイバー版)。"""
from __future__ import annotations

import ctypes
import threading
from typing import Optional, Callable

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual.widgets import Footer, RichLog, Static, TabbedContent, TabPane, TextArea, Tree


# 入力エリアの行数設定
_INPUT_MIN_LINES = 1
_INPUT_MAX_LINES = 5
_INPUT_BAR_BORDER = 2  # round ボーダー上下


class ChatInput(TextArea):
    """Enter で送信・Ctrl+N で改行するチャット入力欄。"""

    class Submit(Message):
        """送信トリガー。"""

    # priority=True でウィジェット内部の処理より先に評価される
    BINDINGS = [
        Binding("enter",  "submit",  "送信", priority=True),
        Binding("ctrl+n", "newline", "改行", priority=True),
    ]

    def action_submit(self) -> None:
        self.post_message(ChatInput.Submit())

    def action_newline(self) -> None:
        self.insert("\n")


class MimicApp(App):
    """mimic_claude Textual TUI アプリ (2ペイン仕様)。"""

    TITLE = "mimic"

    CSS = """
    Screen {
        background: #0d1117;
        layout: vertical;
        padding: 0;
    }

    #title-bar {
        layout: horizontal;
        height: auto;
        background: #161b22;
        border-bottom: solid #21262d;
    }

    #title-art {
        width: 1fr;
        height: auto;
        background: #161b22;
        color: #58a6ff;
        padding: 0 2;
        text-style: bold;
    }

    #status-panel {
        width: 36;
        height: auto;
        background: #161b22;
        border-left: solid #30363d;
        padding: 0 2;
    }

    .panel-section {
        height: auto;
        margin-bottom: 1;
    }

    #chat-log {
        height: 1fr;
        background: #0d1117;
        border: none;
        padding: 1 2;
        scrollbar-color: #00ff41;
    }

    #input-bar {
        height: 3;
        margin: 0 2 1 2;
        background: #161b22;
        border: round #30363d;
        padding: 0 0;
    }

    #input-bar:focus-within {
        border: round #00ff41;
    }

    #user-input {
        background: #161b22;
        color: #f0f6fc;
        border: none;
        height: 1fr;
        scrollbar-size: 0 0;
    }

    #user-input:focus {
        border: none;
    }

    Footer {
        background: #161b22;
        color: #8b949e;
    }

    TabbedContent {
        height: 1fr;
        margin: 0 2 0 2;
    }

    TabbedContent ContentSwitcher {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    #files-split {
        height: 1fr;
        layout: horizontal;
    }

    #file-tree {
        width: 1fr;
        height: 1fr;
        background: #0d1117;
        padding: 0 1;
        scrollbar-color: #00ff41;
        border-right: solid #30363d;
    }

    #preview-pane {
        width: 2fr;
        height: 1fr;
        layout: vertical;
    }

    #file-preview {
        height: 1fr;
        background: #0d1117;
        padding: 0 2;
        scrollbar-color: #00ff41;
    }

    #file-search-bar {
        height: 3;
        background: #161b22;
        border-top: solid #30363d;
        padding: 0 1;
        display: none;
    }

    #file-search-bar:focus-within {
        border-top: solid #00ff41;
    }

    #file-search-input {
        background: transparent;
        border: none;
        color: #f0f6fc;
        width: 1fr;
    }

    #file-search-input:focus {
        border: none;
    }

    #scratchpad-log, #log-view, #workflow-view {
        height: 1fr;
        background: #0d1117;
        border: none;
        padding: 1 2;
        margin: 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+c",    "interrupt",        "中断",         show=True),
        Binding("ctrl+q",    "quit_app",          "終了",         show=True),
        Binding("ctrl+l",    "clear_log",         "画面クリア",   show=False),
        Binding("pageup",    "scroll_up",         "↑",            show=False, priority=True),
        Binding("pagedown",  "scroll_down",       "↓",            show=False, priority=True),
        Binding("ctrl+home", "scroll_top",        "先頭",         show=False),
        Binding("ctrl+end",  "scroll_end",        "末尾",         show=False),
        Binding("f1", "switch_tab('tab-chat')",       "Chat",       show=True, priority=True),
        Binding("f2", "switch_tab('tab-files')",      "Files",      show=True, priority=True),
        Binding("f3", "switch_tab('tab-scratchpad')", "Scratch",    show=True, priority=True),
        Binding("f4", "switch_tab('tab-log')",        "Log",        show=True, priority=True),
        Binding("f5", "switch_tab('tab-workflow')",   "Workflow",   show=True, priority=True),
    ]

    agent_status_text = reactive("IDLE")

    def __init__(self, ctx: dict):
        super().__init__()
        self._ctx                             = ctx
        self._agent_mode                    = "interactive"
        self._log: Optional[RichLog]          = None
        self._agent_busy                      = False
        self._worker_thread_id: Optional[int] = None
        self._out_buf                         = ""
        self._out_buf_lock                    = threading.Lock()
        self._approval_callback: Optional[Callable[[str], None]] = None
        # Files タブ プレビュー状態
        self._preview_path: Optional[object]  = None
        self._preview_all_lines: list[str]     = []
        self._preview_searching: bool          = False

    # ── 構成 ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Container(id="title-bar"):
            yield Static("", id="title-art")
            with Vertical(id="status-panel"):
                yield Static("", id="sec-status", classes="panel-section")
                yield Static("", id="sec-system", classes="panel-section")
        with TabbedContent(initial="tab-chat"):
            with TabPane("💬 Chat", id="tab-chat"):
                yield RichLog(id="chat-log", highlight=False, markup=False, wrap=True)
            with TabPane("📁 Files", id="tab-files"):
                with Horizontal(id="files-split"):
                    yield Tree("", id="file-tree")
                    with Vertical(id="preview-pane"):
                        yield RichLog(id="file-preview", highlight=False, markup=False, wrap=True)
                        with Vertical(id="file-search-bar"):
                            yield ChatInput(id="file-search-input", language=None, show_line_numbers=False)
            with TabPane("📝 Scratchpad", id="tab-scratchpad"):
                yield RichLog(id="scratchpad-log", highlight=False, markup=True, wrap=True)
            with TabPane("📜 Log", id="tab-log"):
                yield RichLog(id="log-view", highlight=False, markup=True, wrap=True)
            with TabPane("🔄 Workflow", id="tab-workflow"):
                yield RichLog(id="workflow-view", highlight=False, markup=True, wrap=True)
        with Vertical(id="input-bar"):
            yield ChatInput(id="user-input", language=None, show_line_numbers=False)
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

        cfg = self._ctx["active_config"]
        cwd = self._ctx["agent"].cwd


        subtitle = f"{cfg.model}  ·  {cwd}"
        art_text = Text.from_ansi(get_ascii_art_str(subtitle))
        self.query_one("#title-art", Static).update(art_text)

        self._write_direct(f"作業Dir: {cwd}\n")
        self._write_direct("─" * 60 + "\n")

        self.query_one("#sec-system", Static).update(
            "[bold #00ff41]■ SYSTEM[/]\n"
            "  OS: WSL2 Linux\n"
            "  Git: [bold #00ff41]ACTIVE[/]"
        )

        self._refresh_status_ui()
        self._set_input_hint("idle")
        self._build_file_tree()
        self._show_file_preview(None)
        self._refresh_scratchpad_tab()
        self.query_one("#workflow-view", RichLog).write(
            "[dim]Plan モード（/mode plan）で実行すると表示されます。[/dim]"
        )
        self.query_one("#user-input", ChatInput).focus()

    # ── 入力ヒント管理 ────────────────────────────────────────────────

    def _set_input_hint(self, mode: str, custom: str = "") -> None:
        """#input-bar の border_title でヒントを表示する。"""
        hints = {
            "idle":     "Enter 送信  ·  Ctrl+N 改行  ·  /help でコマンド一覧",
            "busy":     "⏳ 実行中... (Ctrl+C で中断)",
            "approval": f"Y/n を入力  ·  Enter で確定  ·  {self._APPROVAL_TIMEOUT}秒で自動承認",
            "search":   "番号カンマ区切り / all で全件 / n でキャンセル  ·  Enter で確定",
        }
        try:
            self.query_one("#input-bar").border_title = custom or hints.get(mode, "")
        except Exception:
            pass

    # ── リアクティブ・ウォッチャー ────────────────────────────────────

    def watch_agent_status_text(self, _: str) -> None:
        self._refresh_status_ui()

    def _refresh_status_ui(self) -> None:
        try:
            status = self.agent_status_text
            style  = "bold #00ff41" if status == "IDLE" else "bold #ffda6a"
            self.query_one("#sec-status", Static).update(
                f"[bold #00ff41]■ AGENT[/]\n"
                f"  Status: [{style}]{status}[/]\n"
                f"  Mode:   [#58a6ff]{self._agent_mode.upper()}[/]"
            )
        except Exception:
            pass

    # ── タブ: Files ──────────────────────────────────────────────────

    def _build_file_tree(self) -> None:
        from pathlib import Path
        tree = self.query_one("#file-tree", Tree)
        tree.clear()
        root = Path(self._ctx["agent"].cwd)
        tree.root.set_label(f"📁 {root}")
        tree.root.data = str(root)
        self._populate_tree(tree.root, root)
        tree.root.expand()

    def _populate_tree(self, node, path, depth: int = 0) -> None:
        from pathlib import Path
        if depth > 2:
            return
        ignore = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}
        try:
            items = sorted(Path(path).iterdir(), key=lambda p: (p.is_file(), p.name))
            for item in items:
                if item.name in ignore or item.name.startswith("."):
                    continue
                if item.is_dir():
                    child = node.add(f"📁 {item.name}", data=str(item))
                    self._populate_tree(child, item, depth + 1)
                else:
                    node.add_leaf(f"📄 {item.name}", data=str(item))
        except PermissionError:
            pass

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """タブ切り替え時のフォーカス管理（Ctrl+1-5 以外の経路用）。"""
        if str(event.tab.id) == "tab-files--content-tab-files":
            self.query_one("#file-tree", Tree).focus()

    def on_key(self, event) -> None:
        focused_id = getattr(self.focused, "id", None)

        # 検索バーの Backspace（空のとき）→ 閉じる
        if event.key == "backspace" and focused_id == "file-search-input":
            inp = self.query_one("#file-search-input", ChatInput)
            if not inp.text:
                self._close_file_search()
                event.prevent_default()
                event.stop()
                return

        # プレビューの / → 検索バーを開く
        if event.key == "slash" and focused_id == "file-preview":
            if self._preview_path:
                self._open_file_search()
                event.prevent_default()
                event.stop()
                return

        if event.key == "backspace":
            focused = self.focused
            if focused and getattr(focused, "id", None) == "file-preview":
                self.query_one("#file-tree", Tree).focus()
                event.prevent_default()
                event.stop()
                return
            if focused and getattr(focused, "id", None) == "file-tree":
                from pathlib import Path
                parent = Path(self._ctx["agent"].cwd).parent
                if parent != Path(self._ctx["agent"].cwd):
                    self._ctx["agent"].cwd = str(parent)
                    self._update_title()
                    self._build_file_tree()
                    self.query_one("#file-tree", Tree).focus()
                event.prevent_default()
                event.stop()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        from pathlib import Path
        if not event.node.data:
            return
        path = Path(event.node.data)
        if path.is_dir():
            self._ctx["agent"].cwd = str(path)
            self._update_title()
            self._write_direct(f"  📁 作業Dir → {path}\n")
            self._build_file_tree()
            self._show_file_preview(None)
        else:
            self._show_file_preview(path)

    def _show_file_preview(self, path, *, load_all: bool = False) -> None:
        preview = self.query_one("#file-preview", RichLog)
        preview.clear()
        if path is None:
            self._preview_path       = None
            self._preview_all_lines  = []
            self._preview_searching  = False
            preview.write(Text("ファイルを選択してください"))
            return
        from pathlib import Path
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            self._preview_path      = p
            self._preview_all_lines = text.splitlines()
            self._preview_searching = False
        except Exception as e:
            preview.write(Text(f"読み込みエラー: {e}", style="bold red"))
            preview.focus()
            return
        self._render_preview(self._preview_all_lines, load_all=load_all)
        preview.scroll_home()
        preview.focus()

    def _render_preview(self, lines: list, *, load_all: bool = False,
                        matches: set = None) -> None:
        """(lineno, text) のリスト or str リストをプレビューに描画する。"""
        preview = self.query_one("#file-preview", RichLog)
        preview.clear()
        p = self._preview_path
        if p:
            header = Text()
            header.append(f"📄 {p.name}", style="bold #58a6ff")
            total = len(self._preview_all_lines)
            header.append(f"  ({total} lines)")
            if self._preview_searching:
                header.append(f"  [{len(lines)} マッチ行]", style="#ffda6a")
            preview.write(header)
            preview.write(Text("─" * 60, style="#30363d"))

        for idx, item in enumerate(lines):
            if isinstance(item, tuple):
                lineno, text = item
            else:
                lineno, text = idx, item
            row = Text()
            row.append(f"{lineno + 1:4d} ", style="#8b949e")
            if matches and lineno in matches:
                row.append(text, style="bold #ffda6a on #2d2800")
            else:
                row.append(text)
            preview.write(row)


    # ── Files: 検索 ──────────────────────────────────────────────────

    def _open_file_search(self) -> None:
        bar = self.query_one("#file-search-bar")
        bar.display = True
        inp = self.query_one("#file-search-input", ChatInput)
        inp.load_text("")
        self.query_one("#file-search-bar").border_title = "/ 検索  Enter=確定  Escape=閉じる"
        inp.focus()

    def _close_file_search(self) -> None:
        self._preview_searching = False
        bar = self.query_one("#file-search-bar")
        bar.display = False
        if self._preview_all_lines:
            self._render_preview(self._preview_all_lines)
        self.query_one("#file-preview", RichLog).focus()

    def _run_file_search(self, pattern: str) -> None:
        import re as _re
        if not pattern or not self._preview_all_lines:
            self._close_file_search()
            return
        try:
            regex = _re.compile(pattern, _re.IGNORECASE)
        except _re.error:
            regex = _re.compile(_re.escape(pattern), _re.IGNORECASE)
        results = [(i, line) for i, line in enumerate(self._preview_all_lines)
                   if regex.search(line)]
        match_set = {i for i, _ in results}
        self._preview_searching = True
        # マッチ前後2行のコンテキストも表示
        context_indices = set()
        for i in match_set:
            for d in range(-2, 3):
                idx = i + d
                if 0 <= idx < len(self._preview_all_lines):
                    context_indices.add(idx)
        context_lines = [(i, self._preview_all_lines[i])
                         for i in sorted(context_indices)]
        self._render_preview(context_lines, matches=match_set)
        self.query_one("#file-preview", RichLog).scroll_home()
        self.query_one("#file-search-bar").border_title = (
            f"/ {pattern}  {len(results)} マッチ  Escape=閉じる"
        )

    # ── タブ: Scratchpad ─────────────────────────────────────────────

    def _refresh_scratchpad_tab(self) -> None:
        from .utils import get_scratchpad
        log = self.query_one("#scratchpad-log", RichLog)
        log.clear()
        content = get_scratchpad()
        if content:
            log.write(content)
        else:
            log.write("[dim]スクラッチパッドはまだ空です。[/dim]")

    # ── タブ: Log ────────────────────────────────────────────────────

    def _refresh_log_tab(self) -> None:
        log = self.query_one("#log-view", RichLog)
        log.clear()
        entries = self._ctx["interactive_orch"].react_log.entries
        if not entries:
            log.write("[dim]ログエントリがありません。[/dim]")
            return
        for e in entries[-100:]:
            ev   = e.get("event", "")
            role = e.get("role", "")
            if ev == "session_start":
                log.write(f"[bold #58a6ff]▶ セッション開始  model={e.get('model','')}[/]")
            elif role == "user":
                msg = str(e.get("content", ""))[:120]
                log.write(f"[bold #00ff41]❯ {msg}[/]")
            elif role == "assistant":
                log.write(f"[#8b949e]⬡ (assistant response)[/]")
            elif ev == "tool_call":
                log.write(f"[#ffda6a]⚙ {e.get('name','')}({str(e.get('args',''))[:60]})[/]")
            elif ev == "tool_result":
                res = str(e.get("content",""))[:80]
                log.write(f"[dim]  → {res}[/]")

    # ── タブ: Workflow ───────────────────────────────────────────────

    def _refresh_workflow_tab(self, steps: list) -> None:
        log = self.query_one("#workflow-view", RichLog)
        log.clear()
        icons = {"pending":"○", "running":"▶", "done":"✓", "failed":"✗",
                 "retrying":"↻", "skipped":"⏭"}
        colors = {"pending":"#8b949e", "running":"#ffda6a", "done":"#00ff41",
                  "failed":"#ff6b6b", "retrying":"#ffda6a", "skipped":"#8b949e"}
        total = len(steps)
        done  = sum(1 for s in steps if s.status == "done")
        log.write(f"[bold #58a6ff]Plan-and-Execute  {done}/{total} ステップ完了[/]\n")
        for s in steps:
            icon  = icons.get(s.status, "○")
            color = colors.get(s.status, "#8b949e")
            par   = "  [⚡並列]" if getattr(s, "parallel", False) else ""
            label = f"  [{s.label}]" if s.label else ""
            log.write(f"[{color}]  {icon} Step {s.index}: {s.description}{par}{label}[/]")

    # ── 動的高さ調整 ──────────────────────────────────────────────────

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """入力行数に応じて #input-bar の高さを動的に変更する。"""
        n = max(_INPUT_MIN_LINES, min(event.text_area.text.count("\n") + 1, _INPUT_MAX_LINES))
        self.query_one("#input-bar").styles.height = n + _INPUT_BAR_BORDER

    # ── Enter 送信（ChatInput.Submit メッセージ受信） ─────────────────

    def on_chat_input_submit(self, event: ChatInput.Submit) -> None:
        # 検索バーからの送信
        if getattr(self.focused, "id", None) == "file-search-input":
            inp = self.query_one("#file-search-input", ChatInput)
            query = inp.text.strip()
            inp.load_text("")
            self._run_file_search(query)
            self.query_one("#file-preview", RichLog).focus()
            return
        ta   = self.query_one("#user-input", ChatInput)
        text = ta.text.strip()
        ta.load_text("")
        self.query_one("#input-bar").styles.height = _INPUT_MIN_LINES + _INPUT_BAR_BORDER
        self._process_input(text)

    def _process_input(self, text: str) -> None:
        if self._approval_callback is not None:
            callback = self._approval_callback
            self._approval_callback = None
            callback(text)
            if self._agent_busy:
                self._set_input_hint("busy")
                self.query_one("#user-input", ChatInput).disabled = True
            else:
                self._set_input_hint("idle")
                self.query_one("#user-input", ChatInput).disabled = False
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

        self._write_user_message(text)
        self._start_agent(text)

    # ── 出力コールバック ──────────────────────────────────────────────

    def _safe_write_line(self, line: str) -> None:
        if self._log is None:
            return
        rich_text = Text.from_ansi(line)
        try:
            self.call_from_thread(self._log.write, rich_text)
        except RuntimeError:
            try:
                self._log.write(rich_text)
            except Exception:
                pass
        except Exception:
            pass

    def _output_callback(self, text: str) -> None:
        if self._log is None:
            return
        with self._out_buf_lock:
            self._out_buf += text
            lines = self._out_buf.split("\n")
            self._out_buf = lines[-1]
            complete = lines[:-1]
        for line in complete:
            self._safe_write_line(line)

    def _flush_output_buf(self) -> None:
        with self._out_buf_lock:
            remaining = self._out_buf
            self._out_buf = ""
        if remaining:
            self._safe_write_line(remaining)

    def _update_title(self) -> None:
        from .utils import get_ascii_art_str
        cfg      = self._ctx["active_config"]
        cwd      = self._ctx["agent"].cwd
        subtitle = f"{cfg.model}  ·  {cwd}"
        try:
            art_text = Text.from_ansi(get_ascii_art_str(subtitle))
            self.query_one("#title-art", Static).update(art_text)
        except Exception:
            pass

    def _write_direct(self, text: str) -> None:
        if self._log is None:
            return
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if i == len(lines) - 1 and line == "":
                break
            self._log.write(Text.from_ansi(line))

    def _write_user_message(self, text: str) -> None:
        if self._log is None:
            return
        self._log.write(Text(""))
        label = Text()
        label.append("  👤 You: ", style="bold #00ff41")
        self._log.write(label)
        msg = Text()
        msg.append(f"  {text}", style="bold #f0f6fc")
        self._log.write(msg)
        self._log.write(Text(""))

    # ── 書き込み承認 ──────────────────────────────────────────────────

    _APPROVAL_TIMEOUT = 30

    def _make_approval_handler(self):
        app = self

        def handler(tool_name: str, args: dict, preview: str) -> bool:
            from .utils import safe_print, C

            path = args.get("path", "?")
            app.agent_status_text = "WAIT_APPROVAL"

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
                app.call_from_thread(app._exit_approval_mode)

            if result[0]:
                safe_print(C.green("  ✓ 承認しました"))
            else:
                safe_print(C.red("  ✗ 拒否しました（処理を中断します）"))

            app.agent_status_text = "THINKING"
            return result[0]

        return handler

    def _enter_approval_mode(
        self,
        callback: Callable[[str], None],
        hint_mode: str = "approval",
    ) -> None:
        self._approval_callback = callback
        ta = self.query_one("#user-input", ChatInput)
        ta.disabled = False
        self._set_input_hint(hint_mode)
        ta.focus()

    def _exit_approval_mode(self) -> None:
        self._approval_callback = None
        if self._agent_busy:
            self.query_one("#user-input", ChatInput).disabled = True
            self._set_input_hint("busy")

    # ── AI レスポンスストリーム ──────────────────────────────────────

    def _stream_callback(self, text: str) -> None:
        if not text or not text.strip():
            return
        if self._log is None:
            return
        rich_md = RichMarkdown(text)
        try:
            self.call_from_thread(self._log.write, rich_md)
        except RuntimeError:
            try:
                self._log.write(rich_md)
            except Exception:
                pass
        except Exception:
            pass

    # ── キーバインド・アクション ──────────────────────────────────────

    def action_interrupt(self) -> None:
        if not self._agent_busy or self._worker_thread_id is None:
            return
        self._write_direct("\n  [割り込み] Ctrl+C — 中断を要求しました...\n")
        self.agent_status_text = "INTERRUPTING"
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(self._worker_thread_id),
            ctypes.py_object(KeyboardInterrupt),
        )

    def action_quit_app(self) -> None:
        from .utils import set_tui_output, set_tui_mode, set_tui_stream

        sessions_dir = self._ctx.get("sessions_dir")
        react_log    = self._ctx["interactive_orch"].react_log

        if sessions_dir and react_log.entries:
            try:
                result = react_log.save_session(sessions_dir)
                self._write_direct(f"  [Session] {result}\n")
            except Exception as e:
                self._write_direct(f"  [Session] 保存失敗: {e}\n")

        set_tui_mode(False)
        set_tui_output(None)
        set_tui_stream(None)
        self.exit()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id
        if tab_id == "tab-files":
            self.query_one("#file-tree", Tree).focus()
        elif tab_id == "tab-scratchpad":
            self._refresh_scratchpad_tab()
            self.query_one("#user-input", ChatInput).focus()
        elif tab_id == "tab-log":
            self._refresh_log_tab()
            self.query_one("#user-input", ChatInput).focus()
        else:
            self.query_one("#user-input", ChatInput).focus()

    def action_clear_log(self) -> None:
        if self._log:
            self._log.clear()

    def _active_scroll_target(self) -> Optional[RichLog]:
        tab_map = {
            "tab-chat":       "#chat-log",
            "tab-files":      "#file-preview",
            "tab-scratchpad": "#scratchpad-log",
            "tab-log":        "#log-view",
            "tab-workflow":   "#workflow-view",
        }
        try:
            sel = tab_map.get(self.query_one(TabbedContent).active, "#chat-log")
            return self.query_one(sel, RichLog)
        except Exception:
            return self._log

    def action_scroll_up(self) -> None:
        w = self._active_scroll_target()
        if w:
            w.scroll_page_up()

    def action_scroll_down(self) -> None:
        w = self._active_scroll_target()
        if w:
            w.scroll_page_down()

    def action_scroll_top(self) -> None:
        w = self._active_scroll_target()
        if w:
            w.scroll_home()

    def action_scroll_end(self) -> None:
        w = self._active_scroll_target()
        if w:
            w.scroll_end()

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
            if cmd == "cd":
                self._update_title()
        else:
            self._write_direct(
                f"  不明なコマンド: {text}\n"
                "  /help でコマンド一覧を確認してください。\n"
            )

    def _cmd_mode(self, arg: str) -> None:
        arg = arg.strip().lower()
        if arg in ("interactive", "react", "i"):
            self._agent_mode = "interactive"
            self._ctx["agent"].set_system_prompt(self._ctx["react_prompt"])
            self._ctx["agent"].clear_history()
            self._ctx["interactive_orch"].react_log.clear()
            self._write_direct("⚡ モード: Interactive (ReAct)  会話履歴をリセットしました。\n")
        elif arg in ("plan", "p"):
            self._agent_mode = "plan"
            self._ctx["agent"].set_system_prompt(self._ctx["plan_prompt"])
            self._ctx["agent"].clear_history()
            self._ctx["interactive_orch"].react_log.clear()
            self._write_direct("≡  モード: Plan-and-Execute  会話履歴をリセットしました。\n")
        elif arg in ("multi", "m"):
            if not self._ctx.get("multi_orch"):
                self._write_direct(
                    "  ✗ マルチエージェントの初期化に失敗しています。再起動してください。\n"
                )
                return
            self._agent_mode = "multi"
            self._ctx["multi_orch"].clear_all_history()
            self._write_direct("🌐 モード: Multi-Agent (Architect + Operator + Scribe)\n")
        else:
            mode_labels = {
                "interactive": "Interactive (ReAct)",
                "plan": "Plan-and-Execute",
                "multi": "Multi-Agent",
            }
            label = mode_labels.get(self._agent_mode, self._agent_mode)
            self._write_direct(
                f"  現在: {label}\n"
                "  切替: /mode interactive  /mode plan  /mode multi\n"
            )
        self._refresh_status_ui()

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
        self._write_direct(
            "  コンテキストに注入しますか？ [番号をカンマ区切り / all / n]: "
        )

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

        self._enter_approval_mode(on_response, hint_mode="search")

    # ── エージェント実行 ──────────────────────────────────────────────

    def _start_agent(self, user_input: str) -> None:
        self._agent_busy       = True
        self.agent_status_text = "THINKING"
        self.query_one("#user-input", ChatInput).disabled = True
        self._set_input_hint("busy")
        if self._agent_mode == "multi":
            self._run_multi(user_input)
        elif self._agent_mode == "interactive":
            self._run_react(user_input)
        else:
            self._run_plan(user_input)

    def _on_agent_done(self) -> None:
        self._agent_busy       = False
        self._worker_thread_id = None
        self.agent_status_text = "IDLE"
        self._flush_output_buf()
        ta = self.query_one("#user-input", ChatInput)
        ta.disabled = False
        self._set_input_hint("idle")
        if self._log:
            self._log.write(Text.from_ansi("─" * 60))
        self._refresh_scratchpad_tab()
        self._refresh_log_tab()
        ta.focus()

    @work(thread=True, exclusive=True)
    def _run_react(self, user_input: str) -> None:
        self._worker_thread_id = threading.current_thread().ident
        try:
            self._ctx["interactive_orch"].run_react(user_input)
        except KeyboardInterrupt:
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

        _all_steps: list = []

        def on_plan(steps: list) -> None:
            _all_steps.clear()
            _all_steps.extend(steps)
            self.call_from_thread(self._show_plan_header, steps)
            self.call_from_thread(self._refresh_workflow_tab, list(steps))

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
            self.call_from_thread(self._refresh_workflow_tab, list(_all_steps))

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

    @work(thread=True, exclusive=True)
    def _run_multi(self, user_input: str) -> None:
        """WorkflowGraph ベースのマルチエージェント実行。Workflow タブをリアルタイム更新する。"""
        self._worker_thread_id = threading.current_thread().ident
        multi_orch = self._ctx.get("multi_orch")
        if multi_orch is None:
            self.call_from_thread(
                self._log.write,
                Text.from_ansi("  ✗ multi_orch が初期化されていません。\n")
            )
            self.call_from_thread(self._on_agent_done)
            return

        multi_orch.set_cwd(self._ctx["agent"].cwd)

        # 実行開始時に Workflow タブへ自動切り替え
        self.call_from_thread(self.action_switch_tab, "tab-workflow")

        _all_steps: list = []

        def _on_plan(steps: list) -> None:
            _all_steps.clear()
            _all_steps.extend(steps)
            self.call_from_thread(self._refresh_workflow_tab, list(steps))

        def _on_step(step) -> None:
            self.call_from_thread(self._refresh_workflow_tab, list(_all_steps))

        def _on_agent_switch(name: str) -> None:
            if self._log:
                self.call_from_thread(
                    self._log.write,
                    Text.from_ansi(f"\n  🤖 [{name}] ────────────────────────────\n"),
                )
            self.call_from_thread(
                lambda n=name: setattr(self, "agent_status_text", n)
            )

        try:
            multi_orch.execute_task(
                user_input,
                on_plan         = _on_plan,
                on_step         = _on_step,
                on_agent_switch = _on_agent_switch,
            )
        except KeyboardInterrupt:
            from .utils import C
            if self._log:
                self.call_from_thread(
                    self._log.write,
                    Text.from_ansi(C.yellow("\n\n  [割り込み] Ctrl+C — マルチエージェントを中断しました。\n")),
                )
        except Exception as e:
            if self._log:
                self.call_from_thread(
                    self._log.write, Text.from_ansi(f"\nマルチエージェントエラー: {e}\n")
                )
        finally:
            self.call_from_thread(self._on_agent_done)

    def _show_plan_header(self, steps: list) -> None:
        self._write_direct("\n実行計画\n" + "─" * 40 + "\n")
        for s in steps:
            parallel = " [並列]" if s.parallel else ""
            self._write_direct(f"  Step {s.index}: {s.description}{parallel}\n")
        self._write_direct("─" * 40 + "\n\n")
