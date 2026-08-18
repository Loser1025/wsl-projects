# mimic_tui: Claude Code互換 Skills 対応（設計書 P0）
#
# .claude/skills/<name>/SKILL.md を読み取り専用で参照する。
# フロントマター（name/description）のみを常時ロードし、本文は load_skill() 呼び出し時に
# 遅延ロードする（progressive disclosure）。SKILL.md 原本には一切書き込まない。
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

_BODY_MAX_CHARS = 6000        # load_skill() が一度に返す本文の上限（design doc §6）
_SUMMARY_DESC_MAX_CHARS = 200  # 一覧表示1件あたりの description 上限
_SUMMARY_TOTAL_MAX_CHARS = 1500  # 一覧表示の合計上限


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """`---\\nkey: value\\n---\\n本文` を分解する。フォーマット外なら name/description なしで返す。
    依存追加を避けるため YAML はフラットな `key: value` 行のみを対象にした簡易パース。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_fm, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in raw_fm.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        # ネストしたキー（metadata: 以下のインデント行）は対象外 — name/description は
        # トップレベルにしか出現しないため、インデント行はスキップする。
        if line[0] in (" ", "\t"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            meta[key] = val
    return meta, body.strip("\n")


class Skill:
    __slots__ = ("name", "description", "path")

    def __init__(self, name: str, description: str, path: Path):
        self.name = name
        self.description = description
        self.path = path


class SkillRegistry:
    """SKILL.md をスキャンし、name/description のみメモリ保持する軽量レジストリ。
    本文はディスクから都度読む（キャッシュしない — SKILL.md は外部で更新され得るため）。"""

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._lock = threading.Lock()
        self._scanned_dirs: list[Path] = []

    # ── スキャン ──────────────────────────────────────────────
    def scan(self, dirs: list[Path]) -> int:
        """指定ディレクトリ群から */SKILL.md を列挙して登録する。
        同名スキルは後から見つかった方（＝リストの後ろにあるdirs）で上書きする。
        戻り値: 読み込めたスキル数。"""
        found: dict[str, Skill] = {}
        for d in dirs:
            try:
                if not d.is_dir():
                    continue
                for skill_md in sorted(d.glob("*/SKILL.md")):
                    try:
                        text = skill_md.read_text(encoding="utf-8", errors="replace")
                        meta, _ = _parse_frontmatter(text)
                        name = str(meta.get("name") or skill_md.parent.name).strip()
                        desc = str(meta.get("description") or "").strip()
                        if not name:
                            continue
                        found[name] = Skill(name=name, description=desc, path=skill_md)
                    except Exception:
                        continue
            except Exception:
                continue
        with self._lock:
            self._skills.update(found)
            self._scanned_dirs = dirs
        return len(found)

    def rescan(self) -> int:
        """直前と同じディレクトリ集合で再スキャンする（/skills reload 用）。"""
        with self._lock:
            dirs = list(self._scanned_dirs)
        return self.scan(dirs) if dirs else 0

    # ── フェーズA: 常時ロード用の一覧 ──────────────────────────
    def list_summaries(self) -> list[Skill]:
        with self._lock:
            return sorted(self._skills.values(), key=lambda s: s.name)

    def context_header_section(self) -> str:
        """_build_machine_notes 相当に差し込む「利用可能Skill一覧」セクション。
        合計 _SUMMARY_TOTAL_MAX_CHARS を超える分は打ち切る（弱モデルの予算保護）。"""
        skills = self.list_summaries()
        if not skills:
            return ""
        trust = _load_trust()
        lines = []
        total = 0
        for sk in skills:
            desc = sk.description[:_SUMMARY_DESC_MAX_CHARS]
            badge = ""
            t = trust.get(sk.name)
            if t and t.get("pass_count", 0) > 0:
                badge = f"（検証通過{t['pass_count']}回）"
            elif t is None:
                badge = "（※未検証）"
            line = f"- {sk.name}{badge}: {desc}"
            if total + len(line) > _SUMMARY_TOTAL_MAX_CHARS:
                lines.append(f"…他 {len(skills) - len(lines)} 件（省略）")
                break
            lines.append(line)
            total += len(line)
        return (
            "\n\n## 利用可能なSkill（name+descriptionのみ。本文は load_skill(name) で取得）\n"
            + "\n".join(lines) + "\n"
        )

    # ── フェーズB: 遅延ロード ────────────────────────────────
    def load_body(self, name: str) -> str:
        with self._lock:
            sk = self._skills.get(name)
        if sk is None:
            available = ", ".join(s.name for s in self.list_summaries()) or "(なし)"
            return f"エラー: Skill '{name}' が見つかりません。利用可能: {available}"
        try:
            text = sk.path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"エラー: {sk.path} を読めませんでした ({e})"
        _, body = _parse_frontmatter(text)
        total = len(body)
        if total <= _BODY_MAX_CHARS:
            return f"[Skill: {name}]\n{'─' * 60}\n{body}"
        try:
            from .utils import cache_tool_output
            cached = cache_tool_output(f"skill_{name}", body)
            head = cached[:_BODY_MAX_CHARS]
        except Exception:
            head = body[:_BODY_MAX_CHARS]
        return (
            f"[Skill: {name}  本文 {total:,}文字中 先頭 {_BODY_MAX_CHARS:,}文字]\n"
            f"{'─' * 60}\n{head}\n{'─' * 60}\n"
            f"⚠ 本文が長いため切り詰めました。続きは read_tool_cache(cache_key=\"skill_{name}\", offset={_BODY_MAX_CHARS}) で取得できます。"
        )

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._skills


# ── 信頼スコア（design doc §5: SKILL.md原本は非破壊、別ファイルで管理） ─────
_TRUST_LOCK = threading.Lock()


def _trust_path() -> Path:
    p = Path(__file__).parent / ".mimic"
    p.mkdir(parents=True, exist_ok=True)
    return p / "skill_trust.json"


def _load_trust() -> dict:
    p = _trust_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record_outcome(name: str, verify_passed: bool) -> None:
    """Skill使用を伴った委任の verify 結果を記録する（P1: 信頼スコアリング統合の下地）。
    失敗しても黙って無視する（記録はベストエフォート）。"""
    if not name:
        return
    with _TRUST_LOCK:
        try:
            data = _load_trust()
            entry = data.get(name, {"pass_count": 0, "fail_count": 0})
            if verify_passed:
                entry["pass_count"] = int(entry.get("pass_count", 0)) + 1
            else:
                entry["fail_count"] = int(entry.get("fail_count", 0)) + 1
            entry["last_used"] = datetime.now().isoformat(timespec="seconds")
            data[name] = entry
            _trust_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


# ── デフォルトスキャン対象 ──────────────────────────────────────
def default_skill_dirs() -> list[Path]:
    """~/.claude/skills（グローバル）→ プロジェクトの .claude/skills の順でスキャンし、
    後者を優先させる（同名なら上書き）。design doc: 既存の .claude/skills を正とする。"""
    dirs = [Path.home() / ".claude" / "skills"]
    cwd_skills = Path.cwd() / ".claude" / "skills"
    if cwd_skills not in dirs:
        dirs.append(cwd_skills)
    return dirs


registry = SkillRegistry()
