"""team.py — Worker委任ループ。

delegate_to_team / delegate_to_worker / delegate_to_team_parallel から呼ばれる。

  1. Researcher（省略可）: フレッシュなエージェントが元のタスクを調査し、
     Worker向けの設計ワークフローを作成する。
  2. Worker: run_subagent_reviewable（OverlayFS隔離・サブプロセス）で実行し、
     差分サマリを返す。
  3. 変更を即時適用・AutoGitコミットしてDirectorに差分サマリを返す。
     Directorが結果を見て再委任するかどうかを判断する。
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Optional

from .agent import OpenRouterAgent, AccountRotator, _build_tool_call_entry
from .orchestrator import _parse_xml_tool_calls, _XML_TOOL_PATTERN, _MAX_XML_TOOL_RETRIES
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

_ISOLATED_MAX_ROUNDS = 8

_RESEARCHER_TOOLS = [
    "read_file", "read_tool_cache", "get_repo_map",
    "grep_codebase", "file_info", "smart_read",
    "web_search", "fetch_webpage",
]
_RESEARCHER_MAX_ROUNDS = 12


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
    xml_tool_retry_count = 0

    for _ in range(max_rounds):
        response = agent._api_call_with_retry(messages)
        text = agent._extract_text(response)
        tool_calls = agent._extract_tool_calls(response)
        if text:
            for line in text.splitlines():
                if line.strip():
                    safe_print(prefix + line, flush=True)

        # ── XML形式ツール呼び出し救済 ────────────────────────────
        if not tool_calls and text and _XML_TOOL_PATTERN.search(text):
            _xml_parsed = _parse_xml_tool_calls(text)
            if _xml_parsed:
                safe_print(C.yellow(
                    f"{prefix}⚠ XML形式ツール呼び出しを検知 → {len(_xml_parsed)}件をtool_callsとして実行"
                ), flush=True)
                tool_calls = _xml_parsed

        if not tool_calls:
            # XML検知したがパース失敗 → tool_calls形式で再送を促す
            if (text and _XML_TOOL_PATTERN.search(text)
                    and xml_tool_retry_count < _MAX_XML_TOOL_RETRIES):
                xml_tool_retry_count += 1
                safe_print(C.yellow(
                    f"{prefix}⚠ XMLツール呼び出しのパース失敗 → 修正を促します"
                    f" ({xml_tool_retry_count}/{_MAX_XML_TOOL_RETRIES})"
                ), flush=True)
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user",
                    "content": (
                        "[システム] ツール呼び出しがXML形式でテキストに含まれていましたが、"
                        "パースできませんでした。\n"
                        "ツールを呼び出す場合は、テキスト内に書かず、"
                        "APIのtool_calls機能（JSON形式）を使ってください。\n"
                        "直前のツール呼び出し意図をtool_calls形式で再送してください。"
                    ),
                })
                continue
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


def run_team_task(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "") -> str:
    """Researcher → Worker を1回実行し、変更を即時適用してサマリをDirectorに返す。"""
    resolved_dir = str(Path(project_dir).resolve())
    team_tag = f"[Team:{label}]" if label else "[Team]"
    trace_id = uuid.uuid4().hex[:8]

    safe_print(C.gray(f"  {team_tag} 🔍 Researcher調査中..."), flush=True)
    research = run_research(task, project_dir, config, label=label)
    _log_team_event({"event": "team_research_done", "task": task, "research": research[:2000], "trace_id": trace_id})

    worker_task = f"{task}\n\n[Researcherによる設計ワークフロー]\n{research}" if research else task

    safe_print(C.gray(f"  {team_tag} ⚙ Worker実行..."), flush=True)
    _log_team_event({"event": "team_worker_start", "attempt": 1, "task": task, "resumed": False, "trace_id": trace_id})
    result, upper, base = run_subagent_reviewable(
        worker_task, project_dir, label=label or "single",
        trace_id=trace_id, verify_cmd=verify_cmd,
        provider=config.name, model=config.model,
    )

    if upper is None or base is None:
        return f"[delegate_to_team: ⚠ 実行エラー]\nタスク: {task}\n\n{result.summary}"

    applied = False
    try:
        if result.changed_files:
            with _apply_lock:
                apply_subagent_changes(upper, Path(resolved_dir), result.changed_files)
                _get_team_autogit().checkpoint(resolved_dir, "delegate_to_team")
            applied = True
    finally:
        cleanup_subagent(base)

    status_label = "✓ 完了・適用済み" if applied else "✓ 完了（変更なし）"
    lines = [
        f"[delegate_to_team: {status_label}]",
        f"タスク: {task}",
        "",
        result.summary,
    ]
    if applied:
        lines += ["", "(変更はプロジェクトに適用され、AutoGitでコミット済みです)"]
    return "\n".join(lines)


def run_worker_once(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "") -> str:
    """Researcher/Supervisorを介さず、Workerを1回だけ実行して変更を即時適用する。"""
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
        return f"[delegate_to_worker: ⚠ 実行エラー]\n\n{result.summary}"

    applied = False
    try:
        if result.changed_files:
            with _apply_lock:
                apply_subagent_changes(upper, Path(resolved_dir), result.changed_files)
                _get_team_autogit().checkpoint(resolved_dir, "delegate_to_worker")
            applied = True
    finally:
        cleanup_subagent(base)

    status_label = "✓ 完了・適用済み" if applied else "✓ 完了（変更なし）"
    lines = [f"[delegate_to_worker: {status_label}]", "", result.summary]
    if applied:
        lines += ["", "(変更はプロジェクトに適用され、AutoGitでコミット済みです)"]
    return "\n".join(lines)


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
