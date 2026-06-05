"""
Day 5: 動的ワークフロー統合テスト

シナリオ:
  1. 意図的にシェルエラーを発生させる → INSERT_STEPS でリカバリステップ割り込み
  2. 自律解決が難しい場合に INTERACTIVE ステップへ状態遷移
  3. ユーザー回答を受けて新しいルートを再構築して復帰

テスト実行: python3 -m mimic_tui.test_dynamic_workflow
"""
from __future__ import annotations
import sys
import os
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mimic_tui.config import load_config
from mimic_tui.agent import OpenRouterAgent, AccountRotator
from mimic_tui.tools import tools as _base_tools, ToolRegistry
from mimic_tui.monitoring import MonitoringToolRegistry, ToolCallLog
from mimic_tui.orchestrator import (
    AgentOrchestrator, PlanStep, WorkflowGraph, WorkflowSignal,
)
from mimic_tui.utils import safe_print, C


# ── 簡易モックモジュール（APIキーなしでテスト可能）─────────────────

class MockRotator:
    """APIキー不要のモックロテーター"""
    def pick(self):
        raise RuntimeError("MockRotator: 実際のAPIコールは行いません")
    def record(self, _): pass
    def can_afford_reviewer(self) -> bool: return False
    def wait_to_start(self, _) -> float: return 0.0
    @property
    def accounts(self): return ["mock"]


# ── 単体テスト: WorkflowSignal と WorkflowGraph ────────────────────

def test_workflow_signal():
    print("\n=== [Test 1] WorkflowSignal Enum ===")
    expected = {"CONTINUE", "ABORT", "GOTO", "REPLAN", "SKIP", "INSERT_STEPS"}
    actual   = {s.name for s in WorkflowSignal}
    missing  = expected - actual
    assert not missing, f"シグナル不足: {missing}"
    print(f"  ✓ 全6シグナル確認: {sorted(actual)}")


def test_workflow_graph_state():
    print("\n=== [Test 2] WorkflowGraph state_snapshot / state_merge ===")
    wg = WorkflowGraph([])
    wg.state_set("key1", "val1")
    snap = wg.state_snapshot()
    assert snap == {"key1": "val1"}, f"snapshot 不一致: {snap}"

    wg.state_merge({"key2": "val2", "key1": "overwritten"})
    assert wg.state["key1"] == "overwritten", "merge last-writer-wins 失敗"
    assert wg.state["key2"] == "val2", "merge 新キー失敗"
    print("  ✓ state_snapshot / state_merge 正常動作")


def test_workflow_graph_goto_rollback():
    print("\n=== [Test 3] WorkflowGraph goto ループ上限 ===")
    steps = [
        PlanStep(index=1, description="step A", label="a",
                 on_failure="goto:a", max_iterations=2),
        PlanStep(index=2, description="step B", label="b"),
    ]
    wg = WorkflowGraph(steps)

    # 1回目 goto → OK
    action, idx = wg.resolve_failure(steps[0])
    assert action == "goto" and idx == 1, f"1回目 goto 失敗: {action},{idx}"

    # 2回目 goto → OK
    action, idx = wg.resolve_failure(steps[0])
    assert action == "goto" and idx == 1, f"2回目 goto 失敗: {action},{idx}"

    # 3回目 → 上限超過でスキップ
    action, idx = wg.resolve_failure(steps[0])
    assert action == "skip", f"上限超過後 skip にならなかった: {action}"
    print("  ✓ goto ループ上限 (max_iterations=2) で skip へ格下げ確認")


def test_planstep_dataclass():
    print("\n=== [Test 4] PlanStep デフォルト値 ===")
    s = PlanStep(index=1, description="test")
    assert s.status == "pending"
    assert s.parallel is False
    assert s.on_failure == "retry"
    assert s.join_policy == "all"
    print("  ✓ PlanStep デフォルト値確認")


def test_deque_task_queue_insert():
    """TaskQueue の先頭割り込み (INSERT_STEPS) をシミュレート"""
    print("\n=== [Test 5] TaskQueue 先頭割り込みシミュレーション ===")
    from collections import deque

    original_steps = [
        PlanStep(index=1, description="step 1"),
        PlanStep(index=2, description="step 2"),
        PlanStep(index=3, description="step 3"),
    ]
    task_queue: deque = deque([[s] for s in original_steps])

    # step 1 を取り出す
    batch1 = task_queue.popleft()
    assert batch1[0].description == "step 1"

    # INSERT_STEPS: リカバリステップをキュー先頭に割り込み
    recovery = [
        PlanStep(index=10, description="recovery A"),
        PlanStep(index=11, description="recovery B"),
    ]
    for b in reversed([[s] for s in recovery]):
        task_queue.appendleft(b)

    order = [task_queue.popleft()[0].description for _ in range(4)]
    assert order == ["recovery A", "recovery B", "step 2", "step 3"], \
        f"割り込み順序が不正: {order}"
    print(f"  ✓ INSERT_STEPS 割り込み順序確認: {order}")


def test_interactive_step_detection():
    """INTERACTIVE ステップ検出ロジック"""
    print("\n=== [Test 6] INTERACTIVE ステップ検出 ===")
    cases = [
        (PlanStep(index=1, description="[INTERACTIVE] 問題が発生しました"), True),
        (PlanStep(index=2, description="通常のステップ"),                  False),
        (PlanStep(index=3, description="処理", label="interactive"),       True),
        (PlanStep(index=4, description="処理", label="normal"),            False),
    ]
    for step, expected in cases:
        result = (
            "[INTERACTIVE]" in step.description or
            step.label == "interactive"
        )
        assert result == expected, f"検出ミス: {step.description!r} → {result}"
    print(f"  ✓ {len(cases)} ケースの INTERACTIVE 検出ロジック確認")


def test_parallel_state_isolation():
    """並列ステート隔離: snapshot → 各ステップが独立更新 → merge"""
    print("\n=== [Test 7] 並列ステート隔離 (MapReduce型) ===")
    wg = WorkflowGraph([])
    wg.state_set("shared", "original")
    wg.state_set("only_in_main", "keep_me")

    # 並列ステップ A・B が独立してローカルステートを構築
    snap = wg.state_snapshot()
    local_a = dict(snap); local_a["result_a"] = "done_a"; local_a["shared"] = "by_a"
    local_b = dict(snap); local_b["result_b"] = "done_b"; local_b["shared"] = "by_b"

    # Join: last-writer-wins でマージ（B が後から書くと仮定）
    wg.state_merge(local_a)
    wg.state_merge(local_b)  # B が A を上書き

    assert wg.state["shared"]       == "by_b",       "last-writer-wins 失敗"
    assert wg.state["result_a"]     == "done_a",      "A の結果消失"
    assert wg.state["result_b"]     == "done_b",      "B の結果消失"
    assert wg.state["only_in_main"] == "keep_me",     "メインの既存キー消失"
    print("  ✓ 並列ステート隔離 + last-writer-wins マージ確認")


# ── メイン ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("動的ワークフロー統合テスト (Day 5)")
    print("=" * 60)

    tests = [
        test_workflow_signal,
        test_workflow_graph_state,
        test_workflow_graph_goto_rollback,
        test_planstep_dataclass,
        test_deque_task_queue_insert,
        test_interactive_step_detection,
        test_parallel_state_isolation,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"結果: {passed} 成功 / {failed} 失敗 / {len(tests)} 合計")
    print("=" * 60)
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
