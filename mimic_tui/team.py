"""team.py — Worker → Supervisor のレビュー付き委任ループ。

delegate_to_team / delegate_to_team_parallel から呼ばれる。

  1. Worker: run_subagent_reviewable（OverlayFS隔離・サブプロセス）で
     Director から渡された詳細指示を実行し、差分サマリ(SubagentResult)を返す
     （upperdir はまだ破棄しない）。
  2. Supervisor: 会話履歴を持たないフレッシュなエージェントが、元の指示と
     Workerの差分サマリを見て {"status": "ok"|"retry", "feedback": "..."} を返す。
  3. "ok" の場合: upperdir の変更をプロジェクトに適用し、AutoGit でコミットしてから
     upperdir を破棄する。
     "retry" の場合: upperdir を破棄し、feedback を付加した指示で Worker をやり直す
     （最大 MAX_TEAM_RETRIES 回）。

Director の会話履歴には最終的なサマリ文字列のみが返る。Director自身は書き込み系
ツールを持たない（Extreme Reactモード）想定で、ファイルへの反映とコミットは
このモジュールが行う。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional

from .agent import OpenRouterAgent, AccountRotator, _build_tool_call_entry
from .autogit import AutoGit
from .config import OpenRouterConfig, GoogleAIConfig, MistralConfig
from .subagent import (apply_subagent_changes, cleanup_subagent,
                        run_subagent_reviewable, SubagentResult)
from .tools import ToolRegistry, tools as _base_tools
from .utils import safe_print, C, log

_apply_lock = threading.Lock()

MAX_TEAM_RETRIES = 5
_ISOLATED_MAX_ROUNDS = 8

_SUPERVISOR_TOOLS = [
    "read_file", "read_tool_cache", "get_repo_map",
    "search_in_file", "grep_codebase", "file_info", "smart_read",
]

SUPERVISOR_SYSTEM_PROMPT = """\
あなたはコード変更の監視役（Supervisor）です。
Workerが実施した作業の差分サマリが、元の指示を満たしているかを判定してください。

# 判定基準
- 元の指示で要求された変更が実際に行われているか
- 明らかな副作用・壊れたコード・指示と無関係な変更が無いか
- 必要であれば読み取り専用ツール（read_file, search_in_file, grep_codebase, file_info, smart_read, get_repo_map）で
  プロジェクトの現状を確認してよい（書き込みは一切できない）

# 出力形式（必須）
最終回答は以下のJSON形式のみを1つ出力すること。説明文やMarkdownのコードブロックは付けない。
{"status": "ok", "feedback": ""}
または
{"status": "retry", "feedback": "Workerへの具体的なやり直し指示"}

- "ok": 指示を満たしている
- "retry": 不十分・問題あり。feedback には次にWorkerへ渡す具体的な修正指示を日本語で書くこと
"""


def _build_readonly_registry() -> ToolRegistry:
    """Supervisor用の読み取り専用ツールレジストリを構築する。"""
    reg = ToolRegistry()
    for name in _SUPERVISOR_TOOLS:
        reg.copy_tool(name, _base_tools)
    return reg


def _run_isolated(config, tool_registry: ToolRegistry, system_prompt: str,
                   user_message: str, max_rounds: int = _ISOLATED_MAX_ROUNDS,
                   label: str = "") -> str:
    """会話履歴・スクラッチパッドを持たないフレッシュなエージェントを1ターン実行し、最終回答テキストを返す。"""
    agent = OpenRouterAgent(AccountRotator(config), tool_registry)
    agent.set_system_prompt(system_prompt)
    messages: list[dict] = [{"role": "user", "content": user_message}]
    prefix = f"  {C.gray(f'[Supervisor:{label}]' if label else '[Supervisor]')} "

    for _ in range(max_rounds):
        response = agent._api_call_with_retry(messages)
        text = agent._extract_text(response)
        tool_calls = agent._extract_tool_calls(response)
        if text:
            for line in text.splitlines():
                if line.strip():
                    safe_print(prefix + line, flush=True)
        if not tool_calls:
            return text or ""
        messages.append({
            "role": "assistant",
            "content": text or None,
            "tool_calls": [_build_tool_call_entry(tc) for tc in tool_calls],
        })
        for tc in tool_calls:
            fn_name = tc.get("name", "?")
            fn_args = tc.get("args", {})
            safe_print(prefix + f"→ {fn_name}({str(fn_args)[:80]})", flush=True)
            result, call_id = agent._run_single_tool(tc)
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": str(result),
            })
    return ""


def run_supervisor(task: str, work_result: SubagentResult, project_dir: str, config,
                    label: str = "") -> dict:
    """Workerの結果をレビューし、{"status", "feedback", "raw"} を返す。"""
    registry = _build_readonly_registry()
    prompt = (
        f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
        f"[元の指示]\n{task}\n\n"
        f"[Workerの作業結果]\n{work_result.summary}\n"
    )
    raw = _run_isolated(config, registry, SUPERVISOR_SYSTEM_PROMPT, prompt, label=label)

    verdict: dict = {}
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            verdict = json.loads(m.group(0))
        except Exception:
            verdict = {}

    status = verdict.get("status") if verdict.get("status") in ("ok", "retry") else None
    if status is None:
        status = "ok" if work_result.ok else "retry"
    feedback = verdict.get("feedback", "") or ""
    return {"status": status, "feedback": feedback, "raw": raw}


def _format_team_result(task: str, last_result: SubagentResult,
                          verdict: dict, attempt: int, done: bool, applied: bool) -> str:
    if done:
        status_label = "✓ 完了・適用済み" if applied else "✓ 完了（変更なし）"
    else:
        status_label = f"⚠ 未解決（{MAX_TEAM_RETRIES}回試行・プロジェクトは未変更）"
    lines = [
        f"[delegate_to_team: {status_label}]",
        f"タスク: {task}",
        f"試行回数: {attempt}/{MAX_TEAM_RETRIES}",
        "",
        last_result.summary,
    ]
    if done and applied:
        lines.append("")
        lines.append("(変更はプロジェクトに適用され、AutoGitでコミット済みです)")
    if not done and verdict.get("feedback"):
        lines.append("")
        lines.append(f"[Supervisorの最終所見]\n{verdict['feedback']}")
    return "\n".join(lines)


def run_team_task(task: str, project_dir: str, config, label: str = "") -> str:
    """Worker → Supervisor のレビュー付きループを最大 MAX_TEAM_RETRIES 回実行する。"""
    feedback = ""
    last_result: Optional[SubagentResult] = None
    verdict: dict = {}
    resolved_dir = str(Path(project_dir).resolve())
    team_tag = f"[Team:{label}]" if label else "[Team]"

    for attempt in range(1, MAX_TEAM_RETRIES + 1):
        worker_task = task
        if feedback:
            worker_task = f"{task}\n\n[前回のレビューによるやり直し指示]\n{feedback}"

        safe_print(C.gray(f"  {team_tag} ⚙ Worker実行 (試行{attempt}/{MAX_TEAM_RETRIES})"), flush=True)
        log.info({"event": "team_worker_start", "attempt": attempt, "task": task})
        last_result, upper, base = run_subagent_reviewable(worker_task, project_dir, label=label or "single")

        safe_print(C.gray(f"  {team_tag} 👁 Supervisorレビュー中..."), flush=True)
        verdict = run_supervisor(task, last_result, project_dir, config, label=label)
        log.info({"event": "team_supervisor_verdict", "attempt": attempt,
                   "status": verdict["status"], "feedback": verdict["feedback"][:200]})

        if verdict["status"] == "ok":
            safe_print(C.green(f"  {team_tag} 👁 監視結果: ok (試行{attempt}/{MAX_TEAM_RETRIES})"), flush=True)
            applied = False
            if upper is not None and base is not None:
                try:
                    if last_result.changed_files:
                        with _apply_lock:
                            apply_subagent_changes(upper, Path(resolved_dir), last_result.changed_files)
                            AutoGit().checkpoint(resolved_dir, "delegate_to_team")
                        applied = True
                finally:
                    cleanup_subagent(base)
            return _format_team_result(task, last_result, verdict, attempt, done=True, applied=applied)

        if base is not None:
            cleanup_subagent(base)

        preview = verdict["feedback"][:50].replace("\n", " ")
        safe_print(C.yellow(f"  {team_tag} 👁 監視結果: retry — {preview}"), flush=True)
        feedback = verdict["feedback"] or "監視役からのフィードバックが得られませんでした。再度確認してやり直してください。"

    return _format_team_result(task, last_result, verdict, MAX_TEAM_RETRIES, done=False, applied=False)


def run_team_tasks_parallel(tasks: list[str], project_dir: str, config) -> list[str]:
    """複数タスクを独立した Worker→Supervisor ループとして並列実行する。"""
    results: list[Optional[str]] = [None] * len(tasks)

    def _worker(i: int, t: str):
        results[i] = run_team_task(t, project_dir, config, label=f"#{i + 1}")

    threads = [threading.Thread(target=_worker, args=(i, t)) for i, t in enumerate(tasks)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return results  # type: ignore[return-value]


# ── アクティブモデル設定の共有 ────────────────────────────────────

_team_config: Optional["OpenRouterConfig | GoogleAIConfig | MistralConfig"] = None


def set_team_config(config) -> None:
    """Director が使用中の active_config を Worker/Supervisor 用に共有する。"""
    global _team_config
    _team_config = config


def _get_team_config():
    if _team_config is not None:
        return _team_config
    from .config import load_config
    or_c, gemini_c, mistral_c, _ = load_config(str(Path(__file__).parent))
    return or_c or gemini_c or mistral_c
