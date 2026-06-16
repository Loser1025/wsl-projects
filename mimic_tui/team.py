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
import uuid
from pathlib import Path
from typing import Optional

from .agent import OpenRouterAgent, AccountRotator, _build_tool_call_entry
from .autogit import AutoGit
from .config import OpenRouterConfig, GoogleAIConfig, MistralConfig
from .subagent import (apply_subagent_changes, cleanup_subagent,
                        run_subagent_reviewable, SubagentResult)
from .tools import ToolRegistry, tools as _base_tools
from .utils import safe_print, C, log, emit_team_event


def _log_team_event(event: dict) -> None:
    """mimic.log への記録に加えて、ReactLog（観測ビューア用）にも転送する。"""
    log.info(event)
    emit_team_event(event)

_apply_lock = threading.Lock()

MAX_TEAM_RETRIES = 5
_ISOLATED_MAX_ROUNDS = 8

_SUPERVISOR_TOOLS = [
    "read_file", "read_tool_cache", "get_repo_map",
    "grep_codebase", "file_info", "smart_read",
]

_RESEARCHER_TOOLS = [
    "read_file", "read_tool_cache", "get_repo_map",
    "grep_codebase", "file_info", "smart_read",
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
- 「[Workerの変更ファイル置き場]」が渡されている場合、対象ファイルの最新状態は
  まずそこを確認すること。Workerの変更はこの時点ではまだ「[プロジェクト全体（変更前の
  参照用）]」側に反映されていないため、プロジェクト全体側だけを見て「変更されていない」
  と判定するのは誤り。変更ファイル置き場に対象ファイルが存在しない場合のみ、
  「そのファイルは変更されていない」という意味になる
- Workerの作業結果に「[検証コマンド実行結果]」が含まれている場合、終了コードが0以外で
  あれば原則として "retry" と判定し、feedbackの【修正】にその失敗内容（出力から読み取れる
  原因とファイル名・箇所）を具体的に書くこと。「[検証コマンド実行結果]」が無い場合は
  従来通り差分内容のみで判断する
- 必要であれば読み取り専用ツール（read_file, grep_codebase, file_info, smart_read, get_repo_map）で
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
- read_file, grep_codebase, file_info, smart_read, get_repo_map で
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


_COMPRESS_THRESHOLD = 3000  # この文字数を超えたResearcher出力は中間要約コールで圧縮する

_COMPRESS_SYSTEM_PROMPT = """\
あなたは技術テキスト圧縮役です。
渡されたテキストを3000文字以内に要約してください。
- コードサンプル・ファイルパス・変更手順を優先して保持する
- 重複・冗長な説明・前置きを省く
- 出力はMarkdownでよい。説明なしで要約本文だけを返すこと
"""


def _compress_for_context(text: str, config, label: str = "") -> str:
    """Researcher出力が長すぎる場合、中間要約コールで3000文字以内に圧縮する。"""
    if len(text) <= _COMPRESS_THRESHOLD:
        return text
    safe_print(C.gray(f"  [Team:{label}] ✂ Researcher出力圧縮中 ({len(text)}文字→3000文字以内)..."), flush=True)
    empty_reg = ToolRegistry()
    summary = _run_isolated(config, empty_reg, _COMPRESS_SYSTEM_PROMPT, text,
                             max_rounds=1, label=label, role="Compressor")
    if summary:
        safe_print(C.gray(f"  [Team:{label}] ✂ 圧縮完了 ({len(summary)}文字)"), flush=True)
        return summary
    return text[:_COMPRESS_THRESHOLD] + "\n…（要約圧縮）"


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
                    label: str = "", prev_raw: str = "", review_dir: Optional[Path] = None) -> dict:
    """Workerの結果をレビューし、{"status", "feedback", "raw"} を返す。

    `prev_raw` には前回のSupervisor呼び出しの生出力（あれば）を渡す。これにより
    今回のSupervisorは「前回何を指摘し、それが直っているか」を踏まえて判定できる。

    `review_dir` にはWorkerのoverlay upperdir（新規作成・変更ファイルのみを含む）を渡す。
    Workerの変更は"ok"判定が出るまでproject_dirには反映されないため、project_dirだけを
    読んでも変更前の状態しか見えず、Supervisorが「変更されていない」と誤判定して
    無限retryに陥る。review_dirを優先的に確認させることでこれを防ぐ。
    """
    registry = _build_readonly_registry()
    resolved_project = Path(project_dir).resolve()
    if review_dir is not None and review_dir != resolved_project:
        prompt = (
            f"[Workerの変更ファイル置き場] {review_dir}\n"
            f"（ここにはWorkerが新規作成・変更したファイルのみが、変更後の最終状態として置かれています。\n"
            f"対象ファイルが存在すればそれが最新版です。まずここを確認してください。\n"
            f"存在しないファイルは変更されていないという意味で、{resolved_project} 側の元の内容のままです。）\n\n"
            f"[プロジェクト全体（変更前の参照用）] {resolved_project}\n\n"
            f"[最終目的（元の指示）]\n{task}\n\n"
        )
    else:
        prompt = (
            f"[作業フォルダ] {resolved_project}\n\n"
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
- read_file, grep_codebase, file_info, smart_read, get_repo_map で
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


def _format_no_diff_result(task: str, last_result: SubagentResult, attempt: int) -> str:
    """ファイル変更が無いまま完了したタスク（読み取り調査・コマンド実行のみ等）の結果を整形する。

    Supervisorはファイル差分を前提に判定するため、差分が無いタスクに対しては
    機能しない（必ず「変更されていない」=未完了と判定し、retryを無駄に繰り返す）。
    変更が無くWorkerが完了報告(mark_task_done)済みの場合は、Supervisorを介さず
    Workerの最終回答をそのままDirectorに返す。
    """
    lines = [
        "[delegate_to_team: ✓ 完了（ファイル変更なし）]",
        f"タスク: {task}",
        f"試行回数: {attempt}/{MAX_TEAM_RETRIES}",
        "",
        "(コード変更を伴わないタスクと判断し、Supervisorのレビューを行わずWorkerの回答を"
        "そのまま返します)",
        "",
        last_result.raw_tail,
    ]
    return "\n".join(lines)


def run_team_task(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "") -> str:
    """Worker → Supervisor のレビュー付きループを最大 MAX_TEAM_RETRIES 回実行する。"""
    feedback = ""
    last_result: Optional[SubagentResult] = None
    verdict: dict = {}
    resolved_dir = str(Path(project_dir).resolve())
    team_tag = f"[Team:{label}]" if label else "[Team]"
    base: Optional[Path] = None
    upper: Optional[Path] = None
    prev_raw = ""
    trace_id = uuid.uuid4().hex[:8]

    safe_print(C.gray(f"  {team_tag} 🔍 Researcher調査中..."), flush=True)
    research = run_research(task, project_dir, config, label=label)
    research = _compress_for_context(research, config, label=label)
    _log_team_event({"event": "team_research_done", "task": task, "research": research[:2000], "trace_id": trace_id})

    for attempt in range(1, MAX_TEAM_RETRIES + 1):
        if feedback:
            worker_task = f"{task}\n\n[Supervisorからの指示（これまでの変更を保持したまま続きを行うこと）]\n{feedback}"
        elif research:
            worker_task = f"{task}\n\n[Researcherによる設計ワークフロー]\n{research}"
        else:
            worker_task = task

        safe_print(C.gray(f"  {team_tag} ⚙ Worker実行 (試行{attempt}/{MAX_TEAM_RETRIES})"), flush=True)
        _log_team_event({"event": "team_worker_start", "attempt": attempt, "task": task, "resumed": base is not None, "trace_id": trace_id})
        last_result, upper, base = run_subagent_reviewable(worker_task, project_dir, label=label or "single", base=base, trace_id=trace_id, verify_cmd=verify_cmd, provider=config.name, model=config.model)

        if not last_result.changed_files:
            if last_result.ok:
                # ファイル変更を伴わないタスク（読み取り調査・コマンド実行のみ等）が
                # 完了報告(mark_task_done)済み。Supervisorはdiff前提のため呼ばず、
                # Workerの回答をそのまま返す。
                safe_print(C.green(f"  {team_tag} ✓ 完了（ファイル変更なし、試行{attempt}/{MAX_TEAM_RETRIES}）"), flush=True)
                if base is not None:
                    cleanup_subagent(base)
                return _format_no_diff_result(task, last_result, attempt)

            # mark_task_done なしで終了 → Supervisorを介さず、同じoverlayから続行させる
            safe_print(C.yellow(f"  {team_tag} ⚠ 変更なし・未完了 (試行{attempt}/{MAX_TEAM_RETRIES}) — Supervisorを介さず続行"), flush=True)
            feedback = (
                "前回の試行ではファイルの変更が行われず、また完了報告（mark_task_done）も"
                "ありませんでした。タスクを完了させ、最後に必ずmark_task_doneを呼んでください。"
            )
            continue

        safe_print(C.gray(f"  {team_tag} 👁 Supervisorレビュー中..."), flush=True)
        verdict = run_supervisor(task, last_result, project_dir, config, label=label, prev_raw=prev_raw, review_dir=upper)
        prev_raw = verdict["raw"]
        _log_team_event({"event": "team_supervisor_verdict", "attempt": attempt,
                   "status": verdict["status"], "feedback": verdict["feedback"][:200],
                   "worker_ok": last_result.ok, "worker_raw_tail": last_result.raw_tail[-300:],
                   "trace_id": trace_id})

        if verdict["status"] == "ok":
            safe_print(C.green(f"  {team_tag} 👁 監視結果: ok (試行{attempt}/{MAX_TEAM_RETRIES})"), flush=True)
            applied = False
            if upper is not None and base is not None:
                try:
                    if last_result.changed_files:
                        with _apply_lock:
                            apply_subagent_changes(upper, Path(resolved_dir), last_result.changed_files)
                            _get_team_autogit().checkpoint(resolved_dir, "delegate_to_team")
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


def _format_worker_result(result: SubagentResult, applied: bool, done: bool, note: str = "") -> str:
    if done:
        status_label = "✓ 完了・適用済み" if applied else "✓ 完了（変更なし）"
    else:
        status_label = "⚠ 未完了・未適用（再委任、または delegate_to_team での再試行を検討してください）"
    lines = [
        f"[delegate_to_worker: {status_label}]",
        "",
        result.summary,
    ]
    if done and applied:
        lines.append("")
        lines.append("(変更はプロジェクトに適用され、AutoGitでコミット済みです)")
    if note:
        lines.append("")
        lines.append(note)
    return "\n".join(lines)


def run_worker_once(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "") -> str:
    """Researcher/Supervisorを介さず、Workerを1回だけ実行する単発委任。

    mark_task_done が呼ばれ（=result.ok）、かつ verify_cmd を指定した場合は
    その終了コードが0の場合のみ、変更をプロジェクトに適用・コミットする。
    それ以外は変更を適用せず、差分・検証結果をそのままDirectorに返す
    （Directorが再委任するか delegate_to_team にエスカレートするかを判断する）。
    """
    resolved_dir = str(Path(project_dir).resolve())
    trace_id = uuid.uuid4().hex[:8]

    _log_team_event({
        "event": "team_worker_start", "attempt": 1, "task": task,
        "resumed": False, "trace_id": trace_id, "mode": "single",
    })
    result, upper, base = run_subagent_reviewable(
        task, project_dir, label=label or "single", trace_id=trace_id,
        verify_cmd=verify_cmd, provider=config.name, model=config.model,
    )

    if upper is None or base is None:
        # タイムアウト・実行エラー（既に内部で破棄済み）
        return _format_worker_result(result, applied=False, done=False)

    note = ""
    if verify_cmd and result.verify_exit in (124, 125, 127):
        note = (
            f"[注意] verify_cmd自体が正常に実行できなかった可能性があります"
            f"（終了コード{result.verify_exit}）。verify_cmdの内容を確認してください。"
        )

    verify_ok = (not verify_cmd) or result.verify_exit == 0
    if result.ok and verify_ok:
        applied = False
        if result.changed_files:
            with _apply_lock:
                apply_subagent_changes(upper, Path(resolved_dir), result.changed_files)
                _get_team_autogit().checkpoint(resolved_dir, "delegate_to_worker")
            applied = True
        cleanup_subagent(base)
        return _format_worker_result(result, applied=applied, done=True)

    cleanup_subagent(base)
    return _format_worker_result(result, applied=False, done=False, note=note)


# 並列Worker/Researcher/Supervisorの出力はTUIで入り乱れるが、
# /viewer のセッションツリー（実行状況バッジ付き）で各タスクの進行状況を
# 個別に追えるため、同時実行数を3まで許可する。
_MAX_PARALLEL_TEAM_TASKS = 3


def run_team_tasks_parallel(tasks: list[str], project_dir: str, config, verify_cmd: str = "") -> list[str]:
    """複数タスクを独立した Worker→Supervisor ループとして実行する（同時実行数は_MAX_PARALLEL_TEAM_TASKS）。"""
    results: list[Optional[str]] = [None] * len(tasks)

    def _worker(i: int, t: str):
        results[i] = run_team_task(t, project_dir, config, label=f"#{i + 1}", verify_cmd=verify_cmd)

    threads = [threading.Thread(target=_worker, args=(i, t)) for i, t in enumerate(tasks)]
    for batch_start in range(0, len(threads), _MAX_PARALLEL_TEAM_TASKS):
        batch = threads[batch_start:batch_start + _MAX_PARALLEL_TEAM_TASKS]
        for th in batch:
            th.start()
        for th in batch:
            th.join()
    return results  # type: ignore[return-value]


# ── Director の AutoGit インスタンス共有 ──────────────────────────
# team.py が都度 AutoGit() を生成すると、Orchestrator の _checkpoints スタック
# に委任コミットが積まれず、/rollback やターン末スカッシュが機能しない。
# set_team_autogit() で Orchestrator の auto_git を共有し、checkpoint() を
# 同一インスタンスに向けることで不整合を解消する。

_team_autogit: Optional["AutoGit"] = None


def set_team_autogit(autogit) -> None:
    """Orchestratorが使用中のAutoGitインスタンスをteam.py内の委任チェックポイントと共有する。"""
    global _team_autogit
    _team_autogit = autogit


def _get_team_autogit() -> "AutoGit":
    """共有AutoGitインスタンスを返す。未設定なら新規インスタンスにフォールバック。"""
    return _team_autogit if _team_autogit is not None else AutoGit()


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
