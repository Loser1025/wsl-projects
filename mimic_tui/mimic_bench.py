# mimic_tui: 実測ベンチマーク基盤（設計書 Track A, P0/P1）
#
# 新しいベンチマーク問題集は作らない。既存の .mimic/ 配下の実績ログ
# （skill_trust.json / mcp_policy.json / verify_cmds.json / sessions/*.jsonl）を
# 集計してMarkdownレポートを出すだけ。日付ごとにスナップショットを保存し、
# 前回との差分（通過率の増減）を見えるようにする。
#
# 実行方法: python3 -m mimic_tui.mimic_bench  （または /bench スラッシュコマンド）
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).parent
_MIMIC_DIR = _BASE_DIR / ".mimic"
_HISTORY_DIR = _MIMIC_DIR / "bench_history"
_MIN_SAMPLE = 5  # これ未満の使用回数は「参考値」として区別表示する（design doc §2.4）


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── データ収集: 既存ファイルを読むだけ ────────────────────────────
def collect_skill_stats() -> dict:
    """.mimic/skill_trust.json から Skill 別の通過率を計算する。"""
    data = _load_json(_MIMIC_DIR / "skill_trust.json")
    out = {}
    for name, stats in data.items():
        p = int(stats.get("pass_count", 0))
        f = int(stats.get("fail_count", 0))
        total = p + f
        out[name] = {
            "pass": p,
            "fail": f,
            "total": total,
            "rate": (p / total) if total else None,
            "low_sample": total < _MIN_SAMPLE,
            "last_used": stats.get("last_used", ""),
        }
    return out


def collect_mcp_stats() -> dict:
    """.mimic/mcp_policy.json から MCPサーバーの信頼設定を読む。
    現状 mcp_policy.json には pass/fail の実績は記録されていない
    （MCP対応P1では書込み承認の可否のみを管理しており、Skillのような
    verify結果ベースの信頼スコアリングはまだ実装していない — 既知のギャップ）。
    使用回数はセッションログから補う（collect_session_usage参照）。"""
    data = _load_json(_MIMIC_DIR / "mcp_policy.json")
    return {name: {"trust": v.get("trust", "")} for name, v in data.items()}


def collect_verify_cmd_stats() -> dict:
    """.mimic/verify_cmds.json からプロジェクト別の学習済みverify_cmd実績を読む。"""
    data = _load_json(_MIMIC_DIR / "verify_cmds.json")
    out = {}
    for project, v in data.items():
        out[project] = {
            "passes": v.get("passes", 0),
            "last_used": v.get("last_used", ""),
        }
    return out


def collect_session_usage() -> dict:
    """sessions/*.jsonl の action エントリを走査し、load_skill / mcp__* の
    呼び出し回数を集計する（skill_trust.json/mcp_policy.jsonにはない「実際に
    何回呼ばれたか」の生カウント）。壊れた行は無視する。"""
    sessions_dir = _MIMIC_DIR / "sessions"
    skill_calls: dict[str, int] = {}
    mcp_calls: dict[str, int] = {}
    if not sessions_dir.is_dir():
        return {"skills": skill_calls, "mcp_servers": mcp_calls}
    for jf in sessions_dir.glob("*.jsonl"):
        try:
            lines = jf.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "action":
                continue
            tool = e.get("tool", "")
            if tool == "load_skill":
                n = (e.get("args") or {}).get("name")
                if n:
                    skill_calls[n] = skill_calls.get(n, 0) + 1
            elif tool.startswith("mcp__"):
                parts = tool.split("__", 2)
                server = parts[1] if len(parts) >= 2 else tool
                mcp_calls[server] = mcp_calls.get(server, 0) + 1
    return {"skills": skill_calls, "mcp_servers": mcp_calls}


def collect_all() -> dict:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "skills": collect_skill_stats(),
        "mcp_servers": collect_mcp_stats(),
        "verify_cmds": collect_verify_cmd_stats(),
        "session_usage": collect_session_usage(),
    }


# ── スナップショット保存・前回との差分 ──────────────────────────
def _snapshot_path(day: Optional[str] = None) -> Path:
    day = day or datetime.now().strftime("%Y-%m-%d")
    return _HISTORY_DIR / f"{day}.json"


def save_snapshot(data: dict) -> Path:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_previous_snapshot() -> Optional[dict]:
    """今日以外で最新のスナップショットを読む（今日分は今まさに作っている最中なので除外）。"""
    if not _HISTORY_DIR.is_dir():
        return None
    today = _snapshot_path()
    candidates = sorted(
        (f for f in _HISTORY_DIR.glob("*.json") if f != today),
        key=lambda f: f.name, reverse=True,
    )
    if not candidates:
        return None
    return _load_json(candidates[0])


def _rate_str(rate: Optional[float]) -> str:
    return f"{rate:.0%}" if rate is not None else "—"


def _diff_pt(prev_rate: Optional[float], cur_rate: Optional[float]) -> str:
    if prev_rate is None or cur_rate is None:
        return ""
    delta = round((cur_rate - prev_rate) * 100)
    if delta == 0:
        return "  前回比 ±0pt"
    sign = "+" if delta > 0 else ""
    return f"  前回比 {sign}{delta}pt"


# ── Markdownレポート生成 ────────────────────────────────────────
def build_report(data: dict, previous: Optional[dict] = None) -> str:
    lines = [f"# Mimic ベンチマークレポート — {data['generated_at'][:10]}", ""]

    # Skill別
    lines.append("## Skill別 通過率")
    skills = data["skills"]
    usage = data["session_usage"]["skills"]
    prev_skills = (previous or {}).get("skills", {})
    if not skills and not usage:
        lines.append("（Skill使用実績なし）")
    else:
        all_names = sorted(set(skills) | set(usage))
        for name in all_names:
            s = skills.get(name)
            call_count = usage.get(name, 0)
            if s is None:
                lines.append(f"- {name}: 呼び出しあり({call_count}回)だが検証結果は未記録")
                continue
            rate_str = _rate_str(s["rate"])
            low_flag = "（参考値・件数少）" if s["low_sample"] else ""
            prev = prev_skills.get(name)
            diff = _diff_pt(prev.get("rate") if prev else None, s["rate"])
            lines.append(
                f"- {name}: {rate_str} ({s['pass']}/{s['total']}){low_flag}{diff}"
                + (f"  呼び出し{call_count}回" if call_count else "")
            )
    lines.append("")

    # MCPサーバー別
    lines.append("## MCPサーバー別")
    mcp = data["mcp_servers"]
    mcp_usage = data["session_usage"]["mcp_servers"]
    if not mcp and not mcp_usage:
        lines.append("（MCP使用実績なし）")
    else:
        all_names = sorted(set(mcp) | set(mcp_usage))
        for name in all_names:
            trust = mcp.get(name, {}).get("trust", "")
            trust_label = f"信頼設定: {trust}" if trust else "信頼設定: なし（承認必須）"
            call_count = mcp_usage.get(name, 0)
            lines.append(f"- {name}: {trust_label}、呼び出し{call_count}回")
        lines.append("")
        lines.append(
            "（MCPは現状verify結果と紐付いた通過率を記録していない — Skillのような"
            "信頼スコアリングは今後の拡張候補）"
        )
    lines.append("")

    # プロジェクト別verify_cmd実績
    lines.append("## プロジェクト別 verify_cmd実績")
    vc = data["verify_cmds"]
    if not vc:
        lines.append("（記録なし）")
    else:
        for project, v in sorted(vc.items()):
            lines.append(f"- {project}: {v['passes']}回通過  最終使用 {v['last_used']}")
    lines.append("")

    return "\n".join(lines)


def run() -> str:
    """集計→スナップショット保存→レポート生成→latest_report.mdへの書き出しまで行う。
    戻り値: レポート本文（呼び出し元がそのまま表示できるように）。"""
    previous = load_previous_snapshot()
    data = collect_all()
    save_snapshot(data)
    report = build_report(data, previous)
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (_HISTORY_DIR / "latest_report.md").write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    print(run())
