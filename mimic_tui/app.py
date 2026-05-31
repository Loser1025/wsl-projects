"""
mimic_tui — Textual TUI アプリ本体 (Phase 3)

チャットUI + エージェント統合:
  - Header / Footer
  - ScrollableContainer（チャットログ — ツール呼び出し・思考・最終回答）
  - Input（プロンプト + スラッシュコマンド）
  - worker thread で agent.run() を非同期実行
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Header, Footer, Input, Static, OptionList, Button, Label
from textual.css.query import NoMatches
from textual.screen import ModalScreen


# ──────────────────────────────────────────────────────────────
# UI 部品
# ──────────────────────────────────────────────────────────────

class ChatLog(ScrollableContainer):
    """チャットメッセージを表示するスクロール可能なコンテナ。"""

    def add_message(self, text: str, role: str = "assistant") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        style_map = {
            "user":      ("👤", "cyan"),
            "assistant": ("🤖", "green"),
            "system":    ("⚙️", "yellow"),
            "tool":      ("🔧", "magenta"),
            "thinking":  ("💭", "#a0a0a0"),
        }
        prefix, color = style_map.get(role, ("?", "white"))
        # 複数行メッセージ対応: 各行にスタイルを適用
        formatted_lines = "\n".join(
            f"[{color}]{line}[/]" for line in text.splitlines()
        )
        msg = Static(
            f"[#666666]{timestamp}[/] {prefix} {formatted_lines}",
            classes=f"chat-msg chat-{role}",
        )
        self.mount(msg)
        self.scroll_end(animate=False)


# ──────────────────────────────────────────────────────────────
# エージェント初期化
# ──────────────────────────────────────────────────────────────

def _create_agent():
    """
    mimic_linux __main__.main() と同じ手順でエージェントを初期化して返す。
    (tmux なし, モデルは .env の優先順位で自動選択)
    """
    import os
    import logging
    from pathlib import Path

    base_dir = str(Path(__file__).parent)

    from .utils import set_log_sink
    from .commands import register_search_command, register_sessions_command
    from .tools import set_sessions_dir, tools as _base_tools
    from . import config as _cfg
    from .config import load_config
    from .agent import OpenRouterAgent, AccountRotator
    from .autogit import AutoGit
    from .orchestrator import InteractiveOrchestrator, AgentOrchestrator, BASH_EXECUTOR_GUIDANCE, REACT_SYSTEM_PROMPT
    from .monitoring import MonitoringToolRegistry, ToolCallLog

    # ログの stdout 出力を抑制（TUI が崩れるのを防ぐ）
    logging.getLogger("openrouter_agent").handlers = [
        h for h in logging.getLogger("openrouter_agent").handlers
        if not isinstance(h, logging.StreamHandler)
        or isinstance(h, logging.FileHandler)
    ]

    or_config, gemini_config, mistral_config, system_prompt = load_config(base_dir)
    active_config = or_config or gemini_config or mistral_config
    if active_config is None:
        raise RuntimeError(
            "モデル設定が見つかりません。.env を確認してください。"
        )

    # セッションログ用ディレクトリ
    sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # ツール監視レジストリ
    tool_log = ToolCallLog()

    def _inline_display(record):
        """ツール完了後にログへ記録する（出力はチャットで行うため表示しない）。"""
        pass  # TUI 側でチャットログに表示する

    mon_tools = MonitoringToolRegistry(
        base=_base_tools,
        log=tool_log,
        display_fn=_inline_display,
    )

    rotator = AccountRotator(active_config)
    agent = OpenRouterAgent(rotator, mon_tools)
    auto_git = AutoGit()
    orchestrator = AgentOrchestrator(rotator, mon_tools, executor=agent)

    # CWD 設定
    mimic_cwd = os.environ.get("MIMIC_CWD")
    if mimic_cwd and Path(mimic_cwd).exists():
        agent.cwd = str(Path(mimic_cwd).resolve())
    elif _cfg._DEFAULT_CWD and Path(_cfg._DEFAULT_CWD).exists():
        agent.cwd = str(Path(_cfg._DEFAULT_CWD).resolve())

    # システムプロンプト
    plan_prompt = (system_prompt or "") + BASH_EXECUTOR_GUIDANCE
    react_prompt = plan_prompt + REACT_SYSTEM_PROMPT
    agent.set_system_prompt(react_prompt)
    orchestrator.set_executor_system_prompt(plan_prompt)
    interactive_orch = InteractiveOrchestrator(agent, auto_git)

    # セッションログ
    from datetime import datetime as _dt
    _jsonl_path = sessions_dir / f"{_dt.now().strftime('%Y-%m-%d_%H-%M')}.jsonl"
    interactive_orch.react_log.set_jsonl_path(_jsonl_path)
    interactive_orch.react_log.add(
        "session_start",
        model=active_config.model,
        provider=active_config.name,
        cwd=agent.cwd,
    )
    set_log_sink(
        lambda level, msg: interactive_orch.react_log.add(
            "system_event", level=level, content=msg
        )
    )
    register_search_command(lambda: sessions_dir)
    register_sessions_command(lambda: sessions_dir)
    set_sessions_dir(sessions_dir)

    return agent, active_config, sessions_dir, tool_log


# ──────────────────────────────────────────────────────────────
# メインアプリ
# ──────────────────────────────────────────────────────────────

class MimicApp(App):
    """Textual TUI メインアプリ (Phase 3)。"""

    TITLE = "mimic_tui"

    CSS = """
    Screen {
        layers: base overlay;
    }

    #chat-log {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }

    .chat-msg {
        height: auto;
        margin-bottom: 0;
        padding: 0 0;
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
        self._chat_log: Optional[ChatLog] = None
        self._agent = None
        self._config = None
        self._busy = False
        self._tool_call_count = 0

    def compose(self) -> ComposeResult:
        yield Header()
        self._chat_log = ChatLog(id="chat-log")
        yield self._chat_log
        yield Input(placeholder="メッセージを入力... (Ctrl+C で終了)", id="chat-input")
        yield Footer()

    def on_mount(self) -> None:
        if self._chat_log:
            self._chat_log.add_message("mimic_tui へようこそ！（Phase 3）", role="system")

        # エージェント初期化（少し時間がかかるので非同期で進捗表示）
        self._chat_log.add_message("エージェントを初期化中...", role="system") if self._chat_log else None
        self.call_later(self._init_agent)

    def _init_agent(self) -> None:
        try:
            agent, config, sessions_dir, tool_log = _create_agent()
            self._agent = agent
            self._config = config
            if self._chat_log:
                self._chat_log.add_message(
                    f"[{config.name}] モデル: {config.model}",
                    role="system",
                )
                self._chat_log.add_message(
                    "準備完了！質問を入力してください。",
                    role="system",
                )
        except Exception as e:
            if self._chat_log:
                self._chat_log.add_message(
                    f"初期化エラー: {e}",
                    role="system",
                )

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

        # ── スラッシュコマンド（Phase 4）──────────────────
        cmd = text.split()[0].lower()
        cmd_args = text[len(cmd):].strip()

        if cmd == "/status":
            self._cmd_status()
            event.input.value = ""
            return

        if cmd == "/stats":
            self._cmd_stats()
            event.input.value = ""
            return

        if cmd == "/clear":
            # チャットクリア + 会話履歴リセット
            self.action_clear_chat()
            if self._agent is not None:
                self._agent.clear_history()
                if self._chat_log:
                    self._chat_log.add_message("会話履歴もリセットしました。", role="system")
            event.input.value = ""
            return

        if cmd == "/model":
            self._cmd_model(cmd_args)
            event.input.value = ""
            return

        if cmd == "/cd":
            self._cmd_cd(cmd_args)
            event.input.value = ""
            return

        if cmd == "/sessions":
            self._cmd_sessions(cmd_args)
            event.input.value = ""
            return

        if cmd == "/search":
            self._cmd_search(cmd_args)
            event.input.value = ""
            return

        if cmd == "/undo":
            self._cmd_undo()
            event.input.value = ""
            return

        if cmd == "/scratchpad":
            self._cmd_scratchpad()
            event.input.value = ""
            return

        if cmd.startswith("/mode"):
            self._show_mode_info(text)
            event.input.value = ""
            return

        # エージェントが初期化済みか確認
        if self._agent is None or self._busy:
            if self._chat_log:
                self._chat_log.add_message(
                    "エージェント初期化中または処理中です。お待ちください。",
                    role="system",
                )
            event.input.value = ""
            return

        # 非同期で agent.run() を実行
        self._busy = True
        self._tool_call_count = 0
        if self._chat_log:
            self._chat_log.add_message("🤔 考え中...", role="thinking")

        worker = threading.Thread(
            target=self._run_agent_worker,
            args=(text,),
            daemon=True,
        )
        worker.start()
        event.input.value = ""

    # ── worker スレッド ──────────────────────────────────────

    def _run_agent_worker(self, user_message: str) -> None:
        """バックグラウンドスレッドで agent.run() を実行。"""
        try:
            result = self._agent.run(user_message)
            # メインスレッドでUI更新
            self.call_from_thread(self._on_agent_done, result, None)
        except Exception as e:
            self.call_from_thread(self._on_agent_done, None, e)

    def _on_agent_done(self, result: Optional[str], error: Optional[Exception]) -> None:
        """agent.run() 完了コールバック（メインスレッド）。"""
        self._busy = False
        if self._chat_log:
            # 「考え中...」メッセージを消す（最後の thinking メッセージを削除）
            # Phase 5 でダイアログ対応するので Phase 3 は暫定的に結果を表示
            if error:
                self._chat_log.add_message(
                    f"エラー: {error}", role="system"
                )
            elif result:
                # 「考え中...」の行を消す: 最後の Static(widget) を特定して削除
                children = list(self._chat_log.children)
                if children and hasattr(children[-1], "classes"):
                    pass  # Phase 5 で精致に対応
                self._chat_log.add_message(result, role="assistant")
            else:
                self._chat_log.add_message(
                    "（応答なし — 結果が空でした）", role="system"
                )

    # ── スラッシュコマンド ────────────────────────────────────

    def action_clear_chat(self) -> None:
        if self._chat_log:
            # チャットをクリア（会話履歴もリセットしない — Phase 4 で対応）
            for child in list(self._chat_log.children):
                child.remove()
            self._chat_log.add_message("チャットをクリアしました。", role="system")

    def action_scroll_up(self) -> None:
        if self._chat_log:
            self._chat_log.scroll_page_up(animate=False)

    def action_scroll_down(self) -> None:
        if self._chat_log:
            self._chat_log.scroll_page_down(animate=False)

    def _show_help(self) -> None:
        help_lines = [
            "📖 コマンド一覧",
            "  /exit, /quit — アプリ終了",
            "  /clear — チャットクリア",
            "  /status — モデル・設定を表示",
            "  /mode interactive|plan — モード切替情報",
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

    def _show_status(self) -> None:
        if self._config is None:
            if self._chat_log:
                self._chat_log.add_message("エージェントが初期化されていません。", role="system")
            return
        if self._chat_log:
            self._chat_log.add_message(
                f"プロバイダー: {self._config.name}", role="system"
            )
            self._chat_log.add_message(
                f"モデル: {self._config.model}", role="system"
            )
            self._chat_log.add_message(
                f"APIキー数: {len(self._config.api_keys)}", role="system"
            )

    def _show_mode_info(self, text: str) -> None:
        modes = text.split()[1:] if len(text.split()) > 1 else []
        if modes and modes[0] in ("interactive", "plan"):
            mode = modes[0]
            if self._chat_log:
                self._chat_log.add_message(f"モードを「{mode}」に切り替えました。（Phase 4 で正式対応）", role="system")
        else:
            if self._chat_log:
                self._chat_log.add_message(
                    "使い方: /mode interactive|plan", role="system"
                )


    # ── Phase 4 コマンド実装 ───────────────────────────────

    def _cmd_status(self) -> None:
        if self._config is None:
            self._chat_log.add_message("エージェントが初期化されていません。", role="system") if self._chat_log else None
            return
        log = self._chat_log
        log.add_message("📊 ステータス", role="system")
        log.add_message(f"  プロバイダー : {self._config.name}", role="system")
        log.add_message(f"  モデル       : {self._config.model}", role="system")
        log.add_message(f"  APIキー数    : {len(self._config.api_keys)}", role="system")
        if self._agent is not None:
            log.add_message(f"  会話ターン数 : {len(self._agent.conversation)}", role="system")

    def _cmd_stats(self) -> None:
        if self._config is None:
            return
        sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
        jsonl_files = list(sessions_dir.glob("*.jsonl")) if sessions_dir.exists() else []
        self._chat_log.add_message(
            f"📊 ツール統計: セッションログ {len(jsonl_files)} 件",
            role="system",
        ) if self._chat_log else None

    def _cmd_model(self, args: str) -> None:
        if self._agent is None:
            self._chat_log.add_message("エージェントが初期化されていません。", role="system") if self._chat_log else None
            return
        arg = args.strip()
        if not arg:
            # モーダルダイアログを表示
            self.push_screen(ModelSelectDialog(self._config.model), self._on_model_selected)
            return
        old = self._config.model
        self._config.model = arg
        self._agent.clear_history()
        self._chat_log.add_message(
            f"モデルを変更: {old} → {arg}（会話履歴リセット）",
            role="system",
        ) if self._chat_log else None

    def _on_model_selected(self, model_name: str | None) -> None:
        if model_name is None or model_name == self._config.model:
            self._chat_log.add_message("モデルは変更されませんでした。", role="system") if self._chat_log else None
            return
        old = self._config.model
        self._config.model = model_name
        self._agent.clear_history()
        self._chat_log.add_message(
            f"モデルを変更: {old} → {model_name}（会話履歴リセット）",
            role="system",
        ) if self._chat_log else None

    def _cmd_cd(self, args: str) -> None:
        if self._agent is None:
            self._chat_log.add_message("エージェントが初期化されていません。", role="system") if self._chat_log else None
            return
        if not args:
            self._chat_log.add_message(
                f"現在の作業フォルダ: {self._agent.cwd}",
                role="system",
            ) if self._chat_log else None
            return
        from pathlib import Path
        new_path = args.strip().strip('"').strip("'")
        expanded = str(Path(new_path).expanduser().resolve())
        if Path(expanded).exists():
            self._agent.set_cwd(expanded)
            self._chat_log.add_message(f"作業フォルダを変更: {expanded}", role="system") if self._chat_log else None
        else:
            self._chat_log.add_message(f"フォルダが見つかりません: {expanded}", role="system") if self._chat_log else None

    def _cmd_sessions(self, args: str) -> None:
        from pathlib import Path
        sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
        jsonl_files = sorted(sessions_dir.glob("*.jsonl"), reverse=True) if sessions_dir.exists() else []
        if not jsonl_files:
            self._chat_log.add_message("セッションログがまだありません。", role="system") if self._chat_log else None
            return

        arg = args.strip()
        if not arg:
            # 一覧表示
            lines = ["📋 過去セッション一覧\n"]
            for i, jf in enumerate(jsonl_files, 1):
                try:
                    content = jf.read_text(encoding="utf-8")
                    turn_count = content.count('"user_input"')
                    first_q = ""
                    for line in content.splitlines():
                        try:
                            e = json.loads(line)
                            if e.get("type") == "user_input":
                                first_q = e.get("content", "")[:60].replace("\n", " ")
                                break
                        except Exception:
                            continue
                except Exception:
                    turn_count = 0
                    first_q = "(読込エラー)"
                lines.append(f"  [{i:2d}] {jf.stem}  {turn_count}ターン  {first_q}")
            self._chat_log.add_message("\n".join(lines), role="system") if self._chat_log else None
        elif arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(jsonl_files):
                self._show_session_detail(jsonl_files[idx])
            else:
                self._chat_log.add_message(f"番号 {arg} は範囲外です（1〜{len(jsonl_files)}）。", role="system") if self._chat_log else None

    def _show_session_detail(self, jf) -> None:
        import json
        from pathlib import Path
        try:
            lines = jf.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            self._chat_log.add_message(f"読込エラー: {e}", role="system") if self._chat_log else None
            return

        entries = [json.loads(l) for l in lines if l.strip()]
        out = [f"📋 セッション詳細  {jf.stem}\n"]
        turn = 0
        for e in entries:
            t = e.get("type", "")
            if t == "user_input":
                turn += 1
                out.append(f"── Turn {turn} ({e.get('ts', '')}) ──")
                out.append(f"User: {e.get('content', '')[:200]}")
            elif t == "tool_call":
                out.append(f"  🔧 {e.get('tool', '?')}: {str(e.get('content', ''))[:100]}")
            elif t == "final_answer":
                out.append(f"  🤖 {e.get('content', '')[:300]}")
        self._chat_log.add_message("\n".join(out), role="system") if self._chat_log else None

    def _cmd_search(self, args: str) -> None:
        if not args:
            self._chat_log.add_message("使い方: /search <検索ワード>", role="system") if self._chat_log else None
            return
        from pathlib import Path
        import json
        sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
        jsonl_files = sorted(sessions_dir.glob("*.jsonl"), reverse=True) if sessions_dir.exists() else []
        q = args.lower()
        hits = []
        for jf in jsonl_files:
            try:
                lines = jf.read_text(encoding="utf-8").splitlines()
                entries = [json.loads(l) for l in lines if l.strip()]
            except Exception:
                continue
            for i, e in enumerate(entries):
                if e.get("type") == "user_input":
                    user_text = e.get("content", "")
                    answer_text = ""
                    for j in range(i + 1, len(entries)):
                        if entries[j].get("type") == "final_answer":
                            answer_text = entries[j].get("content", "")
                            break
                    if q in user_text.lower() or q in answer_text.lower():
                        hits.append((jf.stem, user_text[:100], answer_text[:150]))
                        break
            if len(hits) >= 5:
                break
        if not hits:
            self._chat_log.add_message(f"「{args}」に一致するログは見つかりませんでした。", role="system") if self._chat_log else None
            return
        out = [f"🔍 「{args}」— {len(hits)}件ヒット\n"]
        for i, (fname, user, answer) in enumerate(hits, 1):
            out.append(f"  [{i}] {fname}")
            out.append(f"      User: {user}")
            if answer:
                out.append(f"      Result: {answer}")
        self._chat_log.add_message("\n".join(out), role="system") if self._chat_log else None

    def _cmd_undo(self) -> None:
        if self._agent is None:
            self._chat_log.add_message("エージェントが初期化されていません。", role="system") if self._chat_log else None
            return
        conv = self._agent.conversation
        # 最後の assistant + user ターンを削除
        removed = 0
        while conv and conv[-1].get("role") in ("assistant", "tool"):
            conv.pop()
            removed += 1
        if conv and conv[-1].get("role") == "user":
            conv.pop()
            removed += 1
        self._chat_log.add_message(f"直前ターンを undo しまさした（{removed}メッセージ削除）。", role="system") if self._chat_log else None

    def _cmd_scratchpad(self) -> None:
        from .utils import get_scratchpad
        content = get_scratchpad()
        self._chat_log.add_message(f"📝 Scratchpad:\n{content}", role="system") if self._chat_log else None


if __name__ == "__main__":
    app = MimicApp()
    app.run()
