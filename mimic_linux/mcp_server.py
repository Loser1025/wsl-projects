"""
mcp_server.py  —  mimic_linux MCP Server (Full-Agent Edition)
==============================================================
Claude Code (推論) ← MCP → このサーバー → mimic_linux フルエージェント

Claude の役割: ユーザー意図を理解して agent_run を呼ぶだけ
mimic_linux の役割: OpenRouter ReAct ループ + AutoGit + 全ツール実行

起動: python -m mimic_linux.mcp_server  (tamalabo/ ディレクトリで実行)
      Claude Code の settings.json からは以下のように設定する:
        "command": "python",
        "args": ["-m", "mimic_linux.mcp_server"],
        "cwd": "<tamalabo のフルパス>"
"""

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

V4_DIR = Path(__file__).parent.parent

# ── MCP ─────────────────────────────────────────────────────────
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("mimic")

# ANSI エスケープコード除去
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ════════════════════════════════════════════════════════════════
# ツール一覧
# ════════════════════════════════════════════════════════════════
@server.list_tools()
async def list_tools() -> list[Tool]:
    result: list[Tool] = []

    # ── ① メインツール: フルエージェント実行（最優先で使う）────────
    result.append(Tool(
        name="agent_run",
        description=(
            "【最優先】タスクを mimic_linux のフルエージェントに委譲して実行する。\n"
            "\n"
            "内部で実行されること:\n"
            "  • AutoGit バックアップ（タスク前に自動コミット）\n"
            "  • OpenRouter ReAct ループ（Thought→Action→Observation 最大60ステップ）\n"
            "  • ファイル編集・bash・Web検索 など全ツール自動実行\n"
            "  • 並列ツール実行対応\n"
            "  • AutoGit チェックポイント（書き込み後に自動コミット）\n"
            "\n"
            "使い分け:\n"
            "  agent_run   → コーディング・ファイル編集・調査・マルチステップ作業\n"
            "  agent_plan  → 複雑なプロジェクト（計画→並列実行→レビュー）\n"
            "  個別ツール  → 単純な読み取り確認のみ"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "エージェントに実行させるタスクの詳細な説明（日本語OK）"
                },
                "working_dir": {
                    "type": "string",
                    "description": "作業ディレクトリのフルパス。省略時はプロジェクトフォルダ"
                },
                "timeout": {
                    "type": "integer",
                    "description": "タイムアウト秒数（デフォルト 600 = 10分）",
                    "default": 600
                }
            },
            "required": ["task"]
        }
    ))

    # ── ② ターミナル起動（長時間・ユーザー監視が必要な作業）────────
    result.append(Tool(
        name="agent_terminal",
        description=(
            "mimic_linux を新しいターミナルウィンドウで起動する（インタラクティブモード）。\n"
            "30分以上かかる作業・ユーザーが途中で確認したい場合に使う。\n"
            "このツールは起動だけして即返す（結果待ちなし）。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "ターミナルに表示する初期タスクメモ（参照用）"
                },
                "working_dir": {
                    "type": "string",
                    "description": "作業ディレクトリのフルパス"
                }
            },
            "required": ["task"]
        }
    ))

    return result


# ════════════════════════════════════════════════════════════════
# ツール実行
# ════════════════════════════════════════════════════════════════
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_event_loop()

    if name == "agent_run":
        result = await loop.run_in_executor(
            None, _agent_run,
            arguments.get("task", ""),
            arguments.get("working_dir"),
            arguments.get("timeout", 600),
            False,  # plan_mode=False
        )
        return [TextContent(type="text", text=result)]

    if name == "agent_terminal":
        result = _agent_terminal(
            arguments.get("task", ""),
            arguments.get("working_dir"),
        )
        return [TextContent(type="text", text=result)]

    return [TextContent(type="text", text=f"未知のツール: {name}")]


# ════════════════════════════════════════════════════════════════
# agent_run 実装
# ════════════════════════════════════════════════════════════════
def _agent_run(task: str, working_dir: str | None,
               timeout: int, plan_mode: bool) -> str:
    """
    mimic_linux を --auto-prompt で起動して結果を返す。
    """
    cwd  = working_dir or str(V4_DIR)
    py   = sys.executable
    flag = "--auto-prompt"
    task_arg = f"/plan {task}" if plan_mode else task

    env = {
        **os.environ,
        "MIMIC_CWD": cwd,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    DONE_MARKER = "===MIMIC_DONE==="
    import threading

    try:
        proc = subprocess.Popen(
            [py, "-m", "mimic_linux", flag, task_arg],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except Exception as e:
        return f"mimic_linux 起動エラー: {type(e).__name__}: {e}"

    result_lines: list[str] = []
    done_event = threading.Event()

    def _read():
        collecting = True
        try:
            for raw in proc.stdout:
                clean = strip_ansi(raw)
                if DONE_MARKER in clean:
                    done_event.set()
                    collecting = False
                    continue
                if collecting:
                    result_lines.append(clean)
        finally:
            done_event.set()

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()

    if done_event.wait(timeout=timeout):
        answer = "".join(result_lines).strip()
        return answer or "(mimic_linux の出力なし)"
    else:
        proc.kill()
        proc.wait()
        partial = "".join(result_lines).strip()
        return (
            f"タイムアウト ({timeout}秒)\n"
            f"途中出力:\n{partial[-2000:] if partial else '(なし)'}\n\n"
            "長時間タスクは agent_terminal を使ってターミナルで実行してください。"
        )


# ════════════════════════════════════════════════════════════════
# agent_terminal 実装
# ════════════════════════════════════════════════════════════════
def _agent_terminal(task: str, working_dir: str | None) -> str:
    cwd = working_dir or str(V4_DIR)
    py  = sys.executable
    task_preview = task[:300].replace('"', "'")
    return (
        "ターミナル自動起動は無効化されています。\n"
        f"手動で次のコマンドを実行してください:\n"
        f"  cd {cwd} && {py} -m mimic_linux\n\n"
        f"以下のタスクをターミナルに貼り付けてください:\n"
        f"{'─'*50}\n{task_preview}\n{'─'*50}"
    )


# ════════════════════════════════════════════════════════════════
# エントリポイント
# ════════════════════════════════════════════════════════════════
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
