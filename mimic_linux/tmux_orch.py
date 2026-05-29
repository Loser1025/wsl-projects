"""
tmux_orch.py — tmux セッション・ペイン管理
TmuxPane:    1つのペインへの送信・内容取得
TmuxSession: セッション全体の管理とレイアウト構築
"""
from __future__ import annotations

import shutil
import subprocess
import time
from typing import Optional


def _tmux(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """tmux コマンドを実行して CompletedProcess を返す。"""
    return subprocess.run(
        ["tmux"] + list(args),
        capture_output=True,
        text=True,
        check=check,
    )


# ── TmuxPane ─────────────────────────────────────────────────────

class TmuxPane:
    """
    tmux の1ペインを表す。
    target 書式: "session:window.pane"  例: "mimic:0.1"
    """

    def __init__(self, target: str):
        self.target = target

    def send(self, text: str, enter: bool = True) -> None:
        """ペインにテキストを送信する。"""
        args = ["send-keys", "-t", self.target, text]
        if enter:
            args.append("Enter")
        _tmux(*args)

    def capture(self, history: int = 0) -> str:
        """ペインの現在の表示内容を文字列で返す。"""
        args = ["capture-pane", "-t", self.target, "-p"]
        if history:
            args += ["-S", str(-history)]
        r = _tmux(*args)
        return r.stdout

    def set_title(self, title: str) -> None:
        """ペインのタイトルを設定する。"""
        _tmux("select-pane", "-t", self.target, "-T", title)

    def kill(self) -> None:
        """ペインを強制終了する。"""
        _tmux("kill-pane", "-t", self.target)

    def is_alive(self) -> bool:
        r = _tmux("list-panes", "-t", self.target)
        return r.returncode == 0


# ── TmuxSession ───────────────────────────────────────────────────

class TmuxSession:
    """
    mimic_linux 用 tmux セッションを管理する。

    レイアウト（--tmux 起動時に自動構築）:
    ┌───────────────────────────────────┐
    │  [0] メイン（インタラクティブ）    │
    ├───────────────────────────────────┤
    │  [1] Monitor（1秒ごとに更新）     │
    └───────────────────────────────────┘

    Monitor ペインは画面下部 30% を占有する。
    """

    MONITOR_PANE_HEIGHT_PCT = 30  # Monitor ペインの高さ割合 (%)

    def __init__(self, session_name: str = "mimic"):
        self.name = session_name
        self._monitor_pane: Optional[TmuxPane] = None

    # ── セッション存在確認・作成 ────────────────────────────────

    def exists(self) -> bool:
        r = _tmux("has-session", "-t", self.name)
        return r.returncode == 0

    def ensure(self) -> None:
        """セッションがなければ新規作成する（detach 状態）。"""
        if not self.exists():
            _tmux("new-session", "-d", "-s", self.name)

    def attach(self) -> None:
        """セッションにアタッチする（フォアグラウンド）。"""
        subprocess.run(["tmux", "attach", "-t", self.name])

    def kill(self) -> None:
        """セッション全体を終了する。"""
        _tmux("kill-session", "-t", self.name)

    # ── Monitor ペイン管理 ──────────────────────────────────────

    def get_or_create_monitor_pane(self) -> TmuxPane:
        """
        Monitor ペインを取得または新規作成して返す。
        既存のセッションの場合は画面下部を split して確保する。
        """
        if self._monitor_pane and self._monitor_pane.is_alive():
            return self._monitor_pane

        self.ensure()

        # 現在のペイン数を確認
        r = _tmux("list-panes", "-t", self.name, "-F", "#{pane_id}")
        panes = [p.strip() for p in r.stdout.splitlines() if p.strip()]

        if len(panes) < 2:
            # Monitor ペインを下部に split で追加
            r2 = _tmux(
                "split-window", "-t", self.name,
                "-v",                                          # 垂直分割
                "-p", str(self.MONITOR_PANE_HEIGHT_PCT),      # 下部 N%
                "-d",                                          # 作成後にフォーカスを移さない
                "cat",                                        # 何もしないプレースホルダ
            )
            # 作成直後のペインID を取得
            r3 = _tmux("list-panes", "-t", self.name, "-F", "#{pane_id}")
            new_panes = [p.strip() for p in r3.stdout.splitlines() if p.strip()]
            # 一番最後が新しいペイン
            monitor_id = new_panes[-1] if new_panes else f"{self.name}:0.1"
        else:
            monitor_id = panes[-1]

        target = f"{self.name}:{monitor_id}"
        pane   = TmuxPane(target)
        pane.set_title("mimic-monitor")
        # 初期化: clear
        _tmux("send-keys", "-t", target, "clear", "Enter")
        self._monitor_pane = pane
        return pane

    # ── ユーティリティ ──────────────────────────────────────────

    @staticmethod
    def available() -> bool:
        """tmux がシステムに存在するか確認する。"""
        return shutil.which("tmux") is not None

    def list_panes(self) -> list[str]:
        r = _tmux("list-panes", "-t", self.name, "-F", "#{pane_id} #{pane_title}")
        return r.stdout.splitlines()
