"""
multi_agent.py — 役割特化マルチエージェントシステム

計画書に基づく 3 エージェント協調アーキテクチャ:
  Architect  — コード設計・ファイル修正
  Operator   — コマンド実行・テスト・Web 検索
  Scribe     — 作業記憶の管理・圧縮

既存の OpenRouterAgent / MonitoringToolRegistry / ToolRegistry を
ラップして実装するため、TUI や ReAct ループの既存コードは変更不要。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional, Callable

from .agent import OpenRouterAgent, AccountRotator
from .monitoring import MonitoringToolRegistry, ToolCallLog
from .tools import ToolRegistry, tools as _global_tools
from .utils import safe_print, C, log


# ── 役割ごとの許可ツール定義 ──────────────────────────────────────

_ARCHITECT_TOOLS = [
    "get_repo_map", "read_file", "read_tool_cache",
    "smart_read", "search_in_file", "file_info",
    "write_file", "edit_file", "patch_file",
    "update_scratchpad",
]

_OPERATOR_TOOLS = [
    "run_bash", "run_pipeline",
    "read_file", "read_tool_cache", "file_info",
    "smart_read", "search_in_file", "grep_codebase",
    "web_search", "fetch_webpage", "search_history",
    "update_scratchpad",
]

_SCRIBE_TOOLS = [
    "update_scratchpad", "search_history", "read_file",
]


# ── 役割エージェント基底クラス ────────────────────────────────────

class RoleAgentBase:
    """
    OpenRouterAgent を役割制限付きツールセットでラップする基底クラス。
    各サブクラスは ROLE_NAME / ROLE_DESCRIPTION / ALLOWED_TOOLS を定義する。
    """

    ROLE_NAME: str = "BaseAgent"
    ROLE_DESCRIPTION: str = ""
    ALLOWED_TOOLS: list[str] = []

    def __init__(
        self,
        rotator: AccountRotator,
        base_prompt: str = "",
        display_fn: Optional[Callable] = None,
    ):
        # 許可ツールのみを持つ制限付きレジストリを生成
        restricted = ToolRegistry()
        for name in self.ALLOWED_TOOLS:
            if not restricted.copy_tool(name, _global_tools):
                log.warning({"event": "multi_agent_tool_missing", "tool": name,
                             "agent": self.ROLE_NAME})

        self._tool_log = ToolCallLog()
        self._registry = MonitoringToolRegistry(
            base=restricted,
            log=self._tool_log,
            display_fn=display_fn,
        )

        self._agent = OpenRouterAgent(rotator, self._registry)
        self._agent.set_system_prompt(self._build_system_prompt(base_prompt))

    def _build_system_prompt(self, extra: str) -> str:
        lines = [
            f"あなたは「{self.ROLE_NAME}」として動作する AI エージェントです。",
            f"専門領域: {self.ROLE_DESCRIPTION}",
            "自分の責任範囲のみに集中し、割り当てられたツールだけを使用してください。",
        ]
        if extra:
            lines.append(extra)
        return "\n".join(lines)

    # ── 公開 API ──────────────────────────────────────────────────

    @property
    def cwd(self) -> str:
        return self._agent.cwd

    @cwd.setter
    def cwd(self, v: str):
        self._agent.cwd = v

    def run(self, prompt: str) -> str:
        return self._agent.run_stream(prompt)

    def run_stream(self, prompt: str, callback=None) -> str:
        return self._agent.run_stream(prompt, callback=callback)

    def clear_history(self):
        self._agent.clear_history()

    @property
    def tool_log(self) -> ToolCallLog:
        return self._tool_log


# ── 具体的な役割エージェント ──────────────────────────────────────

class ArchitectAgent(RoleAgentBase):
    """コード設計・ファイル修正・リポジトリ構造把握の専門エージェント。"""

    ROLE_NAME = "Architect"
    ROLE_DESCRIPTION = "コード設計・パッチ作成・リポジトリ構造の把握"
    ALLOWED_TOOLS = _ARCHITECT_TOOLS

    def _build_system_prompt(self, extra: str) -> str:
        base = super()._build_system_prompt(extra)
        return base + (
            "\n\n[行動指針]\n"
            "1. まず get_repo_map または smart_read でコード構造を把握する\n"
            "2. 必要なファイルを read_file / search_in_file で確認してから編集する\n"
            "3. 編集完了後は必ず以下の形式で報告する:\n"
            "   - 変更ファイル: <パス1>, <パス2>\n"
            "   - テストコマンド: <pytest/npm test 等の具体的コマンド>\n"
            "4. 実装後に update_scratchpad で進捗を記録する\n"
            "5. bash コマンドの実行は行わない（それは執行担当の責務）"
        )


class OperatorAgent(RoleAgentBase):
    """コマンド実行・テスト・Web 検索の専門エージェント。"""

    ROLE_NAME = "Operator"
    ROLE_DESCRIPTION = "コマンド実行・テスト・コードベース探索・Web 調査"
    ALLOWED_TOOLS = _OPERATOR_TOOLS

    def _build_system_prompt(self, extra: str) -> str:
        base = super()._build_system_prompt(extra)
        return base + (
            "\n\n[行動指針]\n"
            "1. 設計担当の実装を run_bash でテスト・検証する\n"
            "2. エラーが出た場合は完全なスタックトレースを出力する\n"
            "3. 最終的に成功 / 失敗を明確に報告する\n"
            "4. ファイルの直接編集は行わない（それは設計担当の責務）"
        )


class ScribeAgent(RoleAgentBase):
    """作業記憶管理・自動圧縮の専門エージェント。"""

    ROLE_NAME = "Scribe"
    ROLE_DESCRIPTION = "作業記憶の管理・要約・コンテキスト圧縮"
    ALLOWED_TOOLS = _SCRIBE_TOOLS

    def _build_system_prompt(self, extra: str) -> str:
        base = super()._build_system_prompt(extra)
        return base + (
            "\n\n[行動指針]\n"
            "1. update_scratchpad で常に以下の形式で保存する:\n"
            "   【ゴール】【完了済み】【次のステップ】【発見・注意】\n"
            "2. 必ず 2000 文字以内に収める\n"
            "3. 重要な制約・エラー・発見事項を優先的に残す"
        )

    def compact_memory(self, current_memory: str, task_summary: str) -> str:
        """現在の記憶とタスク結果を 2000 文字以内に圧縮して保存する。"""
        prompt = (
            "以下の作業記録を 2000 文字以内に圧縮し、update_scratchpad で保存してください。\n"
            "【ゴール】【完了済み】【次のステップ】【発見・注意】の形式を必ず守ること。\n\n"
            f"[直前のタスク結果（要約）]\n{task_summary[:600]}\n\n"
            f"[現在の作業記憶]\n{current_memory[:1500] if current_memory else 'なし'}"
        )
        return self.run(prompt)


# ── セッション内タスク履歴台帳 ────────────────────────────────────
# LLM の要約に頼らず機械的に「何を・どこに・どうした」を記録する。
# 要約は圧縮のたびに劣化するが、ファイルパス等の事実情報はここに残る。

@dataclass
class TaskRecord:
    goal:     str
    files:    list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)  # 実行コマンドと成否（"[ok] pytest ..." 等）
    summary:  str = ""
    status:   str = "done"


# ── マルチエージェントオーケストレーター ──────────────────────────

class MultiAgentOrchestrator:
    """
    Architect / Operator / Scribe を WorkflowGraph で協調させるオーケストレーター。

    ワークフロー定義:
      Step 1 Architect  : 設計・実装           on_failure=abort
      Step 2 Operator   : 検証・テスト         on_failure=goto:replan, on_success=goto:scribe
      Step 3 Architect  : エラー修正・再設計   on_failure=abort, on_success=goto:operator
      Step 4 Scribe     : 記憶圧縮・保存       on_failure=skip

    WorkflowGraph の goto / max_iterations でループ上限を管理し、
    on_plan / on_step コールバック経由で Workflow タブをリアルタイム更新する。
    """

    def __init__(
        self,
        architect: ArchitectAgent,
        operator: OperatorAgent,
        scribe: ScribeAgent,
    ):
        self.architect = architect
        self.operator  = operator
        self.scribe    = scribe
        self._orch     = None  # AgentOrchestrator キャッシュ（Planner 会話履歴を保持）
        self._task_history: list[TaskRecord] = []  # セッション内タスク台帳

    def set_cwd(self, cwd: str) -> None:
        for agent in (self.architect, self.operator, self.scribe):
            agent.cwd = cwd

    def clear_all_history(self) -> None:
        for agent in (self.architect, self.operator, self.scribe):
            agent.clear_history()
        self._task_history.clear()

    # 書き込み系ツール（Architect が実際に変更したか判定に使用）
    _WRITE_TOOLS = {"write_file", "edit_file", "patch_file"}

    def _make_steps(self):
        from .orchestrator import PlanStep
        return [
            # Step 1: Architect が設計・実装
            PlanStep(index=1, description="Architect: 構造把握・設計・実装",
                     label="architect", on_failure="abort",      on_success=""),
            # Step 2: Operator がファイル変更を確認（Architect が何もしなかった場合に再設計）
            PlanStep(index=2, description="Operator: 実装確認（ファイル変更検証）",
                     label="verify",    on_failure="goto:architect", on_success="",
                     max_iterations=2),
            # Step 3: Operator がテスト実行
            PlanStep(index=3, description="Operator: テスト実行・動作検証",
                     label="operator",  on_failure="goto:replan", on_success="goto:scribe",
                     max_iterations=2),
            # Step 4: Architect がエラー修正（失敗アプローチの情報付き）
            PlanStep(index=4, description="Architect: エラー修正・別アプローチで再設計",
                     label="replan",    on_failure="abort",      on_success="goto:operator",
                     max_iterations=2),
            # Step 5: Scribe が作業記憶を圧縮
            PlanStep(index=5, description="Scribe: 作業記憶圧縮・保存",
                     label="scribe",    on_failure="skip",       on_success=""),
        ]

    # ── メイン実行ループ ──────────────────────────────────────────

    def execute_task(
        self,
        user_prompt: str,
        on_plan:         Optional[Callable] = None,
        on_step:         Optional[Callable] = None,
        on_agent_switch: Optional[Callable[[str], None]] = None,
    ) -> str:
        from .orchestrator import WorkflowGraph
        from .utils import get_scratchpad

        steps    = self._make_steps()
        workflow = WorkflowGraph(steps)
        idx_of   = {s.label: i for i, s in enumerate(steps)}

        if on_plan:
            on_plan(steps)

        def _notify(name: str):
            safe_print(C.cyan(f"\n  🤖 [{name}] ────────────────────────────\n"), flush=True)
            if on_agent_switch:
                on_agent_switch(name)

        def _tick(step):
            if on_step:
                on_step(step)

        def _goto(goto_idx) -> int:
            label = next((s.label for s in steps if s.index == goto_idx), "")
            return idx_of.get(label, cur + 1)

        current_memory   = get_scratchpad() or ""
        architect_result = ""
        exec_result      = ""
        cur              = 0

        while cur < len(steps):
            step = steps[cur]
            step.status = "running"
            _tick(step)

            # ── 各ステップの実行前ログ長を記録（Architect 変更検出用）
            arch_log_before = len(self.architect.tool_log.records)

            try:
                # ── ステップ別実行 ──────────────────────────────

                if step.label == "architect":
                    _notify("Architect")
                    result = self.architect.run(
                        f"[タスク]\n{user_prompt}\n\n"
                        f"[作業記憶]\n{current_memory or 'なし'}\n\n"
                        "リポジトリ構造を把握し、解決策を設計・実装してください。\n"
                        "実装後は「変更ファイル: <パス>」「テストコマンド: <コマンド>」を明記すること。"
                    )
                    architect_result = result
                    # 変更ファイル・テストコマンドを共有ステートに格納
                    workflow.parse_state_updates(result)
                    changed = self._extract_changed_files(result)
                    test_cmd = self._extract_test_command(result)
                    if changed:
                        workflow.state_set("changed_files", changed)
                    if test_cmd:
                        workflow.state_set("test_command", test_cmd)

                elif step.label == "verify":
                    changed = workflow.state_get("changed_files")

                    # 読み取り専用タスクは verify をスキップ（架空の「変更なし」にならないよう）
                    if not changed and any(
                        kw in architect_result for kw in self._READONLY_INDICATORS
                    ) and len(architect_result) >= 200:
                        safe_print(C.cyan("\n  ℹ [verify] 読み取り専用タスクのため確認スキップ\n"), flush=True)
                        result = "確認完了: 読み取り専用タスク（ファイル変更不要）"
                    else:
                        _notify("Operator (実装確認)")
                        result = self.operator.run(
                            f"[設計担当の報告]\n{architect_result[:800]}\n\n"
                            f"[報告された変更ファイル]\n{changed or '（未明記）'}\n\n"
                            "以下を確認してください:\n"
                            "1. git diff --name-only または stat で実際にファイルが変更されているか確認\n"
                            "2. 変更あり → 「確認完了: <ファイル名>」と報告\n"
                            "3. 変更なし → 「変更なし: 実装されていません」と明確に報告"
                        )

                elif step.label == "operator":
                    test_cmd = workflow.state_get("test_command")
                    changed  = workflow.state_get("changed_files")

                    # 読み取り専用タスクはテスト実行スキップ
                    if not changed and not test_cmd and any(
                        kw in architect_result for kw in self._READONLY_INDICATORS
                    ) and len(architect_result) >= 200:
                        safe_print(C.cyan("\n  ℹ [operator] 読み取り専用タスク → テストスキップ\n"), flush=True)
                        result = "[SUCCESS] 読み取り専用タスク完了（テスト不要）"
                    else:
                        _notify("Operator (テスト)")
                        result = self.operator.run(
                            f"[設計担当の実装内容]\n{architect_result[:800]}\n\n"
                            f"[推奨テストコマンド]\n{test_cmd or '（未指定。適切なテストを実行してください）'}\n\n"
                            f"[元のタスク]\n{user_prompt}\n\n"
                            "テストを実行して動作確認してください。"
                        )
                    exec_result = result
                    workflow.state_set("last_error", exec_result[-600:])

                elif step.label == "replan":
                    _notify("Architect (再設計)")
                    failed_approach = workflow.state_get("last_error")
                    result = self.architect.run(
                        f"[★ 失敗したアプローチ（再使用禁止）]\n{architect_result[:500]}\n\n"
                        f"[実行エラー詳細]\n{failed_approach or exec_result[-800:]}\n\n"
                        f"[元のタスク]\n{user_prompt}\n\n"
                        "上記アプローチとは異なる方法で実装してください。\n"
                        "変更後も「変更ファイル: <パス>」「テストコマンド: <コマンド>」を明記すること。"
                    )
                    architect_result = result
                    workflow.parse_state_updates(result)
                    changed = self._extract_changed_files(result)
                    test_cmd = self._extract_test_command(result)
                    if changed:
                        workflow.state_set("changed_files", changed)
                    if test_cmd:
                        workflow.state_set("test_command", test_cmd)

                elif step.label == "scribe":
                    _notify("Scribe")
                    task_summary = f"タスク: {user_prompt[:200]}\n結果: {exec_result[:400]}"
                    result = self.scribe.compact_memory(current_memory, task_summary)

                else:
                    result = ""

                step.result = result[:500] if result else ""

            except KeyboardInterrupt:
                step.status = "failed"
                _tick(step)
                raise
            except Exception as e:
                log.error({"event": "multi_step_error", "label": step.label, "error": str(e)})
                step.result = f"エラー: {e}"
                step.status = "failed"
                _tick(step)
                action, goto_idx = workflow.resolve_failure(step)
                cur = self._route(action, goto_idx, cur, idx_of, steps, step, _tick)
                continue

            # ── 成否判定（改善版） ──────────────────────────────
            is_success = self._judge_success(step, result, arch_log_before)

            if is_success:
                step.status = "done"
                _tick(step)
                action, goto_idx = workflow.resolve_success(step)
                if action == "abort":
                    break
                elif action == "goto" and goto_idx is not None:
                    cur = _goto(goto_idx)
                else:
                    cur += 1
            else:
                step.status = "failed"
                _tick(step)
                safe_print(C.yellow(f"\n  ↻ [{step.label}] 失敗 → ルーティング中...\n"), flush=True)
                action, goto_idx = workflow.resolve_failure(step)
                if action == "abort":
                    safe_print(C.red("\n  ✗ ワークフロー中断\n"), flush=True)
                    break
                cur = self._route(action, goto_idx, cur, idx_of, steps, step, _tick)

        return exec_result

    # ── 動的ワークフロー実行 ──────────────────────────────────────

    def run_dynamic(
        self,
        user_prompt: str,
        on_plan:         Optional[Callable] = None,
        on_step:         Optional[Callable] = None,
        on_interactive:  Optional[Callable] = None,
    ) -> str:
        """
        AgentOrchestrator.run_with_plan() を使った動的ワークフロー実行。
        Planner がステップを生成し、各ステップの label に応じて
        Architect / Operator / Scribe を自動ディスパッチする。
        """
        from .orchestrator import AgentOrchestrator
        if self._orch is None:
            rotator = self.architect._agent.rotator
            # Architect 用の制限付きレジストリではなく全ツールを渡す。
            # Reflector の verify_registry や _make_executor_agent のフォールバックが
            # run_bash / run_pipeline 等を解決できなくなるため。
            self._orch = AgentOrchestrator(rotator, _global_tools, executor=self.architect._agent)
        self._orch.executor.cwd = self.architect.cwd
        role_agents = {
            "architect": self.architect,
            "operator":  self.operator,
            "scribe":    self.scribe,
        }

        arch_log_before = len(self.architect.tool_log.records)
        op_log_before   = len(self.operator.tool_log.records)

        ledger = self._render_task_history()
        prompt_for_orch = (
            f"{ledger}\n\n[今回の依頼]\n{user_prompt}" if ledger else user_prompt
        )

        result = self._orch.run_with_plan(
            prompt_for_orch,
            on_plan        = on_plan,
            on_step        = on_step,
            on_interactive = on_interactive,
            role_agents    = role_agents,
        )
        self._record_task(user_prompt, result, arch_log_before, op_log_before)
        return result

    # ── 成否判定ロジック ──────────────────────────────────────────

    # 読み取り専用タスクのキーワード（これがあれば書き込みなしでも成功）
    _READONLY_INDICATORS = (
        "分析", "要約", "評価", "考察", "まとめ", "レポート", "調査結果",
        "結論", "比較", "解説", "説明", "確認結果", "レビュー",
        "以下の通り", "以下にまとめ", "以下を分析",
    )

    def _judge_success(self, step, result: str, arch_log_before: int) -> bool:
        """ステップ種別ごとに適切な成否判定を行う。"""
        # Scribe は常に成功扱い
        if step.label == "scribe":
            return True

        # Architect / replan: 書き込みツールを呼んだか、または読み取り専用タスクか確認
        if step.label in ("architect", "replan"):
            new_records = self.architect.tool_log.records[arch_log_before:]
            did_write = any(r.tool in self._WRITE_TOOLS for r in new_records)

            if did_write:
                return True

            # 書き込みなし → 読み取り専用タスク（分析・要約）か判定
            is_readonly = (
                len(result) >= 200 and
                any(kw in result for kw in self._READONLY_INDICATORS)
            )
            if is_readonly:
                safe_print(C.cyan(
                    f"\n  ℹ [{step.label}] 読み取り専用タスク（分析・要約）として処理\n"
                ), flush=True)
                return True

            safe_print(C.yellow(
                f"\n  ⚠ [{step.label}] ファイル変更なし・分析結果なし → 再設計を要求\n"
            ), flush=True)
            return False

        # Operator (verify): 「変更なし」パターンで失敗
        if step.label == "verify":
            no_change_kw = ("変更なし", "実装されていません", "差分なし", "変更が確認できません")
            if any(kw in result for kw in no_change_kw):
                return False
            confirm_kw = ("確認完了", "変更あり", "ファイルが変更", "差分を確認")
            return any(kw in result for kw in confirm_kw) or "[SUCCESS]" in result

        # Operator (operator): run_bash 終了コードを最優先で判定
        has_bash_success = "[SUCCESS]" in result
        has_bash_failure = "[FAILURE" in result
        if has_bash_success and not has_bash_failure:
            return True
        if has_bash_failure:
            return False
        # フォールバック: キーワードマッチ
        _TEXT_OK = ("成功", "完了", "問題なし", "テスト合格", "正常動作", "All tests passed")
        _TEXT_NG = ("Exception:", "Traceback", "失敗", "エラー:", "FAILED")
        has_ok = any(kw in result for kw in _TEXT_OK)
        has_ng = any(kw in result for kw in _TEXT_NG)
        return has_ok or not has_ng

    # ── ユーティリティ ────────────────────────────────────────────

    # ── タスク履歴台帳の記録・整形 ────────────────────────────────

    _FAIL_KEYWORDS = ("失敗", "エラー:", "Exception", "Traceback", "中断", "[FAILURE")
    _OK_KEYWORDS   = ("成功", "完了", "[SUCCESS")

    _COMMAND_TOOLS = {"run_bash", "run_pipeline"}

    @staticmethod
    def _extract_touched_files(records: list, before: int) -> list[str]:
        """ツール呼び出しログから書き込み系ツールが触れたファイルパスを抽出する。"""
        import re
        paths: list[str] = []
        for r in records[before:]:
            if r.tool not in MultiAgentOrchestrator._WRITE_TOOLS:
                continue
            m = re.search(r"path=['\"]([^'\"]+)['\"]", r.args_preview)
            if m and m.group(1) not in paths:
                paths.append(m.group(1))
        return paths

    @staticmethod
    def _extract_commands(records: list, before: int) -> list[str]:
        """run_bash/run_pipeline の呼び出しからコマンド文字列と成否を抽出する。
        args_preview には実行コマンド、result_preview には [SUCCESS]/[FAILURE]
        マーカーが含まれるため、両方を突き合わせて記録する。"""
        entries: list[str] = []
        for r in records[before:]:
            if r.tool not in MultiAgentOrchestrator._COMMAND_TOOLS:
                continue
            cmd = ""
            for part in r.args_preview.split(", "):
                if part.startswith("command="):
                    cmd = part[len("command="):].strip("'\"")
                    break
            if not cmd:
                continue
            if "[SUCCESS]" in r.result_preview:
                tag = "ok"
            elif "[FAILURE" in r.result_preview or r.status == "error":
                tag = "ng"
            else:
                tag = "?"
            entry = f"[{tag}] {cmd}"
            if entry not in entries:
                entries.append(entry)
        return entries

    def _derive_status(self, text: str) -> str:
        if any(kw in text for kw in self._FAIL_KEYWORDS):
            return "failed"
        if any(kw in text for kw in self._OK_KEYWORDS):
            return "success"
        return "done"

    def _record_task(self, user_prompt: str, result: str,
                      arch_log_before: int, op_log_before: int) -> None:
        """完了したタスクを台帳に記録する（要約に頼らず機械的に保持）。"""
        files = self._extract_touched_files(self.architect.tool_log.records, arch_log_before)
        for f in self._extract_touched_files(self.operator.tool_log.records, op_log_before):
            if f not in files:
                files.append(f)
        commands = self._extract_commands(self.operator.tool_log.records, op_log_before)
        self._task_history.append(TaskRecord(
            goal     = user_prompt[:100],
            files    = files,
            commands = commands,
            summary  = result[:200].replace("\n", " "),
            status   = self._derive_status(result),
        ))
        if len(self._task_history) > 20:
            self._task_history = self._task_history[-20:]

    def _render_task_history(self, n: int = 8) -> str:
        """直近 n 件のタスク履歴を Planner/実行担当への注入用テキストに整形する。"""
        if not self._task_history:
            return ""
        lines = ["【このセッションでの作業履歴（事実ベース・要約より優先して信頼すること）】"]
        for i, rec in enumerate(self._task_history[-n:], 1):
            files_str = ", ".join(rec.files[:6]) if rec.files else "（ファイル変更なし）"
            lines.append(f"{i}. [{rec.status}] {rec.goal} → 変更/作成: {files_str}")
            if rec.commands:
                lines.append(f"   実行コマンド: {' / '.join(rec.commands[:5])}")
            if rec.summary:
                lines.append(f"   結果概要: {rec.summary}")
        return "\n".join(lines)

    @staticmethod
    def _extract_changed_files(text: str) -> str:
        """Architect の報告から変更ファイル一覧を抽出する。"""
        import re
        m = re.search(r'変更ファイル[:：]\s*(.+)', text)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_test_command(text: str) -> str:
        """Architect の報告からテストコマンドを抽出する。"""
        import re
        m = re.search(r'テストコマンド[:：]\s*(.+)', text)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _route(action: str, goto_idx, cur: int,
               idx_of: dict, steps: list, step, tick_fn) -> int:
        """on_failure / on_success のルーティング結果を list-index に変換する。"""
        if action == "abort":
            return len(steps)
        if action == "goto" and goto_idx is not None:
            label = next((s.label for s in steps if s.index == goto_idx), "")
            step.status = "retrying"
            tick_fn(step)
            return idx_of.get(label, cur + 1)
        if action == "skip":
            step.status = "skipped"
            tick_fn(step)
            return cur + 1
        # retry: 同ステップ再実行
        step.status = "retrying"
        tick_fn(step)
        return cur
