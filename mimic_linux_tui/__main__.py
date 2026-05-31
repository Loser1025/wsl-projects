"""mimic_linux_tui エントリポイント — python -m mimic_linux_tui で起動。"""
from __future__ import annotations
import os
import sys
import signal
import logging
from pathlib import Path


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    from .config import load_config
    from .agent import OpenRouterAgent, AccountRotator
    from .tools import set_write_approval_handler
    from .autogit import AutoGit
    from .orchestrator import (
        InteractiveOrchestrator, AgentOrchestrator,
        BASH_EXECUTOR_GUIDANCE, REACT_SYSTEM_PROMPT,
    )
    from .monitoring import MonitoringToolRegistry, ToolCallLog
    from .tools import tools as _base_tools
    from .commands import register_search_command, register_sessions_command
    from .tools import set_sessions_dir

    logging.getLogger("openrouter_agent").handlers = [
        h for h in logging.getLogger("openrouter_agent").handlers
        if not isinstance(h, logging.StreamHandler)
        or isinstance(h, logging.FileHandler)
    ]

    base_dir = str(Path(__file__).parent)
    or_config, gemini_config, mistral_config, system_prompt = load_config(base_dir)

    # モデル選択: 最初に見つかった設定を使う（TUI モデル選択は Phase 5 で実装）
    active_config = or_config or gemini_config or mistral_config

    # MonitoringToolRegistry
    tool_log = ToolCallLog()
    mon_tools = MonitoringToolRegistry(
        base=_base_tools,
        log=tool_log,
        display_fn=None,  # TUI 側で表示するため display_fn は使わない
    )

    rotator = AccountRotator(active_config)
    agent = OpenRouterAgent(rotator, mon_tools)
    orchestrator = AgentOrchestrator(rotator, mon_tools, executor=agent)
    auto_git = AutoGit()
    interactive_orch = InteractiveOrchestrator(agent, auto_git)

    # SIGTERM グレースフルシャットダウン
    def _on_sigterm(signum, frame):
        sys.exit(0)
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    # CWD 設定
    from . import config as _cfg
    mimic_cwd = os.environ.get("MIMIC_CWD")
    if mimic_cwd and Path(mimic_cwd).exists():
        agent.cwd = str(Path(mimic_cwd).resolve())
    elif _cfg._DEFAULT_CWD and Path(_cfg._DEFAULT_CWD).exists():
        agent.cwd = str(Path(_cfg._DEFAULT_CWD).resolve())

    # システムプロンプト設定
    plan_prompt = (system_prompt or "") + BASH_EXECUTOR_GUIDANCE
    react_prompt = plan_prompt + REACT_SYSTEM_PROMPT
    agent.set_system_prompt(react_prompt)
    orchestrator.set_executor_system_prompt(plan_prompt)

    # セッションログ初期化
    sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime as _dt
    _jsonl_path = sessions_dir / f"{_dt.now().strftime('%Y-%m-%d_%H-%M')}.jsonl"
    interactive_orch.react_log.set_jsonl_path(_jsonl_path)
    interactive_orch.react_log.add(
        "session_start",
        model=active_config.model,
        provider=active_config.name,
        cwd=agent.cwd,
    )
    register_search_command(lambda: sessions_dir)
    register_sessions_command(lambda: sessions_dir)
    set_sessions_dir(sessions_dir)

    # TUI 起動
    from .app import MimicApp
    app = MimicApp(
        agent=agent,
        orchestrator=orchestrator,
        interactive_orch=interactive_orch,
        auto_git=auto_git,
        active_config=active_config,
        tool_log=tool_log,
        sessions_dir=sessions_dir,
        plan_prompt=plan_prompt,
        react_prompt=react_prompt,
    )
    app.run()


if __name__ == "__main__":
    main()
