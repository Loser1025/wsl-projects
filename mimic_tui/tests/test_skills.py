# mimic_tui: skills.py の安全境界テスト（bench/test設計書 Track B）
#
# 対象は「壊れたら危険な境界」のみ:
#   - SKILL.md原本への非破壊性
#   - コンテキスト予算（本文の切り詰め）
#   - ツール名エイリアスヒントが無関係なSkillにノイズを足さないこと
#   - Workerセッションログからのskill使用検出（信頼スコアリングの前提）
#
# 新規依存は追加しない（標準ライブラリの unittest のみ）。
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mimic_tui import skills


def _write_skill(base: Path, name: str, description: str, body: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}", encoding="utf-8")
    return p


class TestSkillNonDestructive(unittest.TestCase):
    """SKILL.md原本には一切書き込まない（design doc §5の非破壊原則）。"""

    def test_skill_body_is_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "skills"
            skill_path = _write_skill(base, "demo", "テスト用Skill", "本文テキスト。")
            before = hashlib.md5(skill_path.read_bytes()).hexdigest()

            reg = skills.SkillRegistry()
            reg.scan([base])
            reg.load_body("demo")
            reg.load_body("demo")  # 複数回呼んでも変わらないこと

            after = hashlib.md5(skill_path.read_bytes()).hexdigest()
            self.assertEqual(before, after)


class TestSkillBodyBudget(unittest.TestCase):
    """本文が予算(_BODY_MAX_CHARS)を超えたら必ず切り詰められ、
    cache_tool_output 経由の続き取得に誘導されること。"""

    def test_skill_body_truncated_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "skills"
            long_body = "あ" * (skills._BODY_MAX_CHARS + 500)
            _write_skill(base, "long-demo", "長いSkill", long_body)

            reg = skills.SkillRegistry()
            reg.scan([base])
            result = reg.load_body("long-demo")

            # ヘッダー・区切り線・フッター分の余裕を見て、予算の2倍は超えないことだけ厳密に見る
            self.assertLess(len(result), skills._BODY_MAX_CHARS * 2)
            self.assertIn("read_tool_cache", result)

    def test_skill_body_under_budget_is_not_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "skills"
            short_body = "短い本文です。"
            _write_skill(base, "short-demo", "短いSkill", short_body)

            reg = skills.SkillRegistry()
            reg.scan([base])
            result = reg.load_body("short-demo")

            self.assertIn(short_body, result)
            self.assertNotIn("read_tool_cache", result)


class TestSkillTrustNonDestructive(unittest.TestCase):
    """信頼スコアは .mimic/skill_trust.json に分離保存され、SKILL.md本体は変わらない。"""

    def test_record_outcome_does_not_touch_skill_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "skills"
            skill_path = _write_skill(base, "trust-demo", "信頼テスト", "本文。")
            before = hashlib.md5(skill_path.read_bytes()).hexdigest()

            fake_trust_file = Path(tmp) / "skill_trust.json"
            with patch.object(skills, "_trust_path", return_value=fake_trust_file):
                skills.record_outcome("trust-demo", True)
                skills.record_outcome("trust-demo", False)
                data = skills._load_trust()

            after = hashlib.md5(skill_path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(data["trust-demo"]["pass_count"], 1)
            self.assertEqual(data["trust-demo"]["fail_count"], 1)


class TestAliasHintNoise(unittest.TestCase):
    """ツール名エイリアスヒントは、本文が実際にClaude Code固有ツール名に
    言及している場合のみ付く。無関係な本文にはノイズを足さない。"""

    def test_hint_present_when_tool_names_referenced(self):
        body = "Use the Read tool to inspect files, then Edit or Bash as needed."
        hint = skills._build_alias_hint(body)
        self.assertIn("read_file", hint)
        self.assertIn("edit_file", hint)
        self.assertIn("run_bash", hint)

    def test_no_hint_when_no_tool_names_referenced(self):
        body = "This document explains Core Web Vitals thresholds and scoring weights."
        hint = skills._build_alias_hint(body)
        self.assertEqual(hint, "")


class TestSessionSkillUsageDetection(unittest.TestCase):
    """Workerのセッションログ(trace_id経由)からload_skill呼び出しを正しく検出できること
    (P1: 信頼スコアリングのWorkerサブプロセス側の前提)。"""

    def test_find_session_skill_usages_from_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            sessions_dir.mkdir()
            trace_id = "abc123"
            entries = [
                {"type": "session_start", "trace_id": trace_id, "model": "test"},
                {"type": "action", "tool": "load_skill", "args": {"name": "web-perf"}},
                {"type": "observation", "tool": "load_skill", "result": "..."},
                {"type": "action", "tool": "read_file", "args": {"path": "x.py"}},
                {"type": "action", "tool": "load_skill", "args": {"name": "wrangler"}},
            ]
            jf = sessions_dir / "test.jsonl"
            jf.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

            used = skills.find_session_skill_usages(sessions_dir, trace_id)
            self.assertEqual(used, {"web-perf", "wrangler"})

    def test_find_session_skill_usages_wrong_trace_id_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            sessions_dir.mkdir()
            entries = [
                {"type": "session_start", "trace_id": "other-trace", "model": "test"},
                {"type": "action", "tool": "load_skill", "args": {"name": "web-perf"}},
            ]
            jf = sessions_dir / "test.jsonl"
            jf.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

            used = skills.find_session_skill_usages(sessions_dir, "nonexistent-trace")
            self.assertEqual(used, set())


if __name__ == "__main__":
    unittest.main()
