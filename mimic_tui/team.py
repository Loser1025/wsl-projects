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

import json
import tempfile
import threading
import time
import uuid
from datetime import datetime
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

MAX_VERIFY_RETRIES = 3   # verify失敗時のWorker自動再試行上限


# ── 中断委任マニフェスト ──────────────────────────────────────────
# Directorプロセス自体がクラッシュ/killされた場合、進行中の委任タスクの
# Overlay作業ディレクトリ（base）が孤立する。base をteam.py側で先に作って
# ここに登録しておき、正常完了時（finally節）に解除することで、
# 「マニフェストに残っている＝中断扱い」として後から検出・再開できる。

_INFLIGHT_LOCK = threading.Lock()


def _manifest_path() -> Path:
    p = Path(__file__).parent / ".mimic" / "inflight_delegations.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_manifest() -> dict:
    p = _manifest_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(data: dict) -> None:
    _manifest_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _register_inflight(trace_id: str, base: Path, project_dir: str, task: str,
                        label: str, verify_cmd: str, kind: str,
                        provider: str, model: str) -> None:
    with _INFLIGHT_LOCK:
        data = _load_manifest()
        data[trace_id] = {
            "base": str(base), "project_dir": project_dir, "task": task,
            "label": label, "verify_cmd": verify_cmd, "kind": kind,
            "provider": provider, "model": model,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_manifest(data)


def _unregister_inflight(trace_id: str) -> None:
    with _INFLIGHT_LOCK:
        data = _load_manifest()
        if data.pop(trace_id, None) is not None:
            _save_manifest(data)


def list_orphaned_delegations() -> list[dict]:
    """マニフェストのうち base が現存するエントリのみ返す（消えているものは自動で除去する）。

    各エントリに checkpoint_age_sec（merged/.mimic_checkpoint.json の最終更新からの
    経過秒数。短いほど「まだ実行中かもしれない」目安になる）を付与する。
    """
    with _INFLIGHT_LOCK:
        data = _load_manifest()
        alive: dict = {}
        pruned = False
        for tid, entry in data.items():
            if Path(entry["base"]).exists():
                alive[tid] = entry
            else:
                pruned = True
        if pruned:
            _save_manifest(alive)

    out = []
    for tid, entry in alive.items():
        e = dict(entry, trace_id=tid)
        cp = Path(entry["base"]) / "merged" / ".mimic_checkpoint.json"
        try:
            e["checkpoint_age_sec"] = time.time() - cp.stat().st_mtime
        except OSError:
            e["checkpoint_age_sec"] = None
        out.append(e)
    return out

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

# 検証コマンドの提案（任意）
今回の変更スコープに対応するテスト・ビルド・Lint コマンドを特定できた場合は、
最終回答の末尾に以下の形式で1行だけ記載すること（Directorが未指定の場合に自動採用される）:

[推奨verify_cmd] <コマンド>

例: pytest tests/test_auth.py -q  /  npm run test:unit  /  go test ./pkg/auth/...
- 今回の変更スコープに絞った最小限のコマンドにすること（フルスイートは避ける）
- 実行に数分以上かかるものは不適切
- 適切なコマンドが特定できない場合はこのセクションを省略してよい
"""






def _extract_suggested_verify_cmd(research: str) -> str:
    """Researcherのワークフロー出力から [推奨verify_cmd] を抽出する。"""
    import re
    m = re.search(r'\[推奨verify_cmd\]\s*[:`]?\s*(.+?)(?:\n|$)', research, re.IGNORECASE)
    if not m:
        return ""
    return m.group(1).strip().strip('`').strip()


def _build_verify_retry_task(original_task: str, verify_cmd: str, verify_exit: int,
                               verify_output: str, attempt: int) -> str:
    """verify失敗フィードバックを含む、Workerへの修正指示文を生成する。"""
    tail = verify_output[-3000:]
    if len(verify_output) > 3000:
        tail = f"…（出力省略、末尾3000文字のみ表示）\n{tail}"
    return (
        f"{original_task}\n\n"
        f"[検証失敗 — 修正してください（試行 {attempt}/{MAX_VERIFY_RETRIES}）]\n"
        f"検証コマンド: {verify_cmd}\n"
        f"終了コード: {verify_exit}\n"
        f"出力:\n{tail}\n\n"
        f"前回の変更内容はOverlay上に残っています。エラーを修正し、検証が通るようにしてください。"
    )


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


def _build_dynamic_system_prompt(role: str, can_write: bool) -> str:
    """Directorが自由記述したロール説明からシステムプロンプトを組み立てる。"""
    write_line = (
        "- write_file, edit_file, patch_file, run_bash でファイル変更・コマンド実行が可能\n"
        if can_write else ""
    )
    return (
        f"あなたは以下の専門家ロールで動作するエージェントです。\n\n"
        f"# ロール\n{role}\n\n"
        f"# 使えるツール\n"
        f"- read_file, grep_codebase, file_info, smart_read, get_repo_map でプロジェクト内を調査できる\n"
        f"- web_search / fetch_webpage で外部情報を調べられる\n"
        f"{write_line}"
        f"\n# 重要\nロールの専門性に集中し、範囲外の作業は行わない。"
        f"最終回答は日本語で簡潔に結果のみ伝える。"
    )


def run_specialist_task(role: str, task: str, project_dir: str, config,
                         can_write: bool = False, label: str = "") -> str:
    """動的ロール定義のエージェントを実行する。"""
    effective_label = label or role[:20]
    system_prompt = _build_dynamic_system_prompt(role, can_write)

    if can_write:
        enriched = f"[あなたのロール]\n{role}\n\n[タスク]\n{task}"
        return run_worker_once(enriched, project_dir, config, label=effective_label)
    else:
        registry = _build_researcher_registry()
        prompt = (
            f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
            f"[タスク]\n{task}\n"
        )
        return _run_isolated(
            config, registry, system_prompt, prompt,
            max_rounds=_RESEARCHER_MAX_ROUNDS,
            label=effective_label, role=role[:20],
        )


def run_research(task: str, project_dir: str, config, label: str = "") -> str:
    """元の指示をもとに調査を行い、Worker向けの設計ワークフローを返す。"""
    registry = _build_researcher_registry()
    prompt = (
        f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
        f"[元の指示]\n{task}\n"
    )
    return _run_isolated(config, registry, RESEARCHER_SYSTEM_PROMPT, prompt,
                          max_rounds=_RESEARCHER_MAX_ROUNDS, label=label, role="Researcher")


def _run_delegation_core(task: str, project_dir: str, config, base: Path, trace_id: str,
                          label: str, verify_cmd: str, tag: str, print_tag: str) -> str:
    """base 上でWorkerを実行し、verify失敗リトライ→適用→マニフェスト解除までを行う共通処理。

    新規実行（base は空のOverlay）・再開（base に前回までの変更が残っている）の
    どちらからも呼ばれる。呼び出し側は事前に base を作成し _register_inflight 済みであること。
    正常終了時（適用成功/不要/実行エラーでの打ち切りいずれも）は必ず _unregister_inflight する
    ため、ここに到達せずプロセスが落ちた場合だけがマニフェストに残り、中断扱いとして検出できる。
    """
    resolved_dir = str(Path(project_dir).resolve())

    safe_print(C.gray(f"  {print_tag} ⚙ Worker実行..."), flush=True)
    _log_team_event({"event": "team_worker_start", "attempt": 1, "task": task, "resumed": False, "trace_id": trace_id})
    result, upper, base = run_subagent_reviewable(
        task, project_dir, label=label or "single", base=base,
        trace_id=trace_id, verify_cmd=verify_cmd,
        provider=config.name, model=config.model,
    )

    # verify失敗ループ: 同じOverlay上でWorkerが修正再試行する
    for verify_attempt in range(1, MAX_VERIFY_RETRIES + 1):
        if result.verify_exit is None or result.verify_exit == 0:
            break  # 検証通過 or verify_cmd未指定
        if upper is None or base is None:
            break  # 直前のWorkerが実行エラー → リトライ不可
        if result.verify_exit in (2, 126, 127):
            # bash構文エラー(2) / 権限なし(126) / コマンド不明(127) はWorkerが修正できないためリトライ中止
            safe_print(C.yellow(
                f"  {print_tag} ⚠ verify_cmdが無効なコマンドです(exit={result.verify_exit}) → リトライ中止"
            ), flush=True)
            _log_team_event({
                "event": "verify_cmd_invalid", "verify_exit": result.verify_exit,
                "verify_cmd": verify_cmd, "trace_id": trace_id,
            })
            break
        safe_print(C.yellow(
            f"  {print_tag} ⚠ 検証失敗(exit={result.verify_exit})"
            f" → 修正再試行 {verify_attempt}/{MAX_VERIFY_RETRIES}"
        ), flush=True)
        _log_team_event({
            "event": "team_worker_start", "attempt": verify_attempt + 1,
            "task": task, "resumed": True, "trace_id": trace_id,
            "reason": "verify_failed", "verify_exit": result.verify_exit,
        })
        retry_task = _build_verify_retry_task(
            task, verify_cmd, result.verify_exit, result.verify_output, verify_attempt
        )
        new_result, new_upper, new_base = run_subagent_reviewable(
            retry_task, project_dir, label=label or "single",
            base=base,  # 前回のOverlayを引き継いで続きから作業
            trace_id=trace_id, verify_cmd=verify_cmd,
            provider=config.name, model=config.model,
        )
        if new_upper is None or new_base is None:
            # リトライ自体が失敗（baseも削除済み）→ 直前の結果で打ち切り
            safe_print(C.yellow(
                f"  {print_tag} ⚠ 修正試行 {verify_attempt} が失敗 → 前回の変更を適用します"
            ), flush=True)
            result = new_result
            upper = None
            base = None
            break
        result, upper, base = new_result, new_upper, new_base

    if upper is None or base is None:
        _unregister_inflight(trace_id)
        return f"[{tag}: ⚠ 実行エラー] (trace_id={trace_id})\nタスク: {task}\n\n{result.summary}"

    applied = False
    try:
        if result.changed_files:
            with _apply_lock:
                apply_subagent_changes(upper, Path(resolved_dir), result.changed_files)
                _get_team_autogit().checkpoint(resolved_dir, tag)
            applied = True
    finally:
        cleanup_subagent(base)
        _unregister_inflight(trace_id)

    verify_status = ""
    if verify_cmd:
        if result.verify_exit == 0:
            verify_status = " ✓検証通過"
        elif result.verify_exit is not None:
            verify_status = f" ✗検証失敗(exit={result.verify_exit}, {MAX_VERIFY_RETRIES}回試行後)"
        else:
            verify_status = " ?(検証結果取得失敗)"

    status_label = f"{'✓ 完了・適用済み' if applied else '✓ 完了（変更なし）'}{verify_status}"
    lines = [
        f"[{tag}: {status_label}] (trace_id={trace_id})",
        f"タスク: {task}",
        "",
        result.summary,
    ]
    if applied:
        lines += ["", "(変更はプロジェクトに適用され、AutoGitでコミット済みです)"]
    return "\n".join(lines)


def run_team_task(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "") -> str:
    """Researcher → Worker を実行し、verify失敗時は自動リトライ後に変更を適用してサマリを返す。"""
    resolved_dir = str(Path(project_dir).resolve())
    team_tag = f"[Team:{label}]" if label else "[Team]"
    trace_id = uuid.uuid4().hex[:8]

    safe_print(C.gray(f"  {team_tag} 🔍 Researcher調査中..."), flush=True)
    research = run_research(task, project_dir, config, label=label)
    _log_team_event({"event": "team_research_done", "task": task, "research": research[:2000], "trace_id": trace_id})

    # Directorがverify_cmdを指定していない場合、Researcherの提案を自動採用する
    if not verify_cmd:
        verify_cmd = _extract_suggested_verify_cmd(research)
        if verify_cmd:
            safe_print(C.gray(f"  {team_tag} 🧪 Researcher推奨verify_cmd: {verify_cmd}"), flush=True)

    worker_task = f"{task}\n\n[Researcherによる設計ワークフロー]\n{research}" if research else task

    # base をここで先に作って登録してから run_subagent_reviewable に渡す。
    # こうしないと、Worker実行中にDirectorプロセスが落ちた場合 base の存在をどこにも
    # 記録できず、Overlay作業ディレクトリが孤立したまま再開も破棄もできなくなる。
    base = Path(tempfile.mkdtemp(prefix=f"mimic_subagent_{label or 'single'}_"))
    _register_inflight(trace_id, base, resolved_dir, worker_task, label, verify_cmd,
                        "team", config.name, config.model)
    return _run_delegation_core(worker_task, project_dir, config, base, trace_id, label,
                                 verify_cmd, "delegate_to_team", team_tag)


def run_worker_once(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "") -> str:
    """Researcherを介さずWorkerを実行し、verify失敗時は自動リトライ後に変更を適用する。"""
    resolved_dir = str(Path(project_dir).resolve())
    trace_id = uuid.uuid4().hex[:8]

    base = Path(tempfile.mkdtemp(prefix=f"mimic_subagent_{label or 'single'}_"))
    _register_inflight(trace_id, base, resolved_dir, task, label, verify_cmd,
                        "worker", config.name, config.model)
    return _run_delegation_core(task, project_dir, config, base, trace_id, label,
                                 verify_cmd, "delegate_to_worker", "[Worker]")


def resume_delegation(trace_id: str) -> str:
    """中断された委任タスクを、保存済みOverlay(base)の続きから再開する。

    run_subagent_reviewable に既存baseを渡すことで、orchestrator.py側の既存の
    チェックポイント検知ロジック（.mimic_checkpoint.json があれば再開メッセージ付きで
    継続）がそのまま機能する。新規の再開ロジックはここでは作らない。
    """
    entry = _load_manifest().get(trace_id)
    if entry is None:
        return f"trace_id={trace_id} の中断タスクは見つかりませんでした。"
    base = Path(entry["base"])
    if not base.exists():
        _unregister_inflight(trace_id)
        return f"trace_id={trace_id} の作業ディレクトリが既に存在しないため再開できません（manifestから削除しました）。"

    config = _get_team_config()
    tag = "delegate_to_team" if entry.get("kind") == "team" else "delegate_to_worker"
    safe_print(C.gray(f"  [Resume] trace_id={trace_id} のタスクを再開します..."), flush=True)
    return _run_delegation_core(
        entry["task"], entry["project_dir"], config, base, trace_id,
        entry.get("label", ""), entry.get("verify_cmd", ""), tag, "[Resume]",
    )


def discard_delegation(trace_id: str) -> str:
    """中断された委任タスクを、変更を適用せずに破棄する。"""
    entry = _load_manifest().get(trace_id)
    if entry is None:
        return f"trace_id={trace_id} の中断タスクは見つかりませんでした。"
    cleanup_subagent(Path(entry["base"]))
    _unregister_inflight(trace_id)
    return f"trace_id={trace_id} の中断タスクを破棄しました（変更は適用されていません）。"


# 並列Worker/Researcher/Supervisorの出力はTUIで入り乱れるが、
# /viewer のセッションツリー（実行状況バッジ付き）で各タスクの進行状況を
# 個別に追えるため、同時実行数を3まで許可する。
_MAX_PARALLEL_TEAM_TASKS = 3


def run_team_tasks_parallel(tasks: list[str], project_dir: str, config, verify_cmd: str = "") -> list[str]:
    """複数タスクを独立した Worker→Supervisor ループとして実行する（同時実行数は_MAX_PARALLEL_TEAM_TASKS）。"""
    results: list[Optional[str]] = [None] * len(tasks)

    def _worker(i: int, t: str):
        try:
            results[i] = run_team_task(t, project_dir, config, label=f"#{i + 1}", verify_cmd=verify_cmd)
        except Exception as exc:
            results[i] = f"[delegate_to_team: ⚠ 予期しないエラー]\n{exc}"

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
