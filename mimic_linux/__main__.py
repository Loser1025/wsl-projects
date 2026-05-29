"""mimic_linux エントリポイント — python -m mimic_linux で起動。"""
from __future__ import annotations
import os
import sys
import signal
import logging
from pathlib import Path


def main():
    # Linux では UTF-8 がデフォルトだが念のため reconfigure で保証する
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    # readline: 履歴のみ有効化（Tab補完は tmux 内で端末制御が競合するため無効）
    try:
        import readline
        import atexit
        _hist = Path.home() / ".mimic_linux_history"
        if _hist.exists():
            readline.read_history_file(str(_hist))
        readline.set_history_length(500)
        atexit.register(readline.write_history_file, str(_hist))
        # parse_and_bind("tab: complete") は tmux 内で端末崩れを起こすため除去
    except ImportError:
        pass

    from .utils import safe_print, C, set_log_sink
    from .commands import register_search_command, register_sessions_command
    from .tools import set_sessions_dir, tools as _base_tools
    from . import config as _cfg
    from .config import load_config, select_model_interactively_multi
    from .agent import OpenRouterAgent, AccountRotator
    from .autogit import AutoGit
    from .orchestrator import (InteractiveOrchestrator, AgentOrchestrator,
                                BASH_EXECUTOR_GUIDANCE, REACT_SYSTEM_PROMPT)
    from .main import interactive_loop, pipe_mode, auto_mode
    from .monitoring import MonitoringToolRegistry, ToolCallLog

    logging.getLogger("openrouter_agent").handlers = [
        h for h in logging.getLogger("openrouter_agent").handlers
        if not isinstance(h, logging.StreamHandler)
        or isinstance(h, logging.FileHandler)]

    base_dir = str(Path(__file__).parent)
    or_config, gemini_config, system_prompt = load_config(base_dir)

    active_config = or_config or gemini_config

    _args = sys.argv[1:]
    use_tmux = "--tmux" in _args
    _args_clean = [a for a in _args if a != "--tmux"]

    # ── tmux チェックをモデル選択より先に実行 ────────────────────
    # tmux 外から --tmux で起動した場合は即座に tmux 内に入り直す。
    # relaunch_inside_tmux は sys.exit() するのでここで処理が終わる。
    if use_tmux:
        import shutil
        if shutil.which("tmux"):
            from .tmux_orch import inside_tmux, relaunch_inside_tmux
            if not inside_tmux():
                relaunch_inside_tmux("mimic")
                return  # 到達しない

    if not any(a in _args_clean for a in ("--prompt", "--auto-prompt", "--status")):
        active_config = select_model_interactively_multi(or_config, gemini_config)

    # ── MonitoringToolRegistry を構築 ────────────────────────────
    tool_log = ToolCallLog()

    def _inline_display(record):
        """ツール完了後にグレーでサマリを1行表示する。"""
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

    rotator      = AccountRotator(active_config)
    agent        = OpenRouterAgent(rotator, mon_tools)
    orchestrator = AgentOrchestrator(rotator, mon_tools, executor=agent)
    auto_git     = AutoGit()

    # SIGTERM でグレースフルシャットダウン
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
    orchestrator.set_executor_system_prompt(plan_prompt)
    interactive_orch = InteractiveOrchestrator(agent, auto_git)

    # ── セッションログ初期化 ──────────────────────────────────────
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
    )
    set_log_sink(lambda level, msg:
        interactive_orch.react_log.add("system_event", level=level, content=msg))
    register_search_command(lambda: sessions_dir)
    register_sessions_command(lambda: sessions_dir)
    set_sessions_dir(sessions_dir)

    # /stats コマンドを登録（tool_log を参照）
    from .commands import cmd_registry
    @cmd_registry.register("stats", "ツール呼び出し統計を表示")
    def _cmd_stats(agent_obj, args: str):
        safe_print(f"\n  {C.bold_green('📊')} {C.white('ツール呼び出し統計')}\n")
        safe_print(tool_log.stats_text())
        safe_print(f"\n  {C.green('直近の呼び出し:')}")
        safe_print(tool_log.recent_text(10))
        safe_print()

    safe_print(C.gray(f"  [{active_config.name}] モデル: {active_config.model}"))

    # ── tmux ダッシュボード起動（--tmux フラグ時のみ）────────────
    if use_tmux:
        _start_tmux_dashboard(
            tool_log, active_config, mon_tools,
            get_cwd     = lambda: agent.cwd,
            get_history = lambda: len(agent.conversation),
        )

    # ── モード分岐 ────────────────────────────────────────────────
    args = _args_clean
    if "--prompt" in args:
        idx = args.index("--prompt")
        pipe_mode(agent, args[idx + 1]) if idx + 1 < len(args) else sys.exit(1)
    elif "--auto-prompt" in args:
        idx = args.index("--auto-prompt")
        auto_mode(interactive_orch, args[idx + 1], orchestrator) if idx + 1 < len(args) else sys.exit(1)
    elif "--status" in args:
        safe_print(f"  プロバイダー: {active_config.name}")
        safe_print(f"  モデル: {active_config.model}")
        safe_print(f"  APIキー: {len(active_config.api_keys)} 個")
        sys.exit(0)
    else:
        interactive_loop(
            agent, orchestrator, interactive_orch, auto_git,
            react_prompt, plan_prompt,
            sessions_dir=sessions_dir,
        )


def _start_tmux_dashboard(tool_log, active_config, mon_registry=None,
                          get_cwd=None, get_history=None):
    """
    tmux ダッシュボードペインを起動する。

    tmux 内から起動した場合:
      現在のウィンドウを縦分割して下部に Monitor ペインを追加する。

    tmux 外から起動した場合:
      新しい tmux セッションを作り、その中で mimic を再起動して attach する。
      この場合は現在のプロセスを終了する（relaunch_inside_tmux が sys.exit する）。
    """
    import shutil
    from .utils import safe_print, C

    if not shutil.which("tmux"):
        safe_print(C.yellow("  ⚠ tmux が見つかりません。通常モードで起動します。"), flush=True)
        return

    from .tmux_orch import inside_tmux, relaunch_inside_tmux, TmuxSession
    from .monitor import MonitorDashboard
    from .proc_observer import SystemMonitor

    if not inside_tmux():
        # tmux 外から起動 → 新しいセッションに入り直す
        safe_print(C.green("  tmux セッションを起動してアタッチします..."), flush=True)
        relaunch_inside_tmux("mimic")  # この関数は return しない
        return  # 到達しない

    # tmux 内から起動 → 現在のウィンドウを分割
    try:
        session      = TmuxSession("mimic")
        monitor_pane = session.get_or_create_monitor_pane()
        sys_mon      = SystemMonitor()
        dashboard    = MonitorDashboard(
            monitor_pane, tool_log, sys_mon, active_config,
            mon_registry = mon_registry,
            get_cwd      = get_cwd,
            get_history  = get_history,
        )
        dashboard.start()
        safe_print(C.green("  ✓ Monitor ペインを起動しました"), flush=True)
    except Exception as e:
        safe_print(C.yellow(f"  ⚠ tmux ダッシュボード起動失敗: {e}"), flush=True)


if __name__ == "__main__":
    main()
