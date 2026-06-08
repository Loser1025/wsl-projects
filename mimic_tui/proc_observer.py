"""
proc_observer.py — Linux /proc を使ったプロセス監視
ProcessMonitor: バックグラウンドスレッドで /proc/{pid} をポーリング
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── データ型 ─────────────────────────────────────────────────────

@dataclass
class Sample:
    """1回のポーリング結果"""
    timestamp: float
    cpu_user: float    # /proc/{pid}/stat のユーザーCPU時間（累積）
    cpu_sys: float     # /proc/{pid}/stat のシステムCPU時間（累積）
    rss_mb: float      # 常駐メモリ (MB)
    fd_count: int      # オープンFD数
    thread_count: int  # スレッド数


@dataclass
class Summary:
    """ProcessMonitor.stop() が返す集計結果"""
    duration_sec: float
    cpu_max_pct: float    # 観測期間中のCPU最大使用率 (%)
    cpu_avg_pct: float    # 平均CPU使用率 (%)
    rss_start_mb: float   # 開始時メモリ
    rss_max_mb: float     # 最大メモリ
    rss_delta_mb: float   # 開始〜終了のメモリ増分
    fd_max: int
    samples: int          # サンプル数

    def short(self) -> str:
        """インライン表示用の短いサマリ文字列"""
        cpu = f"CPU:max{self.cpu_max_pct:.0f}%"
        mem = f"MEM:{self.rss_delta_mb:+.0f}MB"
        return f"{self.duration_sec:.2f}s | {cpu} | {mem}"


# ── ProcessMonitor ────────────────────────────────────────────────

_JIFFY = None  # CPU クロック (Hz) — 一度だけ読む


def _get_jiffy() -> int:
    global _JIFFY
    if _JIFFY is None:
        try:
            import subprocess
            r = subprocess.run(
                ["getconf", "CLK_TCK"], capture_output=True, text=True
            )
            _JIFFY = int(r.stdout.strip())
        except Exception:
            _JIFFY = 100  # Linux のデフォルト
    return _JIFFY


def _read_stat(pid: int) -> Optional[tuple[float, float, int]]:
    """
    /proc/{pid}/stat から (utime, stime, num_threads) を返す。
    読めない場合は None。
    """
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text.split()
        utime   = float(fields[13]) / _get_jiffy()
        stime   = float(fields[14]) / _get_jiffy()
        threads = int(fields[19])
        return utime, stime, threads
    except Exception:
        return None


def _read_rss(pid: int) -> float:
    """
    /proc/{pid}/status の VmRSS を MB で返す。読めない場合は 0.0。
    """
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                kb = int(line.split()[1])
                return kb / 1024.0
    except Exception:
        pass
    return 0.0


def _count_fds(pid: int) -> int:
    """
    /proc/{pid}/fd のエントリ数を返す。読めない場合は 0。
    """
    try:
        return len(os.listdir(f"/proc/{pid}/fd"))
    except Exception:
        return 0


class ProcessMonitor:
    """
    バックグラウンドスレッドで指定 PID の /proc をポーリングする。

    使い方:
        mon = ProcessMonitor(pid)
        mon.start()
        ... 処理 ...
        summary = mon.stop()
        print(summary.short())
    """

    def __init__(self, pid: int, interval: float = 0.3):
        self.pid      = pid
        self.interval = interval
        self._samples: list[Sample] = []
        self._stop    = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._stop.clear()
        self._samples.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"procmon-{self.pid}"
        )
        self._thread.start()

    def stop(self) -> Summary:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        return self._summarize()

    def current(self) -> Optional[Sample]:
        return self._samples[-1] if self._samples else None

    # ── 内部 ────────────────────────────────────────────────────

    def _poll(self, prev_stat: Optional[tuple], prev_time: float) -> tuple[Sample, tuple, float]:
        now      = time.monotonic()
        rss      = _read_rss(self.pid)
        fds      = _count_fds(self.pid)
        stat     = _read_stat(self.pid)
        threads  = stat[2] if stat else 0

        # CPU 使用率の計算（前回サンプルとの差分）
        cpu_pct = 0.0
        if stat and prev_stat:
            elapsed = now - prev_time
            if elapsed > 0:
                d_user = stat[0] - prev_stat[0]
                d_sys  = stat[1] - prev_stat[1]
                cpu_pct = min(100.0, (d_user + d_sys) / elapsed * 100.0)

        sample = Sample(
            timestamp    = now,
            cpu_user     = stat[0] if stat else 0.0,
            cpu_sys      = stat[1] if stat else 0.0,
            rss_mb       = rss,
            fd_count     = fds,
            thread_count = threads,
        )
        return sample, (stat[0], stat[1]) if stat else (0.0, 0.0), now

    def _loop(self):
        prev_stat: Optional[tuple] = None
        prev_time = time.monotonic()

        while not self._stop.is_set():
            try:
                sample, prev_stat, prev_time = self._poll(prev_stat, prev_time)
                self._samples.append(sample)
            except Exception:
                pass
            self._stop.wait(self.interval)

    def _summarize(self) -> Summary:
        s = self._samples
        if not s:
            return Summary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)

        duration = s[-1].timestamp - s[0].timestamp

        # CPU 使用率を差分から再計算
        cpu_pcts: list[float] = []
        jiffy = _get_jiffy()
        for i in range(1, len(s)):
            elapsed = s[i].timestamp - s[i - 1].timestamp
            if elapsed > 0:
                d = (s[i].cpu_user + s[i].cpu_sys) - (s[i-1].cpu_user + s[i-1].cpu_sys)
                cpu_pcts.append(min(100.0, d / elapsed * 100.0))

        cpu_max = max(cpu_pcts, default=0.0)
        cpu_avg = sum(cpu_pcts) / len(cpu_pcts) if cpu_pcts else 0.0
        rss_vals = [x.rss_mb for x in s]

        return Summary(
            duration_sec  = duration,
            cpu_max_pct   = cpu_max,
            cpu_avg_pct   = cpu_avg,
            rss_start_mb  = rss_vals[0],
            rss_max_mb    = max(rss_vals),
            rss_delta_mb  = rss_vals[-1] - rss_vals[0],
            fd_max        = max(x.fd_count for x in s),
            samples       = len(s),
        )

