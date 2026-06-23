"""
sns_data.py — SNS運用データのSQLite永続化（標準ライブラリのみ、外部依存なし）
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).parent / "data" / "sns_posts.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """テーブルが無ければ作成する（冪等）。"""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                created_at TEXT,
                posted_at TEXT,
                theme TEXT,
                strategy TEXT,
                caption TEXT,
                hashtags TEXT,
                image_path TEXT,
                status TEXT DEFAULT 'draft'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                fetched_at TEXT,
                reach INTEGER,
                likes INTEGER,
                saves INTEGER,
                comments INTEGER,
                impressions INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS threads_posts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id     TEXT,
                created_at  TEXT,
                posted_at   TEXT,
                text        TEXT,
                image_path  TEXT,
                strategy    TEXT,
                status      TEXT DEFAULT 'draft'
            )
        """)


def save_post(theme: str, strategy: str, caption: str, hashtags: str, image_path: str) -> int:
    """投稿レコードを draft 状態で保存し、レコードIDを返す。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO posts (created_at, theme, strategy, caption, hashtags, image_path, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'draft')",
            (datetime.now().isoformat(), theme, strategy, caption, hashtags, image_path),
        )
        return cur.lastrowid


def update_post_id(record_id: int, post_id: str) -> None:
    """投稿成功後にInstagram側の投稿IDを記録する。"""
    with _connect() as conn:
        conn.execute("UPDATE posts SET post_id = ? WHERE id = ?", (post_id, record_id))


def update_post_status(record_id: int, status: str) -> None:
    """ステータスを更新する（draft / posted / failed）。postedの場合はposted_atも記録する。"""
    with _connect() as conn:
        if status == "posted":
            conn.execute(
                "UPDATE posts SET status = ?, posted_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), record_id),
            )
        else:
            conn.execute("UPDATE posts SET status = ? WHERE id = ?", (status, record_id))


def save_insight(post_id: str, reach: int, likes: int, saves: int, comments: int, impressions: int) -> None:
    """投稿のインサイト（取得時点のスナップショット）を保存する。"""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO insights (post_id, fetched_at, reach, likes, saves, comments, impressions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (post_id, datetime.now().isoformat(), reach, likes, saves, comments, impressions),
        )


def load_past_posts(limit: int = 30) -> list[dict]:
    """直近limit件の投稿レコードを新しい順で返す。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_threads_post(text: str, image_path: str, strategy: str) -> int:
    """Threads投稿レコードを draft 状態で保存し、レコードIDを返す。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO threads_posts (created_at, text, image_path, strategy, status) "
            "VALUES (?, ?, ?, ?, 'draft')",
            (datetime.now().isoformat(), text, image_path, strategy),
        )
        return cur.lastrowid


def load_insights(post_id: str) -> dict:
    """指定した投稿IDの最新インサイトを返す（無ければ空dict）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM insights WHERE post_id = ? ORDER BY fetched_at DESC LIMIT 1",
            (post_id,),
        ).fetchone()
        return dict(row) if row else {}


# モジュール読み込み時にテーブルを保証する（tools_sns 経由で必ず一度は import されるため）
init_db()
