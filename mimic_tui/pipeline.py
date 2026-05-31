"""
pipeline.py — Unix パイプライン実行ツール
run_bash との違い: pty を使わず stdout をストリーム読みするため
大量出力（ログ解析・find等）でもメモリを圧迫しない。
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

from .tools import tools
from .utils import cache_tool_output

_DEFAULT_TIMEOUT = 120
_MAX_LINES       = 50_000   # これを超えたら打ち切り（安全網）


@tools.register(
    name="run_pipeline",
    description=(
        "Unix パイプライン・コマンドを実行する。"
        "grep/awk/sort/find など大量データを扱う処理に最適。"
        "run_bash との違い: pty を使わず大出力でもメモリを圧迫しない。"
        "結果の先頭が [SUCCESS] なら成功、[FAILURE...] なら失敗。"
        "例: \"grep -r 'ERROR' /var/log | sort | uniq -c | sort -rn | head -20\""
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "実行するシェルコマンド（パイプ・リダイレクト可）。"
                    "例: \"find . -name '*.py' | xargs wc -l | sort -rn | head -10\""
                ),
            },
            "working_directory": {
                "type": "string",
                "description": "作業フォルダのフルパス（必ず指定）",
            },
            "timeout": {
                "type": "integer",
                "description": f"タイムアウト秒数（デフォルト {_DEFAULT_TIMEOUT}）",
                "default": _DEFAULT_TIMEOUT,
            },
            "max_lines": {
                "type": "integer",
                "description": "取得する最大行数（デフォルト 1000）。0 で無制限（上限 50000）。",
                "default": 1000,
            },
        },
        "required": ["command"],
    },
)
def run_pipeline(
    command: str,
    working_directory: Optional[str] = None,
    timeout: int = _DEFAULT_TIMEOUT,
    max_lines: int = 1000,
) -> str:
    cwd      = working_directory or str(Path.cwd())
    max_lines = min(max(0, max_lines), _MAX_LINES) or _MAX_LINES

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            executable="/bin/bash",
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,   # プロセスグループ（タイムアウト kill 用）
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        return f"[FAILURE] パイプライン起動エラー: {e}"

    lines:     list[str] = []
    truncated: bool      = False
    deadline = time.monotonic() + timeout
    timed_out = False

    try:
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                break
            line = proc.stdout.readline()
            if not line:
                # EOF または プロセス終了
                if proc.poll() is not None:
                    break
                time.sleep(0.01)
                continue
            lines.append(line.rstrip("\n"))
            if len(lines) >= max_lines:
                truncated = True
                break
    finally:
        # プロセスグループを kill（子プロセスも含む）
        if proc.poll() is None or timed_out:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(1)
                if proc.poll() is None:
                    os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        proc.wait()

    if timed_out:
        partial = "\n".join(lines)
        result = (
            f"[FAILURE(TIMEOUT)] {timeout}秒経過\n"
            f"作業フォルダ: {cwd}\n"
            + (f"途中出力({len(lines)}行):\n{partial}" if partial else "")
        )
        return cache_tool_output("run_pipeline", result)

    stderr_out = proc.stderr.read().strip() if proc.stderr else ""
    rc         = proc.returncode
    status     = "SUCCESS" if rc == 0 else f"FAILURE(ExitCode={rc})"

    output = "\n".join(lines)
    note   = f"\n[表示上限 {max_lines} 行で打ち切り。続きは max_lines を増やして再実行]" if truncated else ""

    parts = [f"[{status}]", f"作業フォルダ: {cwd}", f"行数: {len(lines)}"]
    if output:
        parts.append(output + note)
    if stderr_out:
        parts.append(f"STDERR:\n{stderr_out}")

    return cache_tool_output("run_pipeline", "\n".join(parts))
