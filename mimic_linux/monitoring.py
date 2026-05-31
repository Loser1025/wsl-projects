"""
monitoring.py — ツール呼び出しの横断監視
MonitoringToolRegistry: ToolRegistry をラップして全ツールを計測
ToolCallLog:            セッション中の呼び出し履歴を蓄積・集計
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .tools import ToolRegistry, UserRejectedWriteError
from .proc_observer import ProcessMonitor, Summary
from .utils import safe_print, C


# ── ToolCallRecord / ToolCallLog ──────────────────────────────────

@dataclass
class ToolCallRecord:
    tool:         str
    args_preview: str       # 引数の短い文字列表現
    elapsed:      float     # 実行時間 (秒)
    status:       str       # "ok" | "error"
    cpu_max_pct:  float
    rss_delta_mb: float
    timestamp:    float     # time.monotonic() 基準

    def one_line(self) -> str:
        icon   = "✓" if self.status == "ok" else "✗"
        timing = f"{self.elapsed:.2f}s"
        cpu    = f"CPU:max{self.cpu_max_pct:.0f}%"
        mem    = f"MEM:{self.rss_delta_mb:+.0f}MB"
        return f"{icon} {self.tool} {timing} | {cpu} | {mem}"


class ToolCallLog:
    """セッション中の全ツール呼び出しを記録する。"""

    def __init__(self):
        self._records: list[ToolCallRecord] = []
        self._lock = threading.Lock()

    def add(self, record: ToolCallRecord) -> None:
        with self._lock:
            self._records.append(record)

    @property
    def records(self) -> list[ToolCallRecord]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def stats_text(self) -> str:
        """
        /stats コマンド用のサマリテキストを返す。
        """
        recs = self.records
        if not recs:
            return "  (このセッションでのツール呼び出しなし)"

        total   = len(recs)
        errors  = sum(1 for r in recs if r.status == "error")
        ok      = total - errors
        elapsed = [r.elapsed for r in recs]
        slowest = max(recs, key=lambda r: r.elapsed)
        # ツール別カウント
        counts: dict[str, int] = {}
        for r in recs:
            counts[r.tool] = counts.get(r.tool, 0) + 1
        top = sorted(counts.items(), key=lambda x: -x[1])[:5]

        lines = [
            f"  呼び出し数 : {total} 回  (成功:{ok}  エラー:{errors})",
            f"  合計時間   : {sum(elapsed):.1f}s",
            f"  平均時間   : {sum(elapsed)/total:.2f}s",
            f"  最遅       : {slowest.tool} {slowest.elapsed:.2f}s",
            f"  使用頻度   : " + "  ".join(f"{n}×{t}" for t, n in top),
        ]
        return "\n".join(lines)

    def recent_text(self, n: int = 10) -> str:
        """直近 n 件の呼び出し履歴を返す。"""
        recs = self.records[-n:]
        return "\n".join(f"  {r.one_line()}" for r in recs) or "  (なし)"


# ── 進捗スピナー ──────────────────────────────────────────────────

class _Spinner:
    """長時間ツール実行中に経過時間を表示するバックグラウンドスレッド。"""
    _FRAMES = ["⠋", "⠙", "⠸", "⠴", "⠦", "⠇"]

    def __init__(self, tool_name: str):
        self._name   = tool_name
        self._start  = time.monotonic()
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
        # スピナー行を消去
        safe_print("\r" + " " * 60 + "\r", end="", flush=True)

    def _run(self):
        i = 0
        while not self._stop.wait(0.15):
            elapsed = time.monotonic() - self._start
            frame   = self._FRAMES[i % len(self._FRAMES)]
            safe_print(
                C.gray(f"\r  {frame} {self._name} 実行中... {elapsed:.1f}s"),
                end="", flush=True,
            )
            i += 1


# ── MonitoringToolRegistry ────────────────────────────────────────

# 長時間とみなす秒数（これを超えるとスピナーを起動）
_SPINNER_THRESHOLD = 2.0

# インライン表示する呼び出し（高頻度の読み取り系は省略可）
_SKIP_INLINE = {"read_tool_cache", "update_scratchpad"}


class MonitoringToolRegistry(ToolRegistry):
    """
    ToolRegistry を継承し、全ツール呼び出しを横断的に計測・表示する。

    agent.py を一切変更せずに監視を挿入できる。
    display_fn を設定するとツール完了後にコールバックが呼ばれる。
    """

    def __init__(
        self,
        base: ToolRegistry,
        log: ToolCallLog,
        display_fn: Optional[Callable[[ToolCallRecord], None]] = None,
    ):
        self._tools        = base._tools
        self._log          = log
        self._display      = display_fn
        self._lock         = threading.Lock()
        self.current_tool: Optional[str] = None

    # specs は親クラスに委譲（_tools を参照共有しているため正しく動く）
    def get_specs(self):
        return super().get_specs()

    def execute(self, tool_name: str, args: dict) -> str:
        """ツールを実行し、計測結果を ToolCallLog に記録する。"""
        args_preview = ", ".join(
            f"{k}={repr(v)[:30]}" for k, v in list(args.items())[:3]
        )

        # ── 実行中ツールを記録（ダッシュボード参照用）──
        self.current_tool = tool_name

        # ── 長時間コマンドにはスピナーを表示 ──
        spinner: Optional[_Spinner] = None
        if tool_name == "run_bash":
            spinner = _Spinner(tool_name)
            spinner.start()

        # ── ProcessMonitor 起動 ──
        pid = os.getpid()
        mon = ProcessMonitor(pid, interval=0.3)
        mon.start()
        t0 = time.perf_counter()

        try:
            result = super().execute(tool_name, args)
            status = "ok"
        except UserRejectedWriteError:
            raise  # 書き込み拒否はそのまま再送出（ReActループを止める）
        except KeyboardInterrupt:
            # Ctrl+C でツール実行中に割り込まれた場合
            # → finally でプロセス・モニターをクリーンアップしてから再送出
            # → run_bash の finally が subprocess を SIGKILL で終了させる
            # → main.py の KeyboardInterrupt ハンドラに届いてプロンプトに戻る
            safe_print(
                C.yellow(f"\n  [割り込み] {tool_name} を中断しました"), flush=True
            )
            raise
        except Exception as e:
            result = f"[エラー] {tool_name}: {e}"
            status = "error"
        finally:
            elapsed  = time.perf_counter() - t0
            summary: Summary = mon.stop()
            self.current_tool = None   # 実行完了
            if spinner:
                spinner.stop()
            # run_bash (PTY実行) 後に端末状態をリセット
            # PTY経由で有効化された代替画面・マウストラッキング等を解除する
            if tool_name == "run_bash":
                import sys as _sys
                _sys.stdout.write(
                    "\033[?1049l"  # 代替画面を終了
                    "\033[?47l"    # 代替画面(古いバリアント)を終了
                    "\033[?1000l"  # X10 マウストラッキングを無効化
                    "\033[?1002l"  # ボタンイベント マウストラッキングを無効化
                    "\033[?1003l"  # 全イベント マウストラッキングを無効化
                    "\033[?1l"     # アプリケーションカーソルキーを無効化
                )
                _sys.stdout.flush()

        # ── ToolCallRecord を生成・記録 ──
        record = ToolCallRecord(
            tool         = tool_name,
            args_preview = args_preview,
            elapsed      = elapsed,
            status       = status,
            cpu_max_pct  = summary.cpu_max_pct,
            rss_delta_mb = summary.rss_delta_mb,
            timestamp    = time.monotonic(),
        )
        self._log.add(record)

        if tool_name not in _SKIP_INLINE and self._display:
            self._display(record)

        return result
