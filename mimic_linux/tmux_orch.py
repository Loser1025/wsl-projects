"""
tmux_orch.py — tmux セッション・ペイン管理
TmuxPane:    1つのペインへの送信・内容取得
TmuxSession: セッション全体の管理とレイアウト構築

起動パターン:
  A) tmux の中から --tmux → 現在のウィンドウを縦分割して Monitor ペインを追加
  B) tmux の外から --tmux → 新しい tmux セッションを作って中で mimic を起動し attach
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Optional


def _tmux(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """tmux コマンドを実行して CompletedProcess を返す。"""
    return subprocess.run(
        ["tmux"] + list(args),
        capture_output=True,
        text=True,
        check=check,
    )


def inside_tmux() -> bool:
    """現在のプロセスが tmux セッション内で動いているか確認する。"""
    return bool(os.environ.get("TMUX"))


# ── TmuxPane ─────────────────────────────────────────────────────

class TmuxPane:
    """
    tmux の1ペインを表す。
    target 書式: ペインID（例: "%3"）または "session:window.pane"
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
        _tmux("select-pane", "-t", self.target, "-T", title)

    def kill(self) -> None:
        _tmux("kill-pane", "-t", self.target)

    def is_alive(self) -> bool:
        r = _tmux("list-panes", "-t", self.target)
        return r.returncode == 0


# ── TmuxSession ───────────────────────────────────────────────────

class TmuxSession:
    """
    mimic_linux 用 tmux セッションを管理する。

    レイアウト:
    ┌───────────────────────────────────┐
    │  [上] メイン（インタラクティブ）   │
    ├───────────────────────────────────┤
    │  [下] Monitor（1秒ごとに更新）    │
    └───────────────────────────────────┘
    Monitor ペインは画面下部 30% を占有する。
    """

    MONITOR_PANE_HEIGHT_PCT = 45

    def __init__(self, session_name: str = "mimic"):
        self.name = session_name
        self._monitor_pane: Optional[TmuxPane] = None

    # ── セッション存在確認・作成 ────────────────────────────────

    def exists(self) -> bool:
        return _tmux("has-session", "-t", self.name).returncode == 0

    def ensure(self) -> None:
        """セッションがなければ detach 状態で新規作成し、便利オプションを設定する。"""
        if not self.exists():
            _tmux("new-session", "-d", "-s", self.name)

        # マウスクリックでペイン・ウィンドウを切り替えられるようにする
        _tmux("set-option", "-t", self.name, "-g", "mouse", "on")
        _tmux("set-option", "-t", self.name, "-g", "status-interval", "1")
        # ステータスバー: 黒文字（背景は tmux デフォルトのまま）
        # -g はグローバル設定のため -t との共存不可 → -g のみで設定する
        _tmux("set-option", "-g", "status-fg",                    "black")
        _tmux("set-option", "-g", "status-style",                 "fg=black")
        _tmux("set-option", "-g", "window-status-style",          "fg=black")
        _tmux("set-option", "-g", "window-status-current-style",  "fg=black,bold")
        _tmux("set-option", "-g", "status-right",
              "#[fg=black] Ctrl+B→0:main  Ctrl+B→1:raw-log  %H:%M ")

    def attach(self) -> None:
        """セッションにアタッチする（フォアグラウンド）。"""
        subprocess.run(["tmux", "attach", "-t", self.name])

    def kill(self) -> None:
        _tmux("kill-session", "-t", self.name)

    # ── Monitor / Raw Log ペイン管理 ────────────────────────────

    def get_or_create_monitor_pane(self) -> TmuxPane:
        """
        Monitor ペインを画面下部に分割して返す。
        コマンドを指定しないことでデフォルトシェルが開き、
        後から send() で送るコマンドが正しく実行される。

        レイアウト:
          ┌──────────────────────────────┐
          │  メイン                      │ 70%
          ├──────────────────────────────┤
          │  Monitor                     │ 15%
          ├──────────────────────────────┤
          │  Raw API Log                 │ 15%
          └──────────────────────────────┘
        """
        if self._monitor_pane and self._monitor_pane.is_alive():
            return self._monitor_pane

        self.ensure()
        r = _tmux(
            "split-window",
            "-v",
            "-p", str(self.MONITOR_PANE_HEIGHT_PCT),
            "-d",
            "-P", "-F", "#{pane_id}",
            # コマンド指定なし → デフォルトシェル（bash）が開く
        )
        pane_id = r.stdout.strip()
        pane = TmuxPane(pane_id)
        pane.set_title("monitor")
        self._monitor_pane = pane
        return pane

    def create_raw_log_pane(self, monitor_pane: TmuxPane, log_path: str) -> TmuxPane:
        """
        Raw API Log 用の別ウィンドウ（タブ）を作成する。
        Ctrl+B → 1 で切り替えられる。
        Monitor は分割表示のまま維持される。
        """
        self.ensure()
        r = _tmux(
            "new-window",
            "-t", self.name,
            "-n", "raw-log",
            "-d",
            "-P", "-F", "#{pane_id}",
            f"tail -f {log_path}",
        )
        pane_id = r.stdout.strip()
        pane = TmuxPane(pane_id)
        return pane

    # ── ユーティリティ ──────────────────────────────────────────

    @staticmethod
    def available() -> bool:
        """tmux がシステムに存在するか確認する。"""
        return shutil.which("tmux") is not None

    def list_panes(self) -> list[str]:
        r = _tmux("list-panes", "-t", self.name, "-F", "#{pane_id} #{pane_title}")
        return r.stdout.splitlines()


# ── tmux 外からの起動を tmux 内に切り替えるヘルパー ─────────────

def relaunch_inside_tmux(session_name: str = "mimic") -> None:
    """
    tmux の外から --tmux で起動した場合に呼ぶ。
    新しい tmux セッションを作り、その中で mimic_linux を再起動して attach する。
    この関数は return しない（attach 後はユーザーが tmux を操作する）。
    """
    py   = sys.executable
    args = [a for a in sys.argv[1:] if a != "--tmux"]  # --tmux は除去（無限ループ防止）
    cmd  = " ".join([py, "-m", "mimic_linux", "--tmux"] + args)

    # 既存セッションがあれば削除して作り直す
    session = TmuxSession(session_name)
    if session.exists():
        session.kill()

    # 新しいセッションを作って mimic を起動
    subprocess.run([
        "tmux", "new-session", "-s", session_name, cmd,
    ])
    # new-session が終わったら（ユーザーが tmux を閉じたら）プロセスを終了
    sys.exit(0)
