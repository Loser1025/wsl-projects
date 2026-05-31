"""mimic4 エントリポイント — python -m mimic4 で起動。"""
from __future__ import annotations
import os
import sys
import signal
import logging
from pathlib import Path


def main():
    # UTF-8 を保証
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    from .utils import safe_print, C, set_log_sink
    from .commands import register_search_command, register_sessions_command
    from .tools import set_sessions_dir, tools as _base_tools
    from . import config as _cfg
    from .config import load_config
    from .agent import OpenRouterAgent, AccountRotator
    from .autogit import AutoGit
    from .orchestrator import (InteractiveOrchestrator, AgentOrchestrator,
                                BASH_EXECUTOR_GUIDANCE, REACT_SYSTEM_PROMPT)
    from .main import pipe_mode, auto_mode
    from .monitoring import MonitoringToolRegistry, ToolCallLog
    from datetime import datetime as _dt

    # stdout への StreamHandler を除去（TUI が stdout を管理するため）
    logging.getLogger("openrouter_agent").handlers = [
        h for h in logging.getLogger("openrouter_agent").handlers
        if not isinstance(h, logging.StreamHandler)
        or isinstance(h, logging.FileHandler)]

    base_dir = str(Path(__file__).parent)
    or_config, gemini_config, mistral_config, system_prompt = load_config(base_dir)
    active_config = or_config or gemini_config or mistral_config

    _args       = sys.argv[1:]
    _args_clean = [a for a in _args if a not in ("--tmux",)]
    is_pipe     = any(a in _args_clean for a in ("--prompt", "--auto-prompt", "--status"))

    # ── MonitoringToolRegistry ──────────────────────────────────────
    tool_log = ToolCallLog()

    def _inline_display(record):
        icon  = C.green("✓") if record.status == "ok" else C.red("✗")
        time_ = C.gray(f"{record.elapsed:.2f}s")
        cpu   = C.gray(f"CPU:max{record.cpu_max_pct:.0f}%")
        mem   = C.gray(f"MEM:{record.rss_delta_mb:+.0f}MB")
        safe_print(f"  {icon} {C.gray(record.tool)} {time_} | {cpu} | {mem}", flush=True)

    mon_tools = MonitoringToolRegistry(
        base       = _base_tools,
        log        = tool_log,
        display_fn = _inline_display,
    )

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    plan_prompt  = (system_prompt or "") + BASH_EXECUTOR_GUIDANCE
    react_prompt = plan_prompt + REACT_SYSTEM_PROMPT

    # ── セッションログ用ディレクトリ（モード共通） ─────────────────
    sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    register_search_command(lambda: sessions_dir)
    register_sessions_command(lambda: sessions_dir)
    set_sessions_dir(sessions_dir)

    # /stats コマンド登録
    from .commands import cmd_registry
    @cmd_registry.register("stats", "ツール呼び出し統計を表示")
    def _cmd_stats(agent_obj, args: str):
        safe_print(f"\n  {C.bold_green('📊')} {C.white('ツール呼び出し統計')}\n")
        safe_print(tool_log.stats_text())
        safe_print(f"\n  {C.green('直近の呼び出し:')}")
        safe_print(tool_log.recent_text(10))
        safe_print()

    # ── オーケストレーター生成ファクトリ ───────────────────────────
    def _make_orch(sel_config):
        """選択されたconfig からエージェント一式を組み立てる。"""
        rotator      = AccountRotator(sel_config)
        agent        = OpenRouterAgent(rotator, mon_tools)
        orchestrator = AgentOrchestrator(rotator, mon_tools, executor=agent)
        auto_git     = AutoGit()

        mimic_cwd = os.environ.get("MIMIC_CWD")
        if mimic_cwd and Path(mimic_cwd).exists():
            agent.cwd = str(Path(mimic_cwd).resolve())
        elif _cfg._DEFAULT_CWD and Path(_cfg._DEFAULT_CWD).exists():
            agent.cwd = str(Path(_cfg._DEFAULT_CWD).resolve())

        agent.set_system_prompt(react_prompt)
        orchestrator.set_executor_system_prompt(plan_prompt)
        interactive_orch = InteractiveOrchestrator(agent, auto_git)

        _jsonl_path = sessions_dir / f"{_dt.now().strftime('%Y-%m-%d_%H-%M')}.jsonl"
        interactive_orch.react_log.set_jsonl_path(_jsonl_path)
        interactive_orch.react_log.add(
            "session_start",
            model    = sel_config.model,
            provider = sel_config.name,
            cwd      = agent.cwd,
        )
        set_log_sink(lambda level, msg:
            interactive_orch.react_log.add("system_event", level=level, content=msg))

        return interactive_orch, sel_config.name, sel_config.model, agent.cwd

    # ── モード分岐 ─────────────────────────────────────────────────
    args = _args_clean
    if "--prompt" in args:
        # パイプモード: デフォルト config でそのまま実行
        orch, _, _, _ = _make_orch(active_config)
        rotator = AccountRotator(active_config)
        agent   = OpenRouterAgent(rotator, mon_tools)
        idx = args.index("--prompt")
        pipe_mode(agent, args[idx + 1]) if idx + 1 < len(args) else sys.exit(1)

    elif "--auto-prompt" in args:
        orch, _, _, _ = _make_orch(active_config)
        rotator      = AccountRotator(active_config)
        agent        = OpenRouterAgent(rotator, mon_tools)
        orchestrator = AgentOrchestrator(rotator, mon_tools, executor=agent)
        interactive_orch = InteractiveOrchestrator(agent, AutoGit())
        agent.set_system_prompt(react_prompt)
        orchestrator.set_executor_system_prompt(plan_prompt)
        idx = args.index("--auto-prompt")
        auto_mode(interactive_orch, args[idx + 1], orchestrator) if idx + 1 < len(args) else sys.exit(1)

    elif "--status" in args:
        print(f"  プロバイダー: {active_config.name}")
        print(f"  モデル: {active_config.model}")
        print(f"  APIキー: {len(active_config.api_keys)} 個")
        sys.exit(0)

    else:
        # ── Textual TUI 起動（モデル選択画面から）────────────────
        from .tui import MimicApp
        app = MimicApp(
            or_config      = or_config,
            gemini_config  = gemini_config,
            mistral_config = mistral_config,
            orch_factory   = _make_orch,
        )
        app.run()


if __name__ == "__main__":
    main()
