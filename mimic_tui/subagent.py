"""subagent.py — OverlayFS隔離による単一/並列サブエージェント委任。

delegate_to_subagent / delegate_to_subagent_parallel は、エージェントが自身の
判断で呼び出せる同期ツール。各サブエージェントは:

  1. 専用の作業部屋(workroom)を用意する
       lowerdir = 元のプロジェクト(読み取り専用)
       upperdir = 空の書き込み層
       merged   = 合成ビュー（サブエージェントの作業ディレクトリ）
  2. unshare -U -m -r で非特権ユーザー名前空間を作り、その中で overlay をマウントし
     `python3 -m mimic_tui --auto-prompt "<task>"` を MIMIC_CWD=<merged> で起動する
  3. サブエージェントは Git に一切触れない（コミットは常に親が行う）
  4. プロセスが終了すると名前空間ごとマウントが自動的に解除される（後始末不要）
  5. upperdir の中身がそのまま「変更点の差分」になる — 親はこれを検査し、
     採用するかどうか・どう統合するかを判断したうえで自身の AutoGit でコミットする

ロールバック = 一時ディレクトリの削除（常に finally で実行する）。
"""
from __future__ import annotations

import difflib
import os
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .utils import log

_DONE_MARKER  = "===MIMIC_DONE==="
_TIMEOUT_SEC  = 1800  # 30分

# mimic_tui パッケージの実体があるディレクトリ（python3 -m mimic_tui の起点）
_LAUNCHER_DIR = Path(__file__).resolve().parent.parent


@dataclass
class SubagentResult:
    task: str
    ok: bool
    changed_files: list[str] = field(default_factory=list)
    summary: str = ""
    raw_tail: str = ""   # デバッグ用: サブエージェント標準出力の末尾


def _force_rmtree(path: Path) -> None:
    """overlay 内部の work ディレクトリ（mode 0000 で生成される）も含めて確実に削除する。"""
    for root, dirs, _files in os.walk(path):
        for name in dirs:
            try:
                os.chmod(os.path.join(root, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def _changed_files(upper: Path) -> list[str]:
    """upperdir を走査し、変更/新規ファイルの相対パス一覧を返す（削除マーカーは除外）。"""
    changed = []
    for p in sorted(upper.rglob("*")):
        if p.is_dir():
            continue
        try:
            st = p.lstat()
        except OSError:
            continue
        if stat.S_ISCHR(st.st_mode):
            continue  # overlay の whiteout（削除マーカー）
        changed.append(str(p.relative_to(upper)))
    return changed


def _summarize(lower: Path, upper: Path, changed: list[str],
               max_files: int = 20, max_diff_lines: int = 60) -> str:
    """upperdir と元ファイルを突き合わせ、親エージェント向けの差分サマリを作る。"""
    if not changed:
        return "(変更されたファイルはありませんでした)"

    lines = [f"変更ファイル数: {len(changed)}"]
    for rel in changed[:max_files]:
        upper_path = upper / rel
        lower_path = lower / rel
        lines.append(f"\n--- {rel} ---")
        try:
            new_text = upper_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            lines.append("(バイナリ、または読み取り不可)")
            continue

        if lower_path.exists():
            try:
                old_text = lower_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                old_text = ""
            diff = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                n=2, lineterm="",
            ))
            body = "\n".join(diff[:max_diff_lines])
            if len(diff) > max_diff_lines:
                body += f"\n…（差分 {len(diff)} 行中 先頭 {max_diff_lines} 行のみ表示）"
            lines.append(body or "(内容に差分なし)")
        else:
            preview = new_text[:1000]
            if len(new_text) > 1000:
                preview += f"\n…（新規ファイル {len(new_text)} 文字中 先頭1000文字のみ表示）"
            lines.append(f"[新規ファイル]\n{preview}")

    if len(changed) > max_files:
        rest = changed[max_files:]
        head = ", ".join(rest[:10])
        more = " ..." if len(rest) > 10 else ""
        lines.append(f"\n…他 {len(rest)} ファイル（{head}{more}）")
    return "\n".join(lines)


def _run_overlay_subagent(task: str, project_dir: str, label: str) -> SubagentResult:
    """ひとつのサブエージェントを OverlayFS 隔離下で同期実行し、結果を回収する。"""
    base   = Path(tempfile.mkdtemp(prefix=f"mimic_subagent_{label}_"))
    lower  = Path(project_dir).resolve()
    upper  = base / "upper"
    work   = base / "work"
    merged = base / "merged"
    try:
        for d in (upper, work, merged):
            d.mkdir(parents=True, exist_ok=True)

        mount_cmd = (
            f"mount -t overlay overlay "
            f"-o lowerdir={shlex.quote(str(lower))},"
            f"upperdir={shlex.quote(str(upper))},"
            f"workdir={shlex.quote(str(work))} "
            f"{shlex.quote(str(merged))}"
        )
        # --auto-prompt は _build_components を経由しないため MIMIC_CWD は効かない
        # （agent.cwd は単に起動時の OS cwd になる）。そこで cwd 自体を merged にし、
        # モジュール解決だけ PYTHONPATH で実体ディレクトリを指す。
        inner_cmd = (
            f"cd {shlex.quote(str(merged))} && "
            f"PYTHONPATH={shlex.quote(str(_LAUNCHER_DIR))}:$PYTHONPATH "
            f"MIMIC_NO_AUTOGIT=1 "
            f"python3 -m mimic_tui --auto-prompt {shlex.quote(task)}"
        )
        script = f"{mount_cmd} && {inner_cmd}"

        proc = subprocess.Popen(
            ["unshare", "-U", "-m", "-r", "bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            return SubagentResult(
                task=task, ok=False,
                summary=f"タイムアウト（{_TIMEOUT_SEC}秒）のため強制終了しました。",
            )

        ok = (_DONE_MARKER in stdout) and proc.returncode == 0
        changed = _changed_files(upper)
        summary = _summarize(lower, upper, changed)
        if not ok:
            summary = f"⚠ サブエージェントは正常終了しませんでした（exit={proc.returncode}）。\n" + summary
        return SubagentResult(
            task=task, ok=ok, changed_files=changed, summary=summary,
            raw_tail=stdout[-2000:],
        )
    except Exception as exc:
        log.error({"event": "subagent_error", "task": task, "error": str(exc)})
        return SubagentResult(task=task, ok=False, summary=f"実行エラー: {exc}")
    finally:
        # ロールバック/後始末 = 一時ディレクトリの削除のみ
        # （overlay マウントは unshare の名前空間終了時に自動解除される）
        _force_rmtree(base)


def run_subagent(task: str, project_dir: str) -> SubagentResult:
    """単一のサブエージェントに作業を委任し、完了まで同期的に待機する。"""
    return _run_overlay_subagent(task, project_dir, label="single")


def run_subagents_parallel(tasks: list[str], project_dir: str) -> list[SubagentResult]:
    """複数タスクを独立した OverlayFS 隔離下で並列実行し、全完了まで待機する。

    各サブエージェントは完全に独立した作業部屋を持ち、Git にも触れないため、
    競合は構造的に発生しない（"並列"が無料で手に入る所以）。
    """
    results: list[Optional[SubagentResult]] = [None] * len(tasks)

    def _worker(i: int, t: str):
        results[i] = _run_overlay_subagent(t, project_dir, label=f"par{i}")

    threads = [threading.Thread(target=_worker, args=(i, t)) for i, t in enumerate(tasks)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return results  # type: ignore[return-value]
