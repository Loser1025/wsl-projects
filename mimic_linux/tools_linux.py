"""
tools_linux.py — Linux専用ツール実装
run_bash: pty対応 / プロセスグループkill / SIGTERM→SIGKILL エスカレーション
"""
from __future__ import annotations

import os
import pty
import signal
import select
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .tools import tools


@tools.register(
    name="run_bash",
    description=(
        "bashコマンドを実行して結果を返す。"
        "結果の先頭が [SUCCESS] なら成功、[FAILURE(ExitCode=N)] なら失敗。"
        "working_directory は必ず明示すること（省略時はPython起動フォルダ）。"
        "パイプ・リダイレクト・複数行コマンドに対応。"
        "タイムアウト時はプロセスグループ全体を終了する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "実行するbashコマンド。パイプ・&&・複数行可。"
            },
            "timeout": {
                "type": "integer",
                "description": "タイムアウト秒数（デフォルト60）",
                "default": 60,
            },
            "working_directory": {
                "type": "string",
                "description": "コマンドを実行する作業フォルダのフルパス（必ず指定）",
            },
            "shell": {
                "type": "string",
                "description": "使用するシェル: bash / sh / zsh（デフォルト: bash）",
                "default": "bash",
            },
        },
        "required": ["command"],
    },
)
def run_bash(
    command: str,
    timeout: int = 60,
    working_directory: Optional[str] = None,
    shell: str = "bash",
) -> str:
    cwd = working_directory or str(Path.cwd())

    # set -euo pipefail: エラー検出を強化
    # LC_ALL=C.UTF-8: 文字化け防止
    wrapped = (
        "export LC_ALL=C.UTF-8\n"
        "export LANG=C.UTF-8\n"
        f"{command}"
    )

    # ── pty で疑似端末確保（npm/git 等の対話的コマンド対応）──
    master_fd, slave_fd = pty.openpty()

    proc = subprocess.Popen(
        [shell, "-c", wrapped],
        cwd=cwd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        preexec_fn=os.setsid,  # 新プロセスグループ（kill時に子プロセスも巻き込む）
    )
    os.close(slave_fd)  # 親側では不要

    output_chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    timed_out = False

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break

            # select でデータ到着を待つ（最大0.1秒）
            try:
                ready, _, _ = select.select([master_fd], [], [], min(remaining, 0.1))
            except (ValueError, OSError):
                break  # master_fd がクローズ済み

            if ready:
                try:
                    chunk = os.read(master_fd, 4096)
                    if chunk:
                        output_chunks.append(chunk)
                    else:
                        break  # EOF
                except OSError:
                    break  # プロセス終了でmaster_fdがクローズ

            # プロセスが終了したか確認
            if proc.poll() is not None:
                # 残りの出力を読み切る
                try:
                    while True:
                        ready, _, _ = select.select([master_fd], [], [], 0.05)
                        if not ready:
                            break
                        chunk = os.read(master_fd, 4096)
                        if chunk:
                            output_chunks.append(chunk)
                        else:
                            break
                except OSError:
                    pass
                break

    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

        if timed_out or proc.poll() is None:
            # SIGTERM → 2秒待機 → SIGKILL（プロセスグループ全体）
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(2)
                if proc.poll() is None:
                    os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()

    # ── 出力を文字列に変換 ──
    raw = b"".join(output_chunks)
    # pty はキャリッジリターンを混入させる場合があるので正規化
    output = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    output = output.strip()

    if timed_out:
        return (
            f"[FAILURE(TIMEOUT)] {timeout}秒経過 — コマンドを分割するか timeout を延ばしてください\n"
            f"作業フォルダ: {cwd}\n"
            + (f"途中出力:\n{output}" if output else "")
        )

    rc = proc.returncode if proc.returncode is not None else -1
    status = "SUCCESS" if rc == 0 else f"FAILURE(ExitCode={rc})"
    parts = [f"[{status}]", f"作業フォルダ: {cwd}"]
    if output:
        parts.append(output)
    return "\n".join(parts)
