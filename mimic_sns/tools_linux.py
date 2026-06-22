"""
tools_linux.py — Linux専用ツール実装
run_bash: pty対応 / プロセスグループkill / SIGTERM→SIGKILL エスカレーション
"""
from __future__ import annotations

import os
import pty
import re
import signal
import select
import subprocess
import time
from pathlib import Path
from typing import Optional

from .tools import tools

# grep_codebase 再帰検索時の除外設定
_GREP_EXCLUDE_DIRS = (
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", ".cache", "coverage",
    ".mypy_cache", ".pytest_cache", ".tox", "target", "vendor",
)
_GREP_EXCLUDE_FILES = ("*.min.js", "*.min.css", "*.map", "*.bundle.js", "*.lock", "package-lock.json")
_GREP_MAX_LINE_CHARS = 300   # 1行あたりの表示上限文字数（minified対策）

# PTY 出力から端末状態変更シーケンスを除去するパターン
# DEC プライベートモード（代替画面・マウストラッキング・カーソルキーモード等）
# これらが親ターミナルに送信されると端末状態が破壊される
_TERMINAL_CTRL_RE = re.compile(r'\033\[\?[0-9;]*[hl]')

# sudo パスワードプロンプト検出パターン（デコード後の文字列で照合）
_SUDO_PROMPT_RE = re.compile(
    r'\[sudo\] password for [^:]+'
    r'|[Pp]assword:'
    r'|パスワードを入力してください'
)

def _sudo_password() -> bytes:
    """環境変数 SUDO_PASSWORD からパスワードを取得する（デフォルト: 1025）。"""
    return (os.environ.get("SUDO_PASSWORD", "1025") + "\n").encode()


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

    # LC_ALL=C.UTF-8: 文字化け防止
    # PAGER=cat / GIT_PAGER=cat: ページャー (less 等) を無効化
    #   → less が起動すると PTY 経由で代替画面・マウストラッキング等の
    #     端末制御シーケンスが親ターミナルに漏洩し端末状態を破壊するため
    wrapped = (
        "export LC_ALL=C.UTF-8\n"
        "export LANG=C.UTF-8\n"
        "export PAGER=cat\n"
        "export GIT_PAGER=cat\n"
        "export GIT_TERMINAL_PROMPT=0\n"
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
    sudo_sent = 0  # 自動入力した回数（連続失敗ループを防ぐため最大3回）

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
                        # sudo パスワードプロンプトを検知したら自動入力（最大3回）
                        if sudo_sent < 3 and _SUDO_PROMPT_RE.search(
                                chunk.decode("utf-8", errors="replace")):
                            os.write(master_fd, _sudo_password())
                            sudo_sent += 1
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
            # SIGTERM → 2秒以内に終了しなければ SIGKILL（プロセスグループ全体）
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    # ── 出力を文字列に変換 ──
    raw = b"".join(output_chunks)
    # pty はキャリッジリターンを混入させる場合があるので正規化
    output = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    # DEC プライベートモードシーケンスを除去
    # (\033[?1049h=代替画面, \033[?1000h=マウストラッキング等が親端末に漏洩するのを防ぐ)
    output = _TERMINAL_CTRL_RE.sub('', output)
    output = output.strip()

    if timed_out:
        partial = f"\n途中出力:\n{output}" if output else "\n(出力なし)"
        return (
            f"[TIMEOUT] {timeout}秒経過でプロセスを強制終了しました。\n"
            f"作業フォルダ: {cwd}\n"
            f"⚠ タイムアウトですが、途中出力を分析して作業を継続してください。\n"
            f"  - デプロイ・インストール等は途中出力から成否を判断できる場合があります\n"
            f"  - 必要なら timeout を延ばして再実行するか、出力の続きを別コマンドで確認してください"
            f"{partial}"
        )

    rc = proc.returncode if proc.returncode is not None else -1
    status = "SUCCESS" if rc == 0 else f"FAILURE(ExitCode={rc})"
    parts = [f"[{status}]", f"作業フォルダ: {cwd}"]
    if output:
        parts.append(output)
    return "\n".join(parts)


# ── Pipeline-First ツール群 ───────────────────────────────────────
# read_file より先に試みるべきコンテキスト節約ツール


@tools.register(
    name="file_info",
    description="ファイルの行数・サイズ・種類を返す。read_file 前のサイズ確認に使う。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "確認するファイルのパス"},
        },
        "required": ["path"],
    },
)
def file_info(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"エラー: ファイルが見つかりません: {path}"
    size_bytes = p.stat().st_size
    size_chars = size_bytes  # UTF-8 最大値として近似
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.count("\n") + 1
        size_chars = len(text)
    except Exception:
        lines = "不明"

    advice = ""
    if isinstance(lines, int) and size_chars > 5000:
        advice = (
            f"\n[推奨] このファイルは大きいです。read_file より先に:\n"
            f"  → grep_codebase(pattern='キーワード', path='{path}') で絞り込む\n"
            f"  → run_pipeline('grep -n ...' ) でフィルタする"
        )
    return (
        f"パス    : {path}\n"
        f"サイズ  : {size_bytes:,} bytes / {size_chars:,} 文字\n"
        f"行数    : {lines}\n"
        f"種類    : {p.suffix or '(拡張子なし)'}"
        + advice
    )


@tools.register(
    name="grep_codebase",
    description=(
        "パターン検索。path 指定でファイル内単一検索（旧 search_in_file）、"
        "directory 指定でコードベース全体を再帰検索。read_file より先に試すこと。"
    ),
    short_desc="コードベース/ファイル内をパターン検索。",
    parameters={
        "type": "object",
        "properties": {
            "pattern":       {"type": "string",  "description": "検索パターン（正規表現可）"},
            "path":          {"type": "string",  "description": "単一ファイル検索時のパス（指定するとファイル内検索モード）"},
            "directory":     {"type": "string",  "description": "再帰検索対象ディレクトリ（pathが未指定の場合に使用、デフォルト: 作業フォルダ）"},
            "file_type":     {"type": "string",  "description": "対象ファイル拡張子（例: py, js）デフォルト全ファイル（ファイル内検索時は無効）"},
            "ignore_case":   {"type": "boolean", "description": "大文字小文字を無視する（デフォルト false）", "default": False},
            "context_lines": {"type": "integer", "description": "マッチ行の前後に表示する行数（ファイル内検索時のみ有効、デフォルト3）", "default": 3},
            "max_results":   {"type": "integer", "description": "最大表示件数（再帰検索時のみ有効、デフォルト 50）", "default": 50},
        },
        "required": ["pattern"],
    },
)
def grep_codebase(
    pattern: str,
    path: str = "",
    directory: str = ".",
    file_type: str = "",
    ignore_case: bool = False,
    context_lines: int = 3,
    max_results: int = 50,
) -> str:
    if path:
        # 単一ファイル検索モード（旧 search_in_file）
        p = Path(path)
        if not p.exists():
            return f"エラー: ファイルが見つかりません: {path}"
        cmd = ["grep", "-n", "-C", str(context_lines)]
        if ignore_case:
            cmd.append("-i")
        cmd.extend([pattern, str(p.resolve())])
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        if result.returncode == 1:
            return f"「{pattern}」は {path} に見つかりませんでした。"
        if result.returncode > 1:
            return f"エラー: {result.stderr.strip()}"
        out = result.stdout.strip()
        lines = out.count("\n") + 1
        return f"[grep_codebase] {path} / pattern={repr(pattern)} / {lines}行マッチ\n{out}"
    # 再帰検索モード（旧 grep_codebase）
    cwd = str(Path.cwd())
    target = str(Path(directory).resolve()) if directory != "." else cwd
    include      = f"--include='*.{file_type}'" if file_type else ""
    flag         = "-i " if ignore_case else ""
    exclude_dirs  = " ".join(f"--exclude-dir={d}" for d in _GREP_EXCLUDE_DIRS)
    exclude_files = " ".join(f"--exclude={f}" for f in _GREP_EXCLUDE_FILES)
    cmd = (
        f"grep -rn {flag}{include} {exclude_dirs} {exclude_files} "
        f"{_shell_quote(pattern)} {_shell_quote(target)} "
        f"| head -{max_results} | cut -c1-{_GREP_MAX_LINE_CHARS}"
    )
    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    out = result.stdout.strip()
    if not out:
        return f"「{pattern}」は {target} 内に見つかりませんでした。"
    lines = out.count("\n") + 1
    suffix = f"\n（上位 {max_results} 件を表示、各行 {_GREP_MAX_LINE_CHARS} 文字で打ち切り）" if lines >= max_results else f"\n（各行 {_GREP_MAX_LINE_CHARS} 文字で打ち切り）"
    return f"[grep_codebase] pattern={repr(pattern)} / {lines}件ヒット\n{out}{suffix}"


def search_in_file(pattern: str, path: str, context_lines: int = 3, ignore_case: bool = False) -> str:
    """後方互換: grep_codebase(path=...) に委譲。ツールとしては登録しない。"""
    return grep_codebase(pattern=pattern, path=path, context_lines=context_lines, ignore_case=ignore_case)


@tools.register(
    name="smart_read",
    description="ファイルを読む。focus 指定で grep 絞り込み、大ファイルは推奨アクションを案内。read_file より先に試すこと。",
    parameters={
        "type": "object",
        "properties": {
            "path":  {"type": "string", "description": "読み込むファイルのパス"},
            "focus": {"type": "string", "description": "探したいキーワード・関数名など（省略可）"},
            "context_lines": {"type": "integer", "description": "focus 指定時の前後行数（デフォルト5）", "default": 5},
        },
        "required": ["path"],
    },
)
def smart_read(path: str, focus: Optional[str] = None, context_lines: int = 5) -> str:
    p = Path(path)
    if not p.exists():
        return f"エラー: ファイルが見つかりません: {path}"

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"エラー: {e}"

    # focus があれば grep で絞り込む
    if focus:
        cmd = ["grep", "-n", "-C", str(context_lines), focus, str(p.resolve())]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            out = result.stdout.strip()
            return f"[smart_read] {path} / focus={repr(focus)}\n{out}"
        return f"「{focus}」は {path} に見つかりませんでした。\nファイル全体を読む場合: read_file(path='{path}')"

    # focus なし: サイズチェック
    size = len(text)
    if size <= 5000:
        return text

    lines = text.count("\n") + 1
    preview = text[:2000]
    return (
        f"[警告] {path} は {size:,} 文字 ({lines}行) あります。\n"
        f"コンテキスト節約のため以下を推奨:\n"
        f"  grep_codebase(pattern='キーワード', path='{path}')  ← 特定箇所を探す\n"
        f"  grep_codebase(pattern='...', directory='.')           ← 複数ファイルを横断検索\n"
        f"  smart_read(path='{path}', focus='関数名')             ← キーワード指定で絞り込む\n\n"
        f"--- 先頭 2,000文字（プレビュー）---\n{preview}"
    )


def _shell_quote(s: str) -> str:
    """シェルコマンド用にシングルクォートでエスケープする。"""
    return "'" + s.replace("'", "'\\''") + "'"
