"""
mimic_tui — Textual TUI アプリ本体 (Phase 1)

基本的なチャットUI:
  - Header（タイトル）
  - ScrollableContainer（チャットログ）
  - Input（プロンプト）
  - Footer（キーバインド表示）
"""
from __future__ import annotations

import asyncio
from typing import Optional
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Header, Footer, Input, Static, Label
from textual.css.query import NoMatches
from textual import events


class ChatLog(ScrollableContainer):
    """チャットメッセージを表示するスクロール可能なコンテナ。"""

    def add_message(self, text: str, role: str = "assistant") -> None:
        """メッセージを追加して自動スクロール。"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"user": "👤", "assistant": "🤖", "system": "⚙️"}.get(role, "?")
        colors = {
            "user": "cyan",
            "assistant": "green",
            "system": "yellow",
        }
        color = colors.get(role, "white")
        msg = Static(
            f"[{color}]{timestamp} {prefix} {text}[/]",
            classes=f"chat-msg chat-{role}",
        )
        self.mount(msg)
        self.scroll_end(animate=False)


class StatusBar(Static):
    """画面上部（Header直下）に簡易ステータスを表示。"""

    def __init__(self) -> None:
        super().__init__("準備完了 | Phase 1", id="status-bar")
        self.styles.background = "#1e1e2e"
        self.styles.color = "#cdd6f4"
        self.styles.height = 1
        self.styles.padding = (0, 1)

    def update_status(self, text: str) -> None:
        self.update(text)


class MimicApp(App):
    """Textual TUI メインアプリ。"""

    TITLE = "mimic_tui"
    CSS = """
    Screen {
        layers: base overlay;
    }

    #status-bar {
        dock: top;
        height: 1;
    }

    #chat-log {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }

    .chat-msg {
        height: auto;
        margin-bottom: 0;
    }

    #input-container {
        dock: bottom;
        height: 3;
        padding: 0 1;
    }

    Input {
        height: 3;
        border: solid #89b4fa;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("pageup", "scroll_up", "", show=False),
        Binding("pagedown", "scroll_down", "", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._status: Optional[StatusBar] = None
        self._chat_log: Optional[ChatLog] = None

    def compose(self) -> ComposeResult:
        yield Header()
        self._status = StatusBar()
        yield self._status
        self._chat_log = ChatLog(id="chat-log")
        yield self._chat_log
        yield Input(placeholder="メッセージを入力... (Ctrl+C で終了)", id="chat-input")
        yield Footer()

    def on_mount(self) -> None:
        if self._chat_log:
            self._chat_log.add_message("mimic_tui へようこそ！（Phase 1）", role="system")
            self._chat_log.add_message("Ctrl+C または /exit で終了します。", role="system")
        try:
            input_widget = self.query_one("#chat-input", Input)
            input_widget.focus()
        except NoMatches:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.input.value.strip()
        if not text:
            event.input.value = ""
            return

        # ユーザーメッセージ表示
        if self._chat_log:
            self._chat_log.add_message(text, role="user")

        # コマンド処理
        if text in ("/exit", "/quit", "/q"):
            self.exit()
            return

        if text == "/clear":
            self.action_clear_chat()
            event.input.value = ""
            return

        if text == "/help":
            self._show_help()
            event.input.value = ""
            return

        # Phase 1: エコー応答
        if self._chat_log:
            self._chat_log.add_message(
                f"（ダミー応答）受信: {text}", role="assistant"
            )

        event.input.value = ""

    def action_clear_chat(self) -> None:
        if self._chat_log:
            self._chat_log.remove_children()
            self._chat_log.add_message("チャットをクリアしました。", role="system")

    def action_scroll_up(self) -> None:
        if self._chat_log:
            self._chat_log.scroll_page_up(animate=False)

    def action_scroll_down(self) -> None:
        if self._chat_log:
            self._chat_log.scroll_page_down(animate=False)

    # Textual ページスクロール用アップデート
    def action_scroll_up(self) -> None:
        if self._chat_log:
            self._chat_log.scroll_page_up(animate=False)

    def _show_help(self) -> None:
        help_lines = [
            "📖 コマンド一覧",
            "  /exit, /quit — アプリ終了",
            "  /clear — チャットクリア",
            "  /help — このヘルプを表示",
            "",
            "⌨️  キーバインド",
            "  Ctrl+C / Ctrl+Q — 終了",
            "  Ctrl+L — チャットクリア",
            "  PageUp / PageDown — スクロール",
        ]
        if self._chat_log:
            for line in help_lines:
                self._chat_log.add_message(line, role="system")


if __name__ == "__main__":
    app = MimicApp()
    app.run()
