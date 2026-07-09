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

# 委任Worker（サブプロセス）の総同時実行数上限。delegate_to_team_parallel の
# バッチ制御(3)とは独立に、delegate_to_specialist 等が orchestrator の並列
# ツール実行経路で呼び出し数ぶん同時に走った場合も、全委任経路まとめて絞る。
_MAX_DELEGATION_CONCURRENCY = 3
_DELEGATION_SEMAPHORE = threading.BoundedSemaphore(_MAX_DELEGATION_CONCURRENCY)


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
                        provider: str, model: str,
                        role_prompt: str = "", apply_changes: bool = True) -> None:
    with _INFLIGHT_LOCK:
        data = _load_manifest()
        data[trace_id] = {
            "base": str(base), "project_dir": project_dir, "task": task,
            "label": label, "verify_cmd": verify_cmd, "kind": kind,
            "provider": provider, "model": model,
            "role_prompt": role_prompt, "apply_changes": apply_changes,
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

# ── 委任履歴リングバッファ（案2: ハーネスによるコンテキスト自動継承） ──
# Directorのscratchpad転記（プロンプト規約）に依存せず、直近の委任の要約を
# ハーネス側で記録し、次の委任タスクの冒頭へ自動注入する。
# 弱いDirectorモデルが経緯を転記し忘れても、Worker間の矛盾修正（前のWorkerの
# 変更を次のWorkerが打ち消す振動）を防げる。

_HISTORY_LOCK = threading.Lock()
_DELEGATION_HISTORY_KEEP = 5
_delegation_history: list[dict] = []


def _record_delegation(label: str, task: str, status: str,
                        changed_files: list[str] | None = None) -> None:
    """完了した委任の要約を履歴バッファへ記録する。"""
    with _HISTORY_LOCK:
        _delegation_history.append({
            "ts": datetime.now().strftime("%H:%M"),
            "label": label[:40],
            "task": " ".join(task.split())[:120],
            "status": status,
            "changed_files": list(changed_files or [])[:8],
        })
        del _delegation_history[:-_DELEGATION_HISTORY_KEEP]


def render_delegation_history() -> str:
    """直近の委任履歴を、委任タスク冒頭へ注入するテキストとして整形する。履歴がなければ空文字。"""
    with _HISTORY_LOCK:
        entries = list(_delegation_history)
    if not entries:
        return ""
    lines = ["[直近の委任履歴（ハーネス自動記録・あなた以前に行われた作業）]"]
    for e in entries:
        cf = f" 変更: {', '.join(e['changed_files'])}" if e["changed_files"] else ""
        lines.append(f"- {e['ts']} [{e['label']}] {e['status']}{cf}")
        lines.append(f"  依頼: {e['task']}")
    lines.append("※ 上記と矛盾する変更（直前の委任が行った変更を打ち消す等）を行う場合は、"
                 "その理由を最終回答に明記すること。")
    return "\n".join(lines) + "\n\n"


def clear_delegation_history() -> None:
    """委任履歴をリセットする（/clear やセッション開始時用）。"""
    with _HISTORY_LOCK:
        _delegation_history.clear()


# ── 反復失敗インターロック（案3: 連続書き込み委任の遮断） ──────────
# 「同じ問題に can_write 委任を盲目的に連発して振動する」失敗モードを機械的に断つ。
# 変更ファイルが重複する書き込み委任が連続 _WRITE_STREAK_LIMIT 回続いたら、
# 次の書き込み委任を拒否し、読み取り専用の診断委任を強制する。
# 読み取り専用委任が1回完了するとリセットされる。

_WRITE_STREAK_LIMIT = 3
_write_streak: list[set[str]] = []  # 直近の連続書き込み委任の変更ファイル集合


def _note_write_delegation(changed_files: list[str]) -> None:
    with _HISTORY_LOCK:
        _write_streak.append(set(changed_files))
        del _write_streak[:-(_WRITE_STREAK_LIMIT + 2)]


def _note_readonly_delegation() -> None:
    with _HISTORY_LOCK:
        _write_streak.clear()


def check_write_interlock() -> str:
    """書き込み委任を許可してよいか判定する。拒否する場合はエラー文字列を返す。

    直近 _WRITE_STREAK_LIMIT 回の書き込み委任の変更ファイルに重複があれば
    「同じ箇所を修正し続けて進展していない」とみなす。"""
    with _HISTORY_LOCK:
        recent = _write_streak[-_WRITE_STREAK_LIMIT:]
    if len(recent) < _WRITE_STREAK_LIMIT:
        return ""
    overlapping = any(
        recent[i] & recent[j]
        for i in range(len(recent)) for j in range(i + 1, len(recent))
        if recent[i] and recent[j]
    )
    if not overlapping:
        return ""
    files = sorted(set().union(*recent))[:10]
    return (
        f"[委任拒否: 反復失敗インターロック] 書き込み委任が連続{_WRITE_STREAK_LIMIT}回、"
        f"同じファイル群（{', '.join(files)}）を修正していますが問題が解決していません。\n"
        "同じアプローチの繰り返しを防ぐため、次の書き込み委任はブロックされました。\n"
        "先に **読み取り専用の委任（can_write=False, can_execute=False）** で対象ファイル全体を"
        "精査させ、根本原因の診断レポートを取得してください。"
        "その診断結果を踏まえた書き込み委任は再び許可されます。"
    )


def _sanitize_label_for_path(label: str) -> str:
    """label を tempfile.mkdtemp の prefix として安全な文字列に変換する。

    delegate_to_specialist の label はロール文字列の先頭から作られるため、
    'React/ランタイム競合解決専門家' のように `/` を含むと mkdtemp が
    [Errno 2] で即失敗する。パス区切りや空白類を `_` に置換して防ぐ。"""
    import re
    return re.sub(r"[/\\\s\x00]+", "_", label)


_ISOLATED_MAX_ROUNDS = 8

_RESEARCHER_TOOLS = [
    "read_file", "read_tool_cache", "get_repo_map",
    "grep_codebase", "file_info", "smart_read",
    "web_search", "fetch_webpage",
]
# 読み取り専用Specialist/Researcherにもブラウザ観測を許可する（案5）。
# 「デプロイ先の実ページを開いてコンソール相当の情報を観測する」委任を可能にし、
# 修正→デプロイ→確認のループをユーザーの手動コピペなしで閉じる。
# Playwright未導入環境ではツール自体がその旨を返すだけなので安全。
_RESEARCHER_BROWSER_TOOLS = [
    "enable_browser_tools", "disable_browser_tools",
    "browser_navigate", "browser_click", "browser_type",
    "browser_get_text", "browser_screenshot", "browser_close",
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
    """Researcher用のツールレジストリ（読み取り専用＋Web検索＋ブラウザ観測）を構築する。"""
    reg = ToolRegistry()
    for name in _RESEARCHER_TOOLS:
        reg.copy_tool(name, _base_tools)
    for name in _RESEARCHER_BROWSER_TOOLS:
        try:
            reg.copy_tool(name, _base_tools)
        except Exception:
            pass  # ブラウザツールが未登録の環境では黙ってスキップ
    return reg


def _run_isolated(config, tool_registry: ToolRegistry, system_prompt: str,
                   user_message: str, max_rounds: int = _ISOLATED_MAX_ROUNDS,
                   label: str = "", role: str = "Supervisor",
                   require_structured: bool = False) -> str:
    """会話履歴・スクラッチパッドを持たないフレッシュなエージェントを1ターン実行し、最終回答テキストを返す。

    require_structured=True の場合、最終回答に必須見出し（【結論】）が無ければ
    1回だけ形式の修正を機械的に再要求する（弱いモデルの自由作文で要点が欠落するのを防ぐ）。"""
    agent = OpenRouterAgent(AccountRotator(config), tool_registry)
    agent.set_system_prompt(system_prompt)
    messages: list[dict] = [{"role": "user", "content": user_message}]
    prefix = f"  {C.gray(f'[{role}:{label}]' if label else f'[{role}]')} "
    xml_tool_retry_count = 0
    structured_retry_done = False
    last_text = ""

    for _ in range(max_rounds):
        response = agent._api_call_with_retry(messages)
        text = agent._extract_text(response)
        tool_calls = agent._extract_tool_calls(response)
        if text:
            last_text = text
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
            # ── 構造化回答の機械チェック（欠落時は1回だけ再要求）────
            if (require_structured and text and "【結論】" not in text
                    and not structured_retry_done):
                structured_retry_done = True
                safe_print(C.yellow(
                    f"{prefix}⚠ 最終回答が指定形式でないため再要求します"
                ), flush=True)
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": (
                    "[システム] 最終回答が指定の形式ではありません。内容を変えずに、"
                    "【結論】【変更・実施内容】【残課題】【次の推奨】の4見出しで"
                    "整理し直して再送してください（該当なしの項目は「なし」と書く）。"
                )})
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

    # ラウンド上限到達 — 空文字ではなく「未完了」であることを呼び出し元（Director）に明示する。
    # 空文字を返すとDirectorが「失敗」と「発見なし」を区別できず誤った報告をし得る。
    note = f"[ラウンド上限到達・調査未完了] {max_rounds}ラウンド以内に最終回答に到達できませんでした。"
    partial = last_text.strip()
    if partial:
        return f"{note}\nここまでの最終出力（不完全な可能性あり）:\n{partial}"
    return note + " タスクを分割するか、より狭いロールで再委任してください。"



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


STRUCTURED_ANSWER_GUIDANCE = """
# 最終回答の形式（必須）
最終回答は必ず以下の4見出しで構成すること（該当なしの項目は「なし」と書く）:
【結論】タスクの結果を1〜3行で
【変更・実施内容】変更/実行したファイル・コマンドと内容
【残課題】未解決の問題・確認できなかったこと
【次の推奨】依頼元が次に行うべきこと
"""


def _build_dynamic_system_prompt(role: str, can_write: bool,
                                  can_execute: bool = False) -> str:
    """Directorが自由記述したロール説明からシステムプロンプトを組み立てる。

    ツール説明は実行経路ごとの実態に合わせる: can_write=True のWorkerは委任以外の
    全ツールを持つため個別列挙しない（過少申告を避ける）。"""
    if can_write:
        tools_desc = (
            "- ファイルの読み書き・シェル実行・検索・Web調査など、委任以外の全ツールが使える\n"
            "- 変更はOverlayFS隔離された作業部屋で行われ、タスク完了後にプロジェクトへ適用される\n"
        )
    elif can_execute:
        tools_desc = (
            "- ファイル読み取り・検索・Web調査に加え、run_bash / run_pipeline で"
            "コマンド（テスト・ビルド・診断等）を実行できる\n"
            "- **作業部屋はOverlayFS隔離されており、ファイルへの変更はタスク終了後に破棄される。**"
            "実行・診断・分析と、その結果の報告に集中すること（修正の実装は行わない）\n"
        )
    else:
        tools_desc = (
            "- read_file, grep_codebase, file_info, smart_read, get_repo_map でプロジェクト内を調査できる\n"
            "- web_search / fetch_webpage で外部情報を調べられる（書き込み・コマンド実行は不可）\n"
            "- browser_navigate / browser_get_text / browser_screenshot 等で実際のWebページ"
            "（デプロイ先のサイト等）を開いて観測できる（enable_browser_tools で有効化。"
            "Playwright未導入の環境では使用不可）\n"
        )
    return (
        f"あなたは以下の専門家ロールで動作するエージェントです。\n\n"
        f"# ロール\n{role}\n\n"
        f"# 使えるツール\n"
        f"{tools_desc}"
        f"\n# 重要\nロールの専門性に集中し、範囲外の作業は行わない。"
        f"最終回答は日本語で簡潔に結果のみ伝える。\n"
        f"{STRUCTURED_ANSWER_GUIDANCE}"
    )


# ── roleスキーマ検証（案4: 自由度の削減） ─────────────────────────
# 弱いDirectorモデルが「〜の専門家」だけの薄いroleを書くとSpecialistの精度が
# 大きく落ちる。形式チェックは機械でできるため、完了基準の明記をツール境界で
# 強制する（欠落時はテンプレ付きで即差し戻し。Workerは起動しないのでコストゼロ）。

_ROLE_MIN_CHARS = 20


def validate_specialist_role(role: str) -> str:
    """delegate_to_specialist の role を検証する。問題があればエラー文字列を返す。"""
    role = (role or "").strip()
    problems = []
    if len(role) < _ROLE_MIN_CHARS:
        problems.append(f"role が短すぎます（{len(role)}文字 < {_ROLE_MIN_CHARS}文字）")
    if "完了基準" not in role:
        problems.append("role に「完了基準」の明記がありません")
    if not problems:
        return ""
    return (
        "[委任拒否: role不備] " + " / ".join(problems) + "\n"
        "role は以下のテンプレートを埋めて再送してください（このチェックは機械的な文字列検査です）:\n"
        "  視点: <どの専門性・観点で作業するか>\n"
        "  制約: <やってはいけないこと・守るべき既存の流儀>\n"
        "  完了基準: <何が確認できたらタスク完了とみなすか（検証可能な形で）>"
    )


_VERIFY_SUGGEST_MAX_ROUNDS = 6

_VERIFY_SUGGEST_SYSTEM_PROMPT = """\
あなたは検証コマンドの提案役です。渡されたタスクの変更スコープに対応する
テスト・ビルド・Lint コマンドを1つだけ特定してください。
- プロジェクト内を読み取りツールで軽く確認してよい（package.json, pyproject.toml 等）
- 変更スコープに絞った最小限のコマンドにする（フルスイートは避ける）
- 実行に数分以上かかるものは不適切
- 適切なコマンドが特定できない場合は「なし」とだけ答える

最終回答は以下の1行のみ:
[推奨verify_cmd] <コマンド>
または
[推奨verify_cmd] なし
"""


def _suggest_verify_cmd(task: str, project_dir: str, config, label: str = "") -> str:
    """can_write委任でverify_cmd未指定のとき、軽量な読み取り専用パスで検証コマンドを自動調達する。
    特定できなければ空文字を返す（失敗しても委任は続行する）。"""
    try:
        registry = _build_researcher_registry()
        prompt = (
            f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
            f"[これから実施される変更タスク]\n{task[:2000]}\n"
        )
        answer = _run_isolated(config, registry, _VERIFY_SUGGEST_SYSTEM_PROMPT, prompt,
                                max_rounds=_VERIFY_SUGGEST_MAX_ROUNDS,
                                label=label, role="VerifySuggest")
        cmd = _extract_suggested_verify_cmd(answer)
        if cmd and cmd not in ("なし", "none", "None"):
            return cmd
    except Exception:
        pass
    return ""


def _rounds_for_specialist(role: str, task: str) -> int:
    """role/taskの記述量から読み取り専用Specialistのラウンド上限を段階的に決める。

    「コードベース全体のレビュー」のような広いタスクほど記述が長くなる傾向を利用した
    粗いヒューリスティック。"""
    size = len(role) + len(task)
    if size > 1200:
        return 24
    if size > 500:
        return 18
    return _RESEARCHER_MAX_ROUNDS


# ── Specialistロール定義の永続化 ──────────────────────────────────
# 成功した委任のロール定義を保存し、/mode specialist 切替時にシステムプロンプトへ
# 注入する。動的生成の柔軟性を保ちつつ、実績あるロール文の再利用で品質を安定させる。

_ROLES_KEEP = 30          # 保存するロール定義の上限（最終使用が古いものから削除）
_ROLES_INJECT_LIMIT = 10  # システムプロンプトに注入する件数


def _roles_dir() -> Path:
    p = Path(__file__).parent / ".mimic" / "roles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_specialist_role(role: str, mode: str) -> None:
    """成功した委任のロール定義を保存する（同一ロールは使用回数を加算）。失敗は無視。"""
    import hashlib
    try:
        slug = hashlib.md5(role.strip().encode()).hexdigest()[:10]
        p = _roles_dir() / f"{slug}.json"
        data: dict = {"role": role.strip(), "uses": 0}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        data["uses"] = int(data.get("uses", 0)) + 1
        data["mode"] = mode
        data["last_used"] = datetime.now().isoformat(timespec="seconds")
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        files = sorted(_roles_dir().glob("*.json"), key=lambda f: f.stat().st_mtime)
        for f in files[:-_ROLES_KEEP]:
            f.unlink(missing_ok=True)
    except Exception:
        pass


def load_saved_roles_section(limit: int = _ROLES_INJECT_LIMIT) -> str:
    """保存済みロール定義をSpecialistモードのシステムプロンプト追記用に整形して返す。
    保存済みロールがなければ空文字。"""
    try:
        files = sorted(_roles_dir().glob("*.json"),
                       key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    except Exception:
        return ""
    lines = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            role = str(data.get("role", "")).strip().replace("\n", " ")
            if role:
                lines.append(f"- {role[:180]}（使用{data.get('uses', 1)}回）")
        except Exception:
            continue
    if not lines:
        return ""
    return (
        "\n\n## 保存済みロール（過去に成功した委任のロール定義）\n"
        "類似タスクでは以下のロール定義をそのまま、または微修正して再利用すること:\n"
        + "\n".join(lines) + "\n"
    )


def run_specialist_task(role: str, task: str, project_dir: str, config,
                         can_write: bool = False, can_execute: bool = False,
                         label: str = "", verify_cmd: str = "",
                         expected_files: Optional[list[str]] = None) -> str:
    """動的ロール定義のエージェントを実行する。

    権限は3段階: 読み取り専用（デフォルト）/ can_execute=True（Overlay内で
    コマンド実行可・変更は破棄）/ can_write=True（Overlay内で実装し変更を適用・コミット）。
    can_write と can_execute が両方 True の場合は can_write が優先される。
    ロール定義は .mimic/roles/ に保存され再利用候補として注入されるが、
    書き込み/実行系は機械検証（verify）を通過した場合のみ「実績」として保存する。"""
    effective_label = label or role[:20]
    system_prompt = _build_dynamic_system_prompt(role, can_write, can_execute)

    if can_write or can_execute:
        # can_write で verify_cmd 未指定なら、軽量パスで検証コマンドを自動調達する。
        # 成功判定をWorkerの自己申告から機械検証へ寄せるための施策で、
        # 特定できなければ未検証のまま続行する（結果に「※未検証」ラベルが付く）。
        if can_write and not verify_cmd:
            verify_cmd = _suggest_verify_cmd(task, project_dir, config, label=effective_label)
            if verify_cmd:
                safe_print(C.gray(
                    f"  [{effective_label}] 🧪 自動調達したverify_cmd: {verify_cmd}"
                ), flush=True)

        enriched = f"[あなたのロール]\n{role}\n\n[タスク]\n{task}"
        result = run_worker_once(enriched, project_dir, config, label=effective_label,
                                  role_prompt=system_prompt, verify_cmd=verify_cmd,
                                  apply_changes=can_write,
                                  expected_files=expected_files)
        # ロール保存は機械検証を通過した委任のみ（自己申告の「完了」では保存しない）
        if "✓検証通過" in result:
            _save_specialist_role(role, "write" if can_write else "execute")
        return result
    else:
        registry = _build_researcher_registry()
        prompt = (
            f"[作業フォルダ] {Path(project_dir).resolve()}\n\n"
            f"{render_delegation_history()}"
            f"[タスク]\n{task}\n"
        )
        answer = _run_isolated(
            config, registry, system_prompt, prompt,
            max_rounds=_rounds_for_specialist(role, task),
            label=effective_label, role=role[:20],
            require_structured=True,
        )
        if answer and not answer.startswith("[ラウンド上限到達"):
            _save_specialist_role(role, "read")
            _record_delegation(effective_label, task, "✓ 調査完了（読み取り専用）")
            _note_readonly_delegation()
        else:
            _record_delegation(effective_label, task, "⚠ ラウンド上限・調査未完了")
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


def _run_delegation_core(task: str, project_dir: str, config, base: Path, trace_id: str,
                          label: str, verify_cmd: str, tag: str, print_tag: str,
                          role_prompt: str = "", apply_changes: bool = True,
                          expected_files: Optional[list[str]] = None) -> str:
    """_run_delegation_core_inner を同時実行数制限付きで実行する。

    delegate_to_specialist 等は orchestrator の並列ツール実行経路で呼び出し数ぶん
    同時に走り得るため、Workerサブプロセスの総同時実行数をここで絞る。
    """
    if not _DELEGATION_SEMAPHORE.acquire(blocking=False):
        safe_print(C.gray(
            f"  {print_tag} ⏳ 委任スロット待機中（同時実行上限 {_MAX_DELEGATION_CONCURRENCY}）..."
        ), flush=True)
        _DELEGATION_SEMAPHORE.acquire()
    try:
        return _run_delegation_core_inner(task, project_dir, config, base, trace_id,
                                           label, verify_cmd, tag, print_tag,
                                           role_prompt=role_prompt,
                                           apply_changes=apply_changes,
                                           expected_files=expected_files)
    finally:
        _DELEGATION_SEMAPHORE.release()


def _run_delegation_core_inner(task: str, project_dir: str, config, base: Path, trace_id: str,
                                label: str, verify_cmd: str, tag: str, print_tag: str,
                                role_prompt: str = "", apply_changes: bool = True,
                                expected_files: Optional[list[str]] = None) -> str:
    """base 上でWorkerを実行し、verify失敗リトライ→適用→マニフェスト解除までを行う共通処理。

    新規実行（base は空のOverlay）・再開（base に前回までの変更が残っている）の
    どちらからも呼ばれる。呼び出し側は事前に base を作成し _register_inflight 済みであること。
    正常終了時（適用成功/不要/実行エラーでの打ち切りいずれも）は必ず _unregister_inflight する
    ため、ここに到達せずプロセスが落ちた場合だけがマニフェストに残り、中断扱いとして検出できる。
    apply_changes=False（実行専用委任）の場合、Overlay内の変更は適用せず破棄する。
    """
    resolved_dir = str(Path(project_dir).resolve())
    _t_start = time.time()  # 競合検出用: この時刻以降に本体側で変更されたファイルを警告する

    # 委任履歴（直近の委任の要約）をハーネス側でタスク冒頭に自動注入する。
    # task 変数自体は汚さない（履歴記録・結果サマリには元のタスクを使う）。
    worker_task = render_delegation_history() + task

    safe_print(C.gray(f"  {print_tag} ⚙ Worker実行..."), flush=True)
    _log_team_event({"event": "team_worker_start", "attempt": 1, "task": task, "resumed": False, "trace_id": trace_id})
    result, upper, base = run_subagent_reviewable(
        worker_task, project_dir, label=label or "single", base=base,
        trace_id=trace_id, verify_cmd=verify_cmd,
        provider=config.name, model=config.model,
        role_prompt=role_prompt,
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
            role_prompt=role_prompt,
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
        _record_delegation(label or tag, task, "⚠ 実行エラー")
        return f"[{tag}: ⚠ 実行エラー] (trace_id={trace_id})\nタスク: {task}\n\n{result.summary}"

    applied = False
    discarded = False
    conflict_files: list[str] = []
    try:
        if result.changed_files and apply_changes:
            # 委任実行中に本体側でも変更されたファイルを検出する
            # （applyはlast-writer-winsで上書きするため、警告として差分サマリに載せる）
            for f in result.changed_files:
                dst = Path(resolved_dir) / f
                try:
                    if dst.exists() and dst.stat().st_mtime > _t_start:
                        conflict_files.append(f)
                except OSError:
                    pass
            with _apply_lock:
                apply_subagent_changes(upper, Path(resolved_dir), result.changed_files)
                _get_team_autogit().checkpoint(resolved_dir, tag)
            applied = True
        elif result.changed_files:
            discarded = True
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
    elif applied:
        # 検証なしの適用は「Workerの自己申告のみ」であることをハーネスが明示する。
        # 弱いDirectorモデルが「完了しました」とユーザーへ言い切るのを防ぐ。
        verify_status = " ※未検証（verify_cmd未指定・Workerの自己申告のみ）"

    if applied:
        status_core = "✓ 完了・適用済み"
    elif discarded:
        status_core = "✓ 完了（実行専用・変更は破棄）"
    else:
        status_core = "✓ 完了（変更なし）"
    status_label = f"{status_core}{verify_status}"
    lines = [
        f"[{tag}: {status_label}] (trace_id={trace_id})",
        f"タスク: {task}",
        "",
        result.summary,
    ]
    if applied:
        lines += ["", "(変更はプロジェクトに適用され、AutoGitでコミット済みです)"]
        if conflict_files:
            lines += ["", "⚠ 競合の可能性: 委任実行中にプロジェクト側でも変更されていた"
                          f"ファイルを上書きしました: {', '.join(conflict_files)}"]
    elif discarded:
        lines += ["", "(実行専用モード(can_execute)のため、Overlay内のファイル変更は破棄されました)"]

    # ── ハーネスによる機械判定（Workerの自己申告に依存しない注記） ──
    if apply_changes and not result.changed_files:
        # 書き込み権限の委任で差分ゼロ = 未遂の可能性。Workerの完了報告と矛盾し得る。
        lines += ["", "⚠ ハーネス判定: 書き込み権限（can_write）の委任ですが、変更ファイルは0件でした。"
                      "Workerの完了報告と矛盾する場合、タスクは実施されていない可能性があります。"
                      "結果を鵜呑みにせず、読み取り専用の委任で実ファイルの状態を確認してください。"]
    if expected_files and result.changed_files:
        resolved_prefix = resolved_dir.rstrip("/") + "/"
        normalized_expected = {
            f[len(resolved_prefix):] if f.startswith(resolved_prefix) else f.lstrip("./")
            for f in expected_files
        }
        unexpected = [f for f in result.changed_files if f not in normalized_expected]
        if unexpected:
            lines += ["", "⚠ ハーネス判定: 変更予定（expected_files）に含まれないファイルが変更されました: "
                          f"{', '.join(unexpected[:10])}\n"
                          "意図した変更範囲からの逸脱がないか差分サマリを確認してください。"]

    # ── 委任履歴・書き込みストリークの記録 ──
    _record_delegation(label or tag, task, status_label, result.changed_files)
    if apply_changes:
        if verify_cmd and result.verify_exit == 0:
            # 機械検証を通過した変更は「進展」なのでストリークをリセットする
            _note_readonly_delegation()
        else:
            _note_write_delegation(result.changed_files)
    else:
        _note_readonly_delegation()

    return "\n".join(lines)


def run_team_task(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "") -> str:
    """Researcher → Worker を実行し、verify失敗時は自動リトライ後に変更を適用してサマリを返す。"""
    interlock = check_write_interlock()
    if interlock:
        return interlock

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
    base = Path(tempfile.mkdtemp(prefix=f"mimic_subagent_{_sanitize_label_for_path(label) or 'single'}_"))
    _register_inflight(trace_id, base, resolved_dir, worker_task, label, verify_cmd,
                        "team", config.name, config.model)
    return _run_delegation_core(worker_task, project_dir, config, base, trace_id, label,
                                 verify_cmd, "delegate_to_team", team_tag)


def run_worker_once(task: str, project_dir: str, config, label: str = "", verify_cmd: str = "",
                     role_prompt: str = "", apply_changes: bool = True,
                     expected_files: Optional[list[str]] = None) -> str:
    """Researcherを介さずWorkerを実行し、verify失敗時は自動リトライ後に変更を適用する。

    apply_changes=False の場合はOverlay内での実行のみ行い、変更は適用せず破棄する
    （delegate_to_specialist の can_execute=True 用）。"""
    if apply_changes:
        interlock = check_write_interlock()
        if interlock:
            return interlock

    resolved_dir = str(Path(project_dir).resolve())
    trace_id = uuid.uuid4().hex[:8]

    base = Path(tempfile.mkdtemp(prefix=f"mimic_subagent_{_sanitize_label_for_path(label) or 'single'}_"))
    _register_inflight(trace_id, base, resolved_dir, task, label, verify_cmd,
                        "worker", config.name, config.model,
                        role_prompt=role_prompt, apply_changes=apply_changes)
    return _run_delegation_core(task, project_dir, config, base, trace_id, label,
                                 verify_cmd, "delegate_to_worker", "[Worker]",
                                 role_prompt=role_prompt, apply_changes=apply_changes,
                                 expected_files=expected_files)


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
        role_prompt=entry.get("role_prompt", ""),
        apply_changes=entry.get("apply_changes", True),
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
