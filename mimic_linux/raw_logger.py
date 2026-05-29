"""
raw_logger.py — API 生リクエスト/レスポンスをファイルに書き出す
/tmp/mimic_raw.log に追記し、tmux ペインが tail -f で表示する
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_LOG_PATH = Path("/tmp/mimic_raw.log")

# ANSI カラー（ファイルに書き込む側なので直接埋め込む）
_RG  = "\033[38;2;0;255;0m"
_GRY = "\033[38;2;80;120;80m"
_YLW = "\033[38;2;140;255;0m"
_CYN = "\033[38;2;0;255;180m"
_MEM = "\033[38;2;0;230;255m"
_WHT = "\033[38;2;220;255;220m"
_RED = "\033[38;2;200;50;50m"
_BLD = "\033[1m"
_RST = "\033[0m"

_SEP_REQ  = f"{_RG}{'▶' * 1}{'─' * 58}{_RST}"
_SEP_RESP = f"{_CYN}{'◀' * 1}{'─' * 58}{_RST}"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _write(text: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def _on_event(event: str, data: dict) -> None:
    ts = _ts()

    if event == "request":
        model      = data.get("model", "?")
        msg_count  = data.get("msg_count", 0)
        tool_count = data.get("tool_count", 0)
        last_user  = data.get("last_user", "")

        lines = [
            "",
            _SEP_REQ,
            f"{_GRY}[{ts}]{_RST} {_BLD}{_RG}▶ REQUEST{_RST}  "
            f"{_YLW}{model}{_RST}",
            f"{_GRY}  メッセージ数: {msg_count}  ツール数: {tool_count}{_RST}",
        ]
        if last_user:
            lines.append(f"{_GRY}  最後のUser入力:{_RST}")
            for line in last_user.splitlines()[:8]:
                lines.append(f"  {_WHT}{line}{_RST}")
        _write("\n".join(lines))

    elif event in ("response", "response_stream"):
        text       = data.get("text", "")
        tool_calls = data.get("tool_calls", [])

        lines = [
            _SEP_RESP,
            f"{_GRY}[{ts}]{_RST} {_BLD}{_CYN}◀ RESPONSE{_RST}",
        ]
        if tool_calls:
            lines.append(f"{_GRY}  ツール呼び出し:{_RST}")
            for name in tool_calls:
                if name:
                    lines.append(f"  {_MEM}⚙ {name}{_RST}")
        if text:
            lines.append(f"{_GRY}  テキスト:{_RST}")
            for line in text.splitlines()[:10]:
                lines.append(f"  {_WHT}{line}{_RST}")
            if len(text.splitlines()) > 10:
                lines.append(f"  {_GRY}... (省略){_RST}")
        _write("\n".join(lines))


def enable() -> None:
    """raw_logger を有効化して agent.py のフックに登録する。"""
    # ログファイルをリセット（セッションごとに新しく開始）
    try:
        _LOG_PATH.write_text(
            f"{_GRY}{'─' * 60}\n"
            f"  mimic_linux — Raw API Log  {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"{'─' * 60}{_RST}\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    from .agent import set_raw_log_fn
    set_raw_log_fn(_on_event)
