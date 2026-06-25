"""subagent.py — OverlayFS隔離によるWorkerサブエージェント実行。

team.py の Worker フェーズから run_subagent_reviewable() で呼ばれる。各実行は:

  1. 専用の作業部屋(workroom)を用意する
       lowerdir = 元のプロジェクト(読み取り専用)
       upperdir = 空の書き込み層
       merged   = 合成ビュー（サブエージェントの作業ディレクトリ）
  2. unshare -U -m -r で非特権ユーザー名前空間を作り、その中で overlay をマウントし
     `python3 -m mimic_tui --auto-prompt "<task>"` を MIMIC_CWD=<merged> で起動する
  3. サブエージェントは Git に一切触れない（コミットは team.py 側が行う）
  4. プロセスが終了すると名前空間ごとマウントが自動的に解除される（後始末不要）
  5. upperdir の中身が「変更点の差分」となる。run_subagent_reviewable() は
     成功時に upperdir を破棄せず (result, upper, base) を返すので、
     呼び出し側（Supervisorのレビュー後）が apply_subagent_changes() で
     プロジェクトに適用するか、cleanup_subagent() で破棄するかを選ぶ。
"""
from __future__ import annotations

import difflib
import os
import re
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

from .utils import log, safe_print, C

_VERIFY_MARKER    = "===MIMIC_VERIFY_START==="
_FINAL_MARKER     = "===MIMIC_FINAL==="
_TIMEOUT_SEC      = 1800   # 30分
_VERIFY_TIMEOUT_SEC = 300  # 5分
_MAX_RESUME_ATTEMPTS = 3

# mimic_tui パッケージの実体があるディレクトリ（python3 -m mimic_tui の起点）
_LAUNCHER_DIR = Path(__file__).resolve().parent.parent


@dataclass
class SubagentResult:
    task: str
    ok: bool
    changed_files: list[str] = field(default_factory=list)
    summary: str = ""
    raw_tail: str = ""   # デバッグ用: サブエージェント標準出力の末尾
    verify_exit: Optional[int] = None   # verify_cmd を指定した場合の終了コード
    verify_output: str = ""             # verify_cmd の出力（末尾）


def _force_rmtree(path: Path) -> None:
    """overlay 内部の work ディレクトリ（mode 0000 で生成される）も含めて確実に削除する。"""
    for root, dirs, _files in os.walk(path):
        for name in dirs:
            try:
                os.chmod(os.path.join(root, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


_APPLY_EXCLUDED_PATHS = {".mimic_checkpoint.json"}  # upperdir ルート直下からの相対パスで指定する

def _changed_files(upper: Path) -> list[str]:
    """upperdir を走査し、変更/新規ファイルの相対パス一覧を返す（削除マーカー・内部管理ファイルは除外）。"""
    changed = []
    for p in sorted(upper.rglob("*")):
        if p.is_dir():
            continue
        rel = str(p.relative_to(upper))
        if rel in _APPLY_EXCLUDED_PATHS:
            continue  # Worker内部管理ファイル（ルート直下のみ対象。プロジェクト内の同名ファイルは除外しない）
        try:
            st = p.lstat()
        except OSError:
            continue
        if stat.S_ISCHR(st.st_mode):
            continue  # overlay の whiteout（削除マーカー）
        changed.append(rel)
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


def _append_verify_section(summary: str, verify_cmd: str, verify_exit: Optional[int],
                            verify_output: str, max_output_chars: int = 2000) -> str:
    """verify_cmd が指定されていた場合、その実行結果セクションを summary に追記する。"""
    if not verify_cmd:
        return summary
    tail = verify_output[-max_output_chars:]
    if len(verify_output) > max_output_chars:
        tail = f"…（出力 {len(verify_output)} 文字中 末尾 {max_output_chars} 文字のみ表示）\n" + tail
    section = (
        f"\n\n[検証コマンド実行結果]\n"
        f"コマンド: {verify_cmd}\n"
        f"終了コード: {verify_exit if verify_exit is not None else '(取得できませんでした)'}\n"
        f"{tail}"
    )
    return summary + section


def apply_subagent_changes(upper: Path, lower: Path, changed_files: list[str]) -> None:
    """upperdir の変更（新規・更新ファイル）を project_dir(lower) に反映し、
    upperdir 上の whiteout（削除マーカー）に対応するファイルを lower から削除する。"""
    for rel in changed_files:
        src = upper / rel
        dst = lower / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    for p in upper.rglob("*"):
        try:
            st = p.lstat()
        except OSError:
            continue
        if not stat.S_ISCHR(st.st_mode):
            continue
        target = lower / p.relative_to(upper)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink()


def cleanup_subagent(base: Path) -> None:
    """run_subagent_reviewable が確保した一時ディレクトリを破棄する。"""
    _force_rmtree(base)


def run_subagent_reviewable(task: str, project_dir: str, label: str = "single",
                              base: Optional[Path] = None,
                              trace_id: Optional[str] = None,
                              verify_cmd: str = "",
                              provider: Optional[str] = None,
                              model: Optional[str] = None,
                              ) -> tuple[SubagentResult, Optional[Path], Optional[Path]]:
    """Worker を OverlayFS 隔離下で同期実行する。

    成功時は upperdir をすぐには破棄せず (result, upper, base) を返す。
    呼び出し側はレビュー結果に応じて apply_subagent_changes() してから
    cleanup_subagent(base) を呼ぶこと（採用しない場合は cleanup のみ）。
    例外・タイムアウト時は内部で破棄して (result, None, None) を返す。

    `base` を渡すと、前回までの upperdir（＝それまでの変更内容）を温存したまま
    overlay を再マウントして続きから実行する（「やり直し」ではなく「続き」）。

    `verify_cmd` を渡すと、Worker のエージェント実行が終わった直後・同じ overlay
    マウント上で `timeout {_VERIFY_TIMEOUT_SEC} bash -c <verify_cmd>` を実行し、
    その終了コード・出力を SubagentResult.verify_exit / verify_output に格納する。
    空文字列の場合はこのステップ自体を行わない（従来と同じ動作）。
    """
    if base is None:
        base = Path(tempfile.mkdtemp(prefix=f"mimic_subagent_{label}_"))
    lower  = Path(project_dir).resolve()
    upper  = base / "upper"
    work   = base / "work"
    merged = base / "merged"
    try:
        for d in (upper, work, merged):
            d.mkdir(parents=True, exist_ok=True)

        # workdir は毎回クリーンな状態でないとマウントが失敗するため、
        # スクリプト内で削除・再作成してからマウントする（upper/merged は保持）。
        mount_cmd = (
            f"rm -rf {shlex.quote(str(work))} && "
            f"mkdir -p {shlex.quote(str(work))} && "
            f"mount -t overlay overlay "
            f"-o lowerdir={shlex.quote(str(lower))},"
            f"upperdir={shlex.quote(str(upper))},"
            f"workdir={shlex.quote(str(work))} "
            f"{shlex.quote(str(merged))}"
        )
        # --auto-prompt は _build_components を経由しないため MIMIC_CWD は効かない
        # （agent.cwd は単に起動時の OS cwd になる）。そこで cwd 自体を merged にし、
        # モジュール解決だけ PYTHONPATH で実体ディレクトリを指す。
        trace_env = f"MIMIC_TRACE_ID={shlex.quote(trace_id)} " if trace_id else ""
        model_env = ""
        if provider and model:
            model_env = (
                f"MIMIC_PROVIDER={shlex.quote(provider)} "
                f"MIMIC_MODEL={shlex.quote(model)} "
            )

        agent_cmd = (
            f"cd {shlex.quote(str(merged))} && "
            f"PYTHONPATH={shlex.quote(str(_LAUNCHER_DIR))}:$PYTHONPATH "
            f"MIMIC_NO_AUTOGIT=1 "
            f"{trace_env}"
            f"{model_env}"
            f"python3 -m mimic_tui --auto-prompt {shlex.quote(task)}"
        )
        inner_cmd = f"{agent_cmd}; agent_exit=$?"
        if verify_cmd:
            inner_cmd += (
                f"; echo {_VERIFY_MARKER}"
                f"; timeout {_VERIFY_TIMEOUT_SEC} bash -c {shlex.quote(verify_cmd)}"
                f"; echo MIMIC_VERIFY_EXIT=$?"
            )
        inner_cmd += "; exit $agent_exit"
        script = f"{mount_cmd} && {inner_cmd}"

        # ── 実行（クラッシュ時は _MAX_RESUME_ATTEMPTS 回まで再開）──
        prefix = f"  {C.gray(f'[Worker:{label}]')} "
        stdout_all: list[str] = []
        timed_out = threading.Event()
        completed = False

        for resume_attempt in range(_MAX_RESUME_ATTEMPTS + 1):
            if resume_attempt > 0:
                safe_print(C.yellow(
                    f"{prefix}⚠ 予期せず終了 → チェックポイントから再開"
                    f" ({resume_attempt}/{_MAX_RESUME_ATTEMPTS})"
                ), flush=True)
                # overlay を再マウントして同一 base/upper の続きから起動
                timed_out.clear()

            proc = subprocess.Popen(
                ["unshare", "-U", "-m", "-r", "bash", "-c", script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                bufsize=1, start_new_session=True,
            )

            proc_done = threading.Event()

            def _watchdog(p=proc, pd=proc_done):
                if not pd.wait(_TIMEOUT_SEC):
                    timed_out.set()
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            threading.Thread(target=_watchdog, daemon=True).start()

            stdout_chunks: list[str] = []
            for raw_line in proc.stdout:
                stdout_chunks.append(raw_line)
                safe_print(prefix + raw_line.rstrip("\n"), flush=True)
            proc.wait()
            proc_done.set()

            stdout_all.extend(stdout_chunks)
            run_stdout = "".join(stdout_chunks)
            completed = _FINAL_MARKER in run_stdout

            if timed_out.is_set():
                break
            if completed:
                break
            # チェックポイントがなければ再開しても意味がない
            cp_file = merged / ".mimic_checkpoint.json"
            if not cp_file.exists():
                break

        stdout = "".join(stdout_all)

        if timed_out.is_set():
            _force_rmtree(base)
            return SubagentResult(
                task=task, ok=False,
                summary=f"タイムアウト（{_TIMEOUT_SEC}秒）のため強制終了しました。",
            ), None, None

        ok = completed
        changed = _changed_files(upper)
        summary = _summarize(lower, upper, changed)

        # Worker の最終回答テキストを stdout から抽出してサマリーに前置する。
        # ファイル変更がない読み取り専用タスクでも回答内容が Director に届くようにする。
        _marker_line = _FINAL_MARKER + "\n"
        if _marker_line in stdout:
            _after_final = stdout.partition(_marker_line)[2]
            if (_VERIFY_MARKER + "\n") in _after_final:
                _after_final = _after_final.partition(_VERIFY_MARKER + "\n")[0]
            _final_text = _after_final.strip()
            if _final_text:
                summary = "[Workerの最終回答]\n" + _final_text + "\n\n" + summary

        if not ok:
            attempts_info = (
                f"再開試行: {resume_attempt}/{_MAX_RESUME_ATTEMPTS}回、"
                if resume_attempt > 0 else ""
            )
            summary = (
                f"⚠ Workerが完了シグナルなしで終了しました"
                f"（{attempts_info}exit={proc.returncode}）。\n" + summary
            )

        verify_exit: Optional[int] = None
        verify_output = ""
        if verify_cmd:
            # resume試行ごとにverifyが毎回走るため、stdout中に複数回マーカーが
            # 出現しうる。最後（=完成した試行）の結果を使う必要があるのでrpartition。
            agent_output, _, verify_part = stdout.rpartition(_VERIFY_MARKER + "\n")
            verify_output = verify_part
            m = re.search(r"MIMIC_VERIFY_EXIT=(\d+)", verify_part)
            if m:
                verify_exit = int(m.group(1))
                verify_output = verify_part[:m.start()]
            summary = _append_verify_section(summary, verify_cmd, verify_exit, verify_output)

        result = SubagentResult(
            task=task, ok=ok, changed_files=changed, summary=summary,
            raw_tail=stdout[-2000:],
            verify_exit=verify_exit, verify_output=verify_output,
        )
        return result, upper, base
    except Exception as exc:
        log.error({"event": "subagent_error", "task": task, "error": str(exc)})
        _force_rmtree(base)
        return SubagentResult(task=task, ok=False, summary=f"実行エラー: {exc}"), None, None


