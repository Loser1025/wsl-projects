"""mimic_claude エントリポイント — python -m mimic_claude で起動。"""
from __future__ import annotations
import os
import sys
import signal
import logging
from pathlib import Path


def _build_components(base_dir: str, active_config=None):
    """エージェント・オーケストレーター等の共通コンポーネントを初期化して返す。
    active_config を渡すと planner/reflector 含む全エージェントがそのモデルを使う。
    省略時は .env の最初の設定を使用する。
    """
    from .utils import safe_print, C, set_log_sink, set_team_event_sink, log
    from .commands import (register_search_command, register_sessions_command,
                            register_viewer_command, register_delegations_command)
    from .tools import set_sessions_dir, tools as _base_tools, ToolRegistry
    from . import config as _cfg
    from .config import load_config
    from .agent import OpenRouterAgent, AccountRotator
    from .autogit import AutoGit
    from .orchestrator import (InteractiveOrchestrator,
                                BASH_EXECUTOR_GUIDANCE, REACT_SYSTEM_PROMPT)
    from .monitoring import MonitoringToolRegistry, ToolCallLog

    logging.getLogger("openrouter_agent").handlers = [
        h for h in logging.getLogger("openrouter_agent").handlers
        if not isinstance(h, logging.StreamHandler)
        or isinstance(h, logging.FileHandler)]

    or_config, gemini_config, mistral_config, system_prompt = load_config(base_dir)
    # active_config が渡されていない場合のみ .env の先頭設定を使う
    if active_config is None:
        active_config = or_config or gemini_config or mistral_config

    from .team import set_team_config, set_team_autogit
    set_team_config(active_config)

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

    # Extreme React モード用: 書き込み系・シェル実行系・読み取り系のツールを
    # すべて取り上げ、調査は delegate_research、実装・修正・検証は
    # delegate_to_team / delegate_to_team_parallel に委任せざるを得ない構成にする
    # （フレッシュな文脈のResearcher/Worker/Supervisorが実際にファイルへ触れる）。
    # 残るのは delegate_research / delegate_to_team[_parallel] / update_scratchpad /
    # search_history（過去セッションの参照のみで、現プロジェクトのファイルには触れない）のみ。
    _EXTREME_EXCLUDED_TOOLS = {
        "write_file", "edit_file", "patch_file", "delete_file",
        "run_bash", "run_pipeline",
        "read_file", "grep_codebase", "file_info",
        "smart_read", "get_repo_map",
        "web_search", "fetch_webpage",
    }
    _extreme_registry = ToolRegistry()
    for _name in _base_tools._tools:
        if _name not in _EXTREME_EXCLUDED_TOOLS:
            _extreme_registry.copy_tool(_name, _base_tools)
    extreme_tools = MonitoringToolRegistry(
        base       = _extreme_registry,
        log        = tool_log,
        display_fn = _inline_display,
    )

    rotator      = AccountRotator(active_config)
    agent        = OpenRouterAgent(rotator, mon_tools)
    auto_git     = AutoGit()
    set_team_autogit(auto_git)

    def _on_sigterm(signum, frame):
        safe_print(C.yellow("\n  [SIGTERM] シャットダウンします..."), flush=True)
        sys.exit(0)
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    mimic_cwd = os.environ.get("MIMIC_CWD")
    if mimic_cwd and Path(mimic_cwd).exists():
        agent.cwd = str(Path(mimic_cwd).resolve())
    elif _cfg._DEFAULT_CWD and Path(_cfg._DEFAULT_CWD).exists():
        agent.cwd = str(Path(_cfg._DEFAULT_CWD).resolve())

    plan_prompt  = (system_prompt or "") + BASH_EXECUTOR_GUIDANCE
    react_prompt = plan_prompt + REACT_SYSTEM_PROMPT
    agent.set_system_prompt(react_prompt)
    interactive_orch = InteractiveOrchestrator(agent, auto_git)

    sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    from .utils import prune_old_sessions
    prune_old_sessions(sessions_dir, keep=200)
    from datetime import datetime as _dt
    _jsonl_path = sessions_dir / f"{_dt.now().strftime('%Y-%m-%d_%H-%M')}.jsonl"
    interactive_orch.react_log.set_jsonl_path(_jsonl_path)
    interactive_orch.react_log.add(
        "session_start",
        model    = active_config.model,
        provider = active_config.name,
        cwd      = agent.cwd,
    )
    set_log_sink(lambda level, msg:
        interactive_orch.react_log.add("system_event", level=level, content=msg))
    set_team_event_sink(lambda event:
        interactive_orch.react_log.add("system_event", level="info", content=str(event)))
    register_search_command(lambda: sessions_dir)
    register_sessions_command(lambda: sessions_dir)
    register_viewer_command(lambda: sessions_dir)
    register_delegations_command()
    set_sessions_dir(sessions_dir)

    # 中断委任マニフェストに長時間（24h超）残ったままのエントリがあれば起動時に知らせる。
    # base が既に消えているものは list_orphaned_delegations() 内で自動的に除去される。
    from datetime import datetime as _dt2
    from .team import list_orphaned_delegations as _list_orphaned
    _stale = []
    for e in _list_orphaned():
        try:
            started = _dt2.fromisoformat(e["started_at"])
            if (_dt2.now() - started).total_seconds() > 24 * 3600:
                _stale.append(e)
        except (KeyError, ValueError):
            pass
    if _stale:
        safe_print(C.yellow(
            f"  ⚠ 24時間以上更新のない中断委任タスクが{len(_stale)}件あります。"
            " /delegations で確認・破棄してください。"))

    from .viewer import start_viewer_server as _start_viewer
    _viewer_url = _start_viewer(sessions_dir)

    from .commands import cmd_registry
    @cmd_registry.register("stats", "ツール呼び出し統計を表示")
    def _cmd_stats(agent_obj, args: str):
        safe_print(f"\n  {C.bold_green('📊')} {C.white('ツール呼び出し統計')}\n")
        safe_print(tool_log.stats_text())
        safe_print(f"\n  {C.green('直近の呼び出し:')}")
        safe_print(tool_log.recent_text(10))
        safe_print()

    return dict(
        active_config    = active_config,
        agent            = agent,
        interactive_orch = interactive_orch,
        auto_git         = auto_git,
        tool_log         = tool_log,
        mon_tools        = mon_tools,
        extreme_tools    = extreme_tools,
        react_prompt     = react_prompt,
        plan_prompt      = plan_prompt,
        sessions_dir     = sessions_dir,
        viewer_url       = _viewer_url,
    )


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:]

    base_dir = str(Path(__file__).parent)

    # ── 非対話モード（モデル選択不要） ──────────────────────────────
    if "--prompt" in args:
        from .config import load_config
        from .agent import OpenRouterAgent, AccountRotator
        from .tools import tools as _base_tools
        from .monitoring import MonitoringToolRegistry, ToolCallLog
        from .main import pipe_mode

        or_config, gemini_config, mistral_config, _ = load_config(base_dir)
        active_config = or_config or gemini_config or mistral_config
        mon_tools = MonitoringToolRegistry(base=_base_tools, log=ToolCallLog())
        agent = OpenRouterAgent(AccountRotator(active_config), mon_tools)
        idx = args.index("--prompt")
        pipe_mode(agent, args[idx + 1]) if idx + 1 < len(args) else sys.exit(1)
        return

    if "--auto-prompt" in args:
        from .config import load_config
        from .agent import OpenRouterAgent, AccountRotator
        from .autogit import AutoGit, NullAutoGit
        from .tools import tools as _base_tools
        from .monitoring import MonitoringToolRegistry, ToolCallLog
        from .orchestrator import InteractiveOrchestrator, BASH_EXECUTOR_GUIDANCE, REACT_SYSTEM_PROMPT, WORKER_COMPLETION_GUIDANCE
        from .main import auto_mode
        from .utils import set_log_sink, set_team_event_sink

        or_config, gemini_config, mistral_config, system_prompt = load_config(base_dir)
        active_config = or_config or gemini_config or mistral_config

        # Worker（delegate_to_team経由）には、起動時に MIMIC_PROVIDER/MIMIC_MODEL で
        # Directorが選択中のプロバイダー・モデルが渡される。これを優先することで、
        # Workerが.envの先頭設定（デフォルトモデル）に固定されず、Directorと同じ
        # モデルで動作するようになる。
        _provider_map = {"openrouter": or_config, "gemini": gemini_config, "mistral": mistral_config}
        _wanted_provider = os.environ.get("MIMIC_PROVIDER")
        _wanted_model    = os.environ.get("MIMIC_MODEL")
        if _wanted_provider and _provider_map.get(_wanted_provider):
            active_config = _provider_map[_wanted_provider]
            if _wanted_model:
                active_config.model = _wanted_model

        from .team import set_team_config, set_team_autogit
        set_team_config(active_config)
        # auto_gitはNullAutoGit（MIMIC_NO_AUTOGIT=1の場合）またはAutoGit()。
        # NullAutoGitの場合もset_team_autogitで渡し、team.pyのcheckpointをno-opにする。
        # Worker（delegate_to_team経由のサブエージェント、MIMIC_NO_AUTOGIT=1で起動）には
        # delegate_to_team[_parallel]/delegate_researchを与えない。与えると、Workerが
        # さらに自分のWorkerを再帰的に委任し続け、サブエージェントが無限増殖してしまう。
        if os.environ.get("MIMIC_NO_AUTOGIT"):
            from .tools import ToolRegistry
            _DELEGATE_TOOLS = {"delegate_to_team", "delegate_to_team_parallel", "delegate_to_worker", "delegate_research"}
            _worker_registry = ToolRegistry()
            for _name in _base_tools._tools:
                if _name not in _DELEGATE_TOOLS:
                    _worker_registry.copy_tool(_name, _base_tools)
            _agent_tools = _worker_registry
        else:
            _agent_tools = _base_tools

        mon_tools = MonitoringToolRegistry(base=_agent_tools, log=ToolCallLog())
        rotator   = AccountRotator(active_config)
        agent     = OpenRouterAgent(rotator, mon_tools)
        plan_prompt  = (system_prompt or "") + BASH_EXECUTOR_GUIDANCE
        react_prompt = plan_prompt + REACT_SYSTEM_PROMPT
        if os.environ.get("MIMIC_NO_AUTOGIT"):
            react_prompt += WORKER_COMPLETION_GUIDANCE
        agent.set_system_prompt(react_prompt)
        # サブエージェント（delegate_to_subagent）として起動された場合は Git に触れない
        auto_git = NullAutoGit() if os.environ.get("MIMIC_NO_AUTOGIT") else AutoGit()
        set_team_autogit(auto_git)
        interactive_orch = InteractiveOrchestrator(agent, auto_git)

        trace_id = os.environ.get("MIMIC_TRACE_ID")
        if trace_id:
            sessions_dir = Path(__file__).parent / ".mimic" / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime as _dt
            _jsonl_path = sessions_dir / f"{_dt.now().strftime('%Y-%m-%d_%H-%M')}.jsonl"
            interactive_orch.react_log.set_jsonl_path(_jsonl_path)
            interactive_orch.react_log.add(
                "session_start",
                model    = active_config.model,
                provider = active_config.name,
                cwd      = agent.cwd,
                trace_id = trace_id,
            )
            # ネストしたdelegate_to_team[_parallel]が発行するteam_*イベントを
            # このサブエージェント自身のjsonlにも記録し、ビューアで孫世代の
            # セッションまでtrace_idで紐付けられるようにする。
            set_log_sink(lambda level, msg:
                interactive_orch.react_log.add("system_event", level=level, content=msg))
            set_team_event_sink(lambda event:
                interactive_orch.react_log.add("system_event", level="info", content=str(event)))

        idx = args.index("--auto-prompt")
        auto_mode(interactive_orch, args[idx + 1]) if idx + 1 < len(args) else sys.exit(1)
        return

    if "--status" in args:
        from .config import load_config
        or_config, gemini_config, mistral_config, _ = load_config(base_dir)
        cfg = or_config or gemini_config or mistral_config
        print(f"  プロバイダー: {cfg.name}")
        print(f"  モデル: {cfg.model}")
        print(f"  APIキー: {len(cfg.api_keys)} 個")
        sys.exit(0)
        return

    # ── 対話モード: モデル選択 → TUI 起動 ───────────────────────────
    from .config import load_config, select_model_interactively_multi
    or_config, gemini_config, mistral_config, _ = load_config(base_dir)
    active_config = select_model_interactively_multi(or_config, gemini_config, mistral_config)

    # 選択した config を _build_components に渡す
    # → rotator を active_config で作るので planner/reflector も同じモデルを使う
    ctx = _build_components(base_dir, active_config=active_config)

    from .app import MimicApp
    app = MimicApp(ctx)
    app.run(mouse=False)


if __name__ == "__main__":
    main()
