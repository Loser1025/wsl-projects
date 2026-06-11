"""team.py — Worker → Supervisor のレビュー付き委任ループ。

delegate_to_team / delegate_to_team_parallel から呼ばれる。

  1. Worker: run_subagent_reviewable（OverlayFS隔離・サブプロセス）で
     Director から渡された詳細指示を実行し、差分サマリ(SubagentResult)を返す
     （upperdir はまだ破棄しない）。
  2. Supervisor: 会話履歴を持たないフレッシュなエージェントが、元の指示と
     Workerの差分サマリを見て {"status": "ok"|"retry", "feedback": "..."} を返す。
     "retry" の feedback には「既存の変更の中で間違っている箇所とその直し方」と
     「まだ残っている作業」を分けて具体的に書くよう指示している。
  3. "ok" の場合: upperdir の変更をプロジェクトに適用し、AutoGit でコミットしてから
     upperdir を破棄する。
     "retry" の場合: upperdir はそのまま温存し、feedback を付加した指示で Worker を
     同じ upperdir 上から再実行する（ゼロからのやり直しではなく「壁打ち継続」、
     最大 MAX_TEAM_RETRIES 回）。最終的に "ok" にならず打ち切った場合のみ、
     最後に upperdir を破棄して未適用のまま終わる。

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

_RESEARCHER_TOOLS = [
    "read_file", "read_tool_cache", "get_repo_map",
    "search_in_file", "grep_codebase", "file_info", "smart_read",
    "web_search", "fetch_webpage",
]
_RESEARCHER_MAX_ROUNDS = 12

SUPERVISOR_SYSTEM_PROMPT = """\
あなたはコード変更の監視役（Supervisor）です。
Workerが「ここまでに行った作業」の差分サマリが、元の指示に対して正しいか・
完了しているかを判定してください。

重要: ここで "retry" と判定しても、Workerは最初からやり直すのではなく、
「今ある変更を保持したまま続きの作業」を行います。そのため、フィードバックは
「全部やり直して」のような曖昧な指示ではなく、以下の2点を明確に分けて
具体的に書いてください。

# 判定基準
- 元の指示で要求された変更が実際に行われ、完了しているか
- これまでの変更の中に、誤り・壊れたコード・指示と矛盾する内容・余計な副作用が無いか
  （read_file等の読み取り専用ツールでファイルの現状を確認し、該当ファイル名・箇所を
  具体的に特定すること）
- 必要であれば読み取り専用ツール（read_file, search_in_file, grep_codebase, file_info, smart_read, get_repo_map）で
  プロジェクトの現状を確認してよい（書き込みは一切できない）
- 「前回のSupervisor所見」が渡されている場合は、その指摘（特に【修正】）が今回の
  変更で実際に解消されているかを最優先で確認すること。解消されていなければ
  同じ指摘を繰り返すのではなく、なぜ直っていないのか・どう直すべきかをより
  具体的に書き直すこと

# 出力形式（必須）
最終回答は以下のJSON形式のみを1つ出力すること。説明文やMarkdownのコードブロックは付けない。
{"status": "ok", "feedback": ""}
または
{"status": "retry", "feedback": "..."}

- "ok": 指示を完全に満たしている
- "retry": 未完了または問題がある。feedback には次の2点を日本語で具体的に書くこと
  （該当しない方は省略してよい）。Workerは現在の変更内容を保持したまま、この
  feedbackに従って続きの作業を行う。
  1. 【修正】既存の変更の中に誤りがあれば、どのファイルのどの箇所が
     どう間違っているか、どう直すべきかを具体的に指摘する
  2. 【続き】まだ完了していない残りの作業があれば、何をどう続けて行うべきかを
     具体的に指示する
"""


RESEARCHER_SYSTEM_PROMPT = """\
あなたは調査役（Researcher）です。
Director（指示役）から渡された「元の指示」を実現するために必要な調査を行い、
その結果をもとに、Workerがそのまま着手できる具体的な設計ワークフローを作成してください。

# 調査
- read_file, search_in_file, grep_codebase, file_info, smart_read, get_repo_map で
  対象ファイル・関連コードの現状を確認する
- 必要であれば web_search / fetch_webpage で外部の仕様・ドキュメント・ライブラリの
  使い方などを調べる（書き込みは一切できない）

# 出力（最終回答）
最終回答は、調査結果の説明ではなく、Workerへの指示文としてそのまま使える
「設計ワークフロー」のテキストにすること。Markdownで構わない。最低限、以下を含めること:
- 対象ファイルの絶対パス
- 変更前の現状（関連する既存コードの抜粋・関数シグネチャなど）
- 実装手順（ステップごとに具体的に）
- 追加・変更後のコード例（できるだけ実際に貼り付けられる形で）
- 完了の判定基準（Supervisorが確認できる程度に具体的に）

元の指示の意図から外れた提案や、無関係な追加作業は書かないこと。
"""


def _build_readonly_registry() -> ToolRegistry:
    """Supervisor用の読み取り専用ツールレジストリを構築する。"""
    reg = ToolRegistry()
    for name in _SUPERVISOR_TOOLS:
        reg.copy_tool(name, _base_tools)
    return reg


def _build_researcher_registry() -> ToolRegistry:
    """Researcher用のツールレジストリ（読み取り専用＋Web検索）を構築する。"""
    reg = ToolRegistry()
    for name in _RESEARCHER_TOOLS:
        reg.copy_tool(name, _base_tools)
    return reg


def _run_isolated(config, tool_registry: ToolRegistry, system_prompt: str,
                   user_message: str, max_rounds: int = _ISOLATED_MAX_ROUNDS,
                   label: str = "", role: str = "Supervisor") -> str:
    """会話履歴・スクラッチパッドを持たないフレッシュなエージェントを1ターン実行し、最終回答テキストを返す。"""
    agent = OpenRouterAgent(AccountRotator(config), tool_registry)
    agent.set_system_prompt(system_prompt)
    messages: list[dict] = [{"role": "user", "content": user_message}]
    prefix = f"  {C.gray(f'[{role}:{label}]' if label else f'[{role}]')} "

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
                    label: str = "", prev_raw: str = "") -> dict:
    """Workerの結果をレビューし、{"status", "feedback", "raw"} を返す。

    `prev_raw` には前回のSupervisor呼び出しの生出力（あれば）を渡す。これにより
    今回のSupervisorは「前回何を指摘し、それが直っているか」を踏まえて判定できる。
    """
    registry = _build_readonly_registry()
    prompt = (
        f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
        f"[最終目的（元の指示）]\n{task}\n\n"
    )
    if prev_raw:
        prompt += f"[前回のSupervisor所見]\n{prev_raw}\n\n"
    prompt += f"[Workerの作業結果]\n{work_result.summary}\n"
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


RESEARCH_QA_SYSTEM_PROMPT = """\
あなたは調査役（Researcher）です。
Director（指示役）から渡された「調べてほしいこと」について必要な調査を行い、
その結果だけをユーザーへの回答として整理して返してください。

# 調査
- read_file, search_in_file, grep_codebase, file_info, smart_read, get_repo_map で
  プロジェクト内の関連情報を確認できる
- 必要であれば web_search / fetch_webpage で外部の仕様・公式ドキュメント等を調べる
  （書き込みは一切できない）

# 出力（最終回答）
- 「調べてほしいこと」に対する答えだけを、簡潔に日本語で書くこと。
  調査の過程・余談・関係ない情報は書かない。
- Markdownの区切り線（---）を多用しない。見出しは最小限にする。
- 情報源（URL等）があれば末尾に簡潔に添える。
"""


def run_research_qa(question: str, project_dir: str, config, label: str = "") -> str:
    """ユーザーからの調べ物依頼に対し、フレッシュな文脈で調査を行い回答だけを返す。"""
    registry = _build_researcher_registry()
    prompt = (
        f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
        f"[調べてほしいこと]\n{question}\n"
    )
    answer = _run_isolated(config, registry, RESEARCH_QA_SYSTEM_PROMPT, prompt,
                            max_rounds=_RESEARCHER_MAX_ROUNDS, label=label, role="Researcher")
    log.info({"event": "research_qa_done", "question": question, "answer": answer[:2000]})
    return answer


def run_research(task: str, project_dir: str, config, label: str = "") -> str:
    """元の指示をもとに調査を行い、Worker向けの設計ワークフローを返す。"""
    registry = _build_researcher_registry()
    prompt = (
        f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
        f"[元の指示]\n{task}\n"
    )
    return _run_isolated(config, registry, RESEARCHER_SYSTEM_PROMPT, prompt,
                          max_rounds=_RESEARCHER_MAX_ROUNDS, label=label, role="Researcher")


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
    base: Optional[Path] = None
    upper: Optional[Path] = None
    prev_raw = ""

    safe_print(C.gray(f"  {team_tag} 🔍 Researcher調査中..."), flush=True)
    research = run_research(task, project_dir, config, label=label)
    log.info({"event": "team_research_done", "task": task, "research": research[:2000]})

    for attempt in range(1, MAX_TEAM_RETRIES + 1):
        if feedback:
            worker_task = f"{task}\n\n[Supervisorからの指示（これまでの変更を保持したまま続きを行うこと）]\n{feedback}"
        elif research:
            worker_task = f"{task}\n\n[Researcherによる設計ワークフロー]\n{research}"
        else:
            worker_task = task

        safe_print(C.gray(f"  {team_tag} ⚙ Worker実行 (試行{attempt}/{MAX_TEAM_RETRIES})"), flush=True)
        log.info({"event": "team_worker_start", "attempt": attempt, "task": task, "resumed": base is not None})
        last_result, upper, base = run_subagent_reviewable(worker_task, project_dir, label=label or "single", base=base)

        safe_print(C.gray(f"  {team_tag} 👁 Supervisorレビュー中..."), flush=True)
        verdict = run_supervisor(task, last_result, project_dir, config, label=label, prev_raw=prev_raw)
        prev_raw = verdict["raw"]
        log.info({"event": "team_supervisor_verdict", "attempt": attempt,
                   "status": verdict["status"], "feedback": verdict["feedback"][:200],
                   "worker_ok": last_result.ok, "worker_raw_tail": last_result.raw_tail[-300:]})

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

        preview = verdict["feedback"][:50].replace("\n", " ")
        safe_print(C.yellow(f"  {team_tag} 👁 監視結果: retry — {preview}"), flush=True)
        feedback = verdict["feedback"] or "監視役からのフィードバックが得られませんでした。現在の変更内容を確認し、続きの作業を行ってください。"
        # upperdir はここでは破棄せず、次の試行で同じ内容から続きを行う

    if base is not None:
        cleanup_subagent(base)
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
