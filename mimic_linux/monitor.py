"""
monitor.py — tmux Monitor ペインへのリアルタイムダッシュボード描画

Python → /tmp/mimic_monitor.ansi に書き込み（1秒ごと）
tmux  → watch -n 1 -c cat /tmp/mimic_monitor.ansi で表示
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .tmux_orch import TmuxPane
from .monitoring import ToolCallLog, ToolCallRecord, MonitoringToolRegistry
from .proc_observer import SystemMonitor


# ── ANSI カラー ───────────────────────────────────────────────────

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

_W   = 62
_TMP = Path("/tmp/mimic_monitor.ansi")

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def _bar(pct: float, width: int = 18) -> str:
    filled = int(width * min(pct, 100) / 100)
    color  = _RED if pct >= 90 else (_YLW if pct >= 75 else _RG)
    return f"{color}{'█' * filled}{_RGD}{'░' * (width - filled)}{_RST}"


def _pct(pct: float) -> str:
    color = _RED if pct >= 90 else (_YLW if pct >= 75 else _RG)
    return f"{color}{pct:5.1f}%{_RST}"


# ── MonitorDashboard ──────────────────────────────────────────────

class MonitorDashboard:
    """
    1秒ごとにダッシュボードを /tmp/mimic_monitor.ansi に書き込む。
    tmux Monitor ペインは watch -n 1 -c cat <file> でそれを表示する。

    ╔══════════════════════════════════════════════════════════════╗
    ║  MIMIC LINUX — MONITOR  2026-05-29 15:30:42                ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  CPU [████████░░░░░░░░░░]  38.2%  Load: 1.24              ║
    ║  MEM [█████████████░░░░░]  64.1%  3.2/5.0 GB              ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  モデル  : gemini-2.0-flash        経過: 00:12:34          ║
    ║  作業Dir : /home/loser/wsl-projects                        ║
    ║  実行中  : run_bash ⠋                                      ║
    ║  履歴数  : 24 メッセージ                                    ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  ツール: 14回  エラー: 0回  合計: 32.4s                    ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  直近の呼び出し:                                            ║
    ║  ✓ run_bash       2.30s | CPU:max45% | MEM:+12MB          ║
    ║  ✓ read_file      0.02s | CPU:max 2% | MEM: +0MB          ║
    ╚══════════════════════════════════════════════════════════════╝
    """

    REFRESH_INTERVAL = 1.0
    _SPINNER_FRAMES  = ["⠋", "⠙", "⠸", "⠴", "⠦", "⠇"]

    def __init__(
        self,
        pane:         TmuxPane,
        tool_log:     ToolCallLog,
        sys_mon:      SystemMonitor,
        active_config,
        mon_registry: Optional[MonitoringToolRegistry] = None,
        get_cwd:      Optional[Callable[[], str]]      = None,
        get_history:  Optional[Callable[[], int]]      = None,
    ):
        self._pane        = pane
        self._log         = tool_log
        self._sys         = sys_mon
        self._config      = active_config
        self._registry    = mon_registry   # 実行中ツール取得用
        self._get_cwd     = get_cwd        # agent.cwd を返すコールバック
        self._get_history = get_history    # len(agent.conversation) を返すコールバック
        self._start_time  = time.monotonic()
        self._spin_idx    = 0
        self._stop        = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        self._pane.send(f"watch -n 1 -c cat {_TMP}")
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="monitor-dashboard"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        try:
            _TMP.write_text(f"{_GRY}[Monitor 停止]{_RST}\n", encoding="utf-8")
        except OSError:
            pass

    # ── 内部 ────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.wait(self.REFRESH_INTERVAL):
            self._spin_idx += 1
            try:
                snap    = self._sys.snapshot()
                content = self._render(snap)
                _TMP.write_text(content, encoding="utf-8")
            except Exception:
                pass

    def _row(self, inner: str) -> str:
        """幅 _W のボックス行を生成。ANSI コードを除いた可視幅でパディング。"""
        pad = max(0, _W - 2 - _visible_len(inner))
        return f"{_RGD}║{_RST}{inner}{' ' * pad}{_RGD}║{_RST}"

    def _elapsed_str(self) -> str:
        secs = int(time.monotonic() - self._start_time)
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _render(self, snap) -> str:
        now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        recs = self._log.records
        total   = len(recs)
        errs    = sum(1 for r in recs if r.status == "error")
        t_sum   = sum(r.elapsed for r in recs)
        model   = getattr(self._config, "model", "unknown")
        elapsed = self._elapsed_str()
        cwd     = (self._get_cwd() if self._get_cwd else "-")
        hist    = (self._get_history() if self._get_history else 0)

        # 実行中ツール（スピナー付き）
        cur_tool = self._registry.current_tool if self._registry else None
        if cur_tool:
            spin = self._SPINNER_FRAMES[self._spin_idx % len(self._SPINNER_FRAMES)]
            cur_str = f"{_YLW}{cur_tool}{_RST} {_GRY}{spin}{_RST}"
        else:
            cur_str = f"{_GRY}待機中{_RST}"

        # 罫線
        top = f"{_RGD}╔{'═' * _W}╗{_RST}"
        mid = f"{_RGD}╠{'═' * _W}╣{_RST}"
        bot = f"{_RGD}╚{'═' * _W}╝{_RST}"

        # 作業フォルダ（長い場合は末尾を省略）
        cwd_disp = cwd if len(cwd) <= _W - 14 else "…" + cwd[-(_W - 15):]

        lines = [
            top,
            self._row(f"  {_BLD}{_RG}MIMIC LINUX — MONITOR{_RST}  {_GRY}{now}{_RST}"),
            mid,
            self._row(f"  CPU [{_bar(snap.cpu_percent)}] {_pct(snap.cpu_percent)}  {_GRY}Load:{snap.load_avg_1m:.2f}{_RST}"),
            self._row(f"  MEM [{_bar(snap.mem_percent)}] {_pct(snap.mem_percent)}  {_GRY}{snap.mem_used_mb/1024:.1f}/{snap.mem_total_mb/1024:.1f}GB{_RST}"),
            mid,
            self._row(f"  {_GRY}モデル  :{_RST} {_WHT}{model:<28}{_RST}  {_GRY}経過:{_RST} {_CYN}{elapsed}{_RST}"),
            self._row(f"  {_GRY}作業Dir :{_RST} {_WHT}{cwd_disp}{_RST}"),
            self._row(f"  {_GRY}実行中  :{_RST} {cur_str}"),
            self._row(f"  {_GRY}履歴数  :{_RST} {_MEM}{hist} メッセージ{_RST}"),
            mid,
            self._row(
                f"  {_GRY}ツール:{_RST} {_RG}{total}回{_RST}  "
                f"{_GRY}エラー:{_RST} {(_RED if errs else _GRY)}{errs}回{_RST}  "
                f"{_GRY}合計:{_RST} {_CYN}{t_sum:.1f}s{_RST}"
            ),
            mid,
            self._row(f"  {_BLD}{_WHT}直近の呼び出し:{_RST}"),
        ]

        for rec in recs[-5:]:
            icon = f"{_RG}✓{_RST}" if rec.status == "ok" else f"{_RED}✗{_RST}"
            name = f"{_WHT}{rec.tool:<14}{_RST}"
            t_   = f"{_CYN}{rec.elapsed:5.2f}s{_RST}"
            cpu_ = f"{_YLW}CPU:{rec.cpu_max_pct:3.0f}%{_RST}"
            mem_ = f"{_MEM}MEM:{rec.rss_delta_mb:+5.0f}MB{_RST}"
            lines.append(self._row(f"  {icon} {name} {t_} | {cpu_} | {mem_}"))

        # 最低 5 行をパディング
        while len(lines) < len(lines) + max(0, 5 - len(recs[-5:])):
            lines.append(self._row(""))

        lines.append(bot)
        return "\n".join(lines) + "\n"
