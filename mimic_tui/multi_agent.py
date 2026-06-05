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
    "web_search", "fetch_webpage",
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
            "2. 必ず 800 文字以内に収める\n"
            "3. 重要な制約・エラー・発見事項を優先的に残す"
        )

    def compact_memory(self, current_memory: str, task_summary: str) -> str:
        """現在の記憶とタスク結果を 800 文字以内に圧縮して保存する。"""
        prompt = (
            "以下の作業記録を 800 文字以内に圧縮し、update_scratchpad で保存してください。\n"
            "【ゴール】【完了済み】【次のステップ】【発見・注意】の形式を必ず守ること。\n\n"
            f"[直前のタスク結果（要約）]\n{task_summary[:400]}\n\n"
            f"[現在の作業記憶]\n{current_memory[:600] if current_memory else 'なし'}"
        )
        return self.run(prompt)


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

    def set_cwd(self, cwd: str) -> None:
        for agent in (self.architect, self.operator, self.scribe):
            agent.cwd = cwd

    def clear_all_history(self) -> None:
        for agent in (self.architect, self.operator, self.scribe):
            agent.clear_history()

    def _make_steps(self):
        from .orchestrator import PlanStep
        return [
            PlanStep(index=1, description="Architect: 構造把握・設計・実装",
                     label="architect", on_failure="abort",  on_success=""),
            PlanStep(index=2, description="Operator: 検証・テスト実行",
                     label="operator",  on_failure="goto:replan", on_success="goto:scribe",
                     max_iterations=2),
            PlanStep(index=3, description="Architect: エラー修正・再設計",
                     label="replan",    on_failure="abort",  on_success="goto:operator",
                     max_iterations=2),
            PlanStep(index=4, description="Scribe: 作業記憶圧縮・保存",
                     label="scribe",    on_failure="skip",   on_success=""),
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

        steps   = self._make_steps()
        workflow = WorkflowGraph(steps)

        # ステップを label → list-index でルックアップ
        idx_of = {s.label: i for i, s in enumerate(steps)}

        if on_plan:
            on_plan(steps)

        def _notify(name: str):
            safe_print(C.cyan(f"\n  🤖 [{name}] ────────────────────────────\n"), flush=True)
            if on_agent_switch:
                on_agent_switch(name)

        def _tick(step):
            """ステップ状態変化を Workflow タブに通知する。"""
            if on_step:
                on_step(step)

        current_memory  = get_scratchpad() or ""
        architect_result = ""
        exec_result      = ""

        cur = 0  # steps リストの現在位置（0-based）

        while cur < len(steps):
            step = steps[cur]
            step.status = "running"
            _tick(step)

            try:
                # ── ステップ別実行 ──────────────────────────────
                if step.label == "architect":
                    _notify("Architect")
                    result = self.architect.run(
                        f"[タスク]\n{user_prompt}\n\n"
                        f"[作業記憶]\n{current_memory or 'なし'}\n\n"
                        "リポジトリ構造を把握し、解決策を設計・実装してください。"
                    )
                    architect_result = result

                elif step.label == "operator":
                    _notify("Operator")
                    result = self.operator.run(
                        f"[設計担当の実装内容]\n{architect_result}\n\n"
                        f"[元のタスク]\n{user_prompt}\n\n"
                        "実装を検証し、テストを実行して動作確認してください。"
                    )
                    exec_result = result

                elif step.label == "replan":
                    _notify("Architect (再設計)")
                    result = self.architect.run(
                        f"[実行エラー]\n{exec_result[-1200:]}\n\n"
                        f"[元のタスク]\n{user_prompt}\n\n"
                        "エラーを分析し、修正した実装を行ってください。"
                    )
                    architect_result = result

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
                result = f"エラー: {e}"
                step.result = result
                step.status = "failed"
                _tick(step)
                action, goto_idx = workflow.resolve_failure(step)
                cur = self._next_index(action, goto_idx, cur, idx_of, steps)
                _tick(step)
                continue

            # ── 成功 / 失敗 判定 ──────────────────────────────
            _SUCCESS = ("成功", "完了", "問題なし", "[SUCCESS]", "テスト合格", "正常動作", "All tests")
            _FAILURE = ("[FAILURE", "Exception:", "Error:", "Traceback", "失敗", "エラー:")

            is_success = step.label in ("architect", "replan", "scribe") or \
                         any(kw in result for kw in _SUCCESS) or \
                         not any(kw in result for kw in _FAILURE)

            if is_success:
                step.status = "done"
                _tick(step)
                action, goto_idx = workflow.resolve_success(step)
                if action == "abort":
                    break
                elif action == "goto" and goto_idx is not None:
                    cur = idx_of.get(
                        next((s.label for s in steps if s.index == goto_idx), ""),
                        cur + 1
                    )
                else:
                    cur += 1
            else:
                step.status = "failed"
                _tick(step)
                safe_print(C.yellow(f"\n  ↻ {step.label} 失敗 → ルーティング中...\n"), flush=True)
                action, goto_idx = workflow.resolve_failure(step)
                if action == "abort":
                    safe_print(C.red("\n  ✗ ワークフロー中断\n"), flush=True)
                    break
                elif action == "skip":
                    step.status = "skipped"
                    _tick(step)
                    cur += 1
                elif action == "goto" and goto_idx is not None:
                    step.status = "retrying"
                    _tick(step)
                    cur = idx_of.get(
                        next((s.label for s in steps if s.index == goto_idx), ""),
                        cur + 1
                    )
                else:
                    step.status = "retrying"
                    _tick(step)
                    # retry: 同ステップ再実行（goto カウンタは WorkflowGraph が管理）

        return exec_result

    @staticmethod
    def _next_index(action: str, goto_idx, cur: int, idx_of: dict, steps: list) -> int:
        if action == "abort":
            return len(steps)  # ループ終了
        if action == "goto" and goto_idx is not None:
            label = next((s.label for s in steps if s.index == goto_idx), "")
            return idx_of.get(label, cur + 1)
        if action == "skip":
            return cur + 1
        return cur  # retry: 変えない
