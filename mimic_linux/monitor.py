"""
monitor.py — tmux Monitor ペインへのリアルタイムダッシュボード描画

設計:
  Python側  → /tmp/mimic_monitor.ansi にANSI付きテキストを書き込む（1秒ごと）
  tmux側    → `watch -n 1 -c cat /tmp/mimic_monitor.ansi` でペイン内に表示

printf に ANSI コードを渡す方式は tmux send-keys 経由では壊れるため、
ファイルベース方式を採用する。
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .tmux_orch import TmuxPane
from .monitoring import ToolCallLog, ToolCallRecord
from .proc_observer import SystemMonitor, SystemSnapshot


# ── ANSI カラー定数 ───────────────────────────────────────────────

_RG  = "\033[38;2;0;255;0m"
_RGD = "\033[38;2;0;64;0m"
_WHT = "\033[38;2;220;255;220m"
_GRY = "\033[38;2;80;120;80m"
_CYN = "\033[38;2;0;255;180m"
_YLW = "\033[38;2;140;255;0m"
_MEM = "\033[38;2;0;230;255m"
_RED = "\033[38;2;200;50;50m"
_BLD = "\033[1m"
_RST = "\033[0m"

_W   = 60                                          # ダッシュボード幅
_TMP = Path("/tmp/mimic_monitor.ansi")             # 共有ファイルパス


def _bar(pct: float, width: int = 20, warn: float = 75, crit: float = 90) -> str:
    filled = int(width * min(pct, 100) / 100)
    empty  = width - filled
    color  = _RED if pct >= crit else (_YLW if pct >= warn else _RG)
    return f"{color}{'█' * filled}{_RGD}{'░' * empty}{_RST}"


def _pct_str(pct: float, warn: float = 75, crit: float = 90) -> str:
    color = _RED if pct >= crit else (_YLW if pct >= warn else _RG)
    return f"{color}{pct:5.1f}%{_RST}"


# ── MonitorDashboard ──────────────────────────────────────────────

class MonitorDashboard:
    """
    1秒ごとにダッシュボードを /tmp/mimic_monitor.ansi に書き込む。
    tmux Monitor ペインは `watch -n 1 -c cat <file>` でそれを表示する。

    表示例:
    ╔════════════════════════════════════════════════════════════╗
    ║  MIMIC LINUX — MONITOR  2026-05-29 15:30:42              ║
    ╠════════════════════════════════════════════════════════════╣
    ║  CPU [████████░░░░░░░░░░░░]  38.2%  Load: 1.24          ║
    ║  MEM [█████████████░░░░░░░]  64.1%  3.2/5.0 GB          ║
    ╠════════════════════════════════════════════════════════════╣
    ║  モデル: gemini-2.0-flash                                 ║
    ║  ツール: 14回  エラー: 0回  合計: 32.4s                   ║
    ╠════════════════════════════════════════════════════════════╣
    ║  直近の呼び出し:                                           ║
    ║  ✓ run_bash       2.30s | CPU:max45% | MEM:+12MB        ║
    ║  ✓ read_file      0.02s | CPU:max 2% | MEM: +0MB        ║
    ╚════════════════════════════════════════════════════════════╝
    """

    REFRESH_INTERVAL = 1.0

    def __init__(
        self,
        pane:         TmuxPane,
        tool_log:     ToolCallLog,
        sys_mon:      SystemMonitor,
        active_config,
    ):
        self._pane   = pane
        self._log    = tool_log
        self._sys    = sys_mon
        self._config = active_config
        self._stop   = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """ダッシュボードスレッドを起動し、tmux ペインに watch コマンドを送る。"""
        self._stop.clear()

        # ペインで watch を起動（ファイルを1秒ごとに表示）
        watch_cmd = f"watch -n 1 -c cat {_TMP}"
        self._pane.send(watch_cmd)

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="monitor-dashboard"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        # 終了メッセージを書き込む
        try:
            _TMP.write_text(f"{_GRY}[Monitor 停止]{_RST}\n", encoding="utf-8")
        except OSError:
            pass

    # ── 内部 ────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.wait(self.REFRESH_INTERVAL):
            try:
                snap    = self._sys.snapshot()
                content = self._render(snap)
                _TMP.write_text(content, encoding="utf-8")
            except Exception:
                pass

    def _row(self, inner: str) -> str:
        """幅 _W のボックス1行を返す。inner の可視文字幅を _W - 2 に合わせる。"""
        # ANSIコードを除いた可視文字数を計算
        import re
        visible = re.sub(r"\033\[[0-9;]*m", "", inner)
        pad = max(0, _W - 2 - len(visible))
        return f"{_RGD}║{_RST}{inner}{' ' * pad}{_RGD}║{_RST}"

    def _render(self, snap: SystemSnapshot) -> str:
        now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        recs   = self._log.records
        total  = len(recs)
        errs   = sum(1 for r in recs if r.status == "error")
        t_sum  = sum(r.elapsed for r in recs)
        model  = getattr(self._config, "model", "unknown")

        hline_top = f"{_RGD}╔{'═' * _W}╗{_RST}"
        hline_mid = f"{_RGD}╠{'═' * _W}╣{_RST}"
        hline_bot = f"{_RGD}╚{'═' * _W}╝{_RST}"

        title = f"  {_BLD}{_RG}MIMIC LINUX — MONITOR{_RST}  {_GRY}{now}{_RST}"

        cpu_bar  = _bar(snap.cpu_percent)
        mem_bar  = _bar(snap.mem_percent)
        mem_gb   = f"{snap.mem_used_mb/1024:.1f}/{snap.mem_total_mb/1024:.1f}GB"

        cpu_line = f"  CPU [{cpu_bar}] {_pct_str(snap.cpu_percent)}  {_GRY}Load:{snap.load_avg_1m:.2f}{_RST}"
        mem_line = f"  MEM [{mem_bar}] {_pct_str(snap.mem_percent)}  {_GRY}{mem_gb}{_RST}"

        model_line = f"  {_GRY}モデル:{_RST} {_WHT}{model}{_RST}"
        stat_line  = (
            f"  {_GRY}ツール:{_RST} {_RG}{total}回{_RST}  "
            f"{_GRY}エラー:{_RST} {(_RED if errs else _GRY)}{errs}回{_RST}  "
            f"{_GRY}合計:{_RST} {_CYN}{t_sum:.1f}s{_RST}"
        )
        recent_header = f"  {_BLD}{_WHT}直近の呼び出し:{_RST}"

        recent_rows = []
        for rec in recs[-5:]:
            icon = f"{_RG}✓{_RST}" if rec.status == "ok" else f"{_RED}✗{_RST}"
            name = f"{_WHT}{rec.tool:<14}{_RST}"
            t_   = f"{_CYN}{rec.elapsed:5.2f}s{_RST}"
            cpu_ = f"{_YLW}CPU:{rec.cpu_max_pct:3.0f}%{_RST}"
            mem_ = f"{_MEM}MEM:{rec.rss_delta_mb:+5.0f}MB{_RST}"
            recent_rows.append(f"  {icon} {name} {t_} | {cpu_} | {mem_}")

        # 最低 5 行を空行でパディング
        while len(recent_rows) < 5:
            recent_rows.append("")

        lines = [
            hline_top,
            self._row(title),
            hline_mid,
            self._row(cpu_line),
            self._row(mem_line),
            hline_mid,
            self._row(model_line),
            self._row(stat_line),
            hline_mid,
            self._row(recent_header),
            *[self._row(r) for r in recent_rows],
            hline_bot,
        ]
        return "\n".join(lines) + "\n"
