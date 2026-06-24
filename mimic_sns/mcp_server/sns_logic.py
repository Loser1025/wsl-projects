"""
sns_logic.py — Instagram/Threads APIロジック + SQLite永続化（Vercelサーバーレス用）

mimic_sns/tools_sns.py と mimic_sns/tools_threads.py のロジックを移植したもの。
Vercel上では .env ファイルではなく os.environ（Vercelの環境変数機能）から読む点が異なる。
urllib のみ使用（requests 不使用）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

_GRAPH_BASE = "https://graph.facebook.com/v19.0"
_THREADS_BASE = "https://graph.threads.net/v1.0"

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_BASE_DIR, "data", "sns_posts.db")
_ENV_PATH = os.path.join(_BASE_DIR, ".env")

# トークン自動更新: expires_atがこの秒数を切ったら長期トークンに再交換する。
_TOKEN_REFRESH_THRESHOLD_SEC = 7 * 24 * 3600
# debug_token呼び出しの間隔（リクエストごとに毎回叩かないためのキャッシュ）。
_TOKEN_CHECK_INTERVAL_SEC = 3600
_token_check_state: dict[str, float] = {}


# ── HTTPヘルパー ──────────────────────────────────────────────

def _api_get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=25) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", errors="replace")) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ネットワークエラー: {e.reason}") from e


def _api_post(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", errors="replace")) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ネットワークエラー: {e.reason}") from e


# ── SQLite ────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    """テーブルが無ければ作成する（冪等）。呼び出しごとに確認するが、CREATE TABLE IF NOT EXISTSなので軽量。"""
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
            CREATE TABLE IF NOT EXISTS threads_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                created_at TEXT,
                posted_at TEXT,
                text TEXT,
                image_path TEXT,
                strategy TEXT,
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


def _save_post(
    theme: str, strategy: str, caption: str, hashtags: str, image_path: str,
    post_id: str | None = None, status: str = "draft",
) -> int:
    _init_db()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO posts (created_at, post_id, theme, strategy, caption, hashtags, image_path, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), post_id, theme, strategy, caption, hashtags, image_path, status),
        )
        return cur.lastrowid


def _load_past_posts(limit: int = 30) -> list[dict]:
    _init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def _save_threads_post(
    text: str, image_path: str, strategy: str,
    post_id: str | None = None, status: str = "draft",
) -> int:
    _init_db()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO threads_posts (created_at, post_id, text, image_path, strategy, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), post_id, text, image_path, strategy, status),
        )
        return cur.lastrowid


# ── トークン自動更新 ───────────────────────────────────────────
# ローカル常駐プロセス（local_run.py）になったため、プロセス内キャッシュで
# debug_token呼び出し頻度を抑えつつ、期限が近づいたら長期トークンに自動交換する。
# APP_SECRET未設定の場合は何もせず黙ってスキップする（従来の手動ローテーションのまま）。

def _update_env_file(key: str, value: str) -> None:
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _maybe_refresh_instagram_token() -> None:
    now = time.time()
    if now - _token_check_state.get("instagram", 0) < _TOKEN_CHECK_INTERVAL_SEC:
        return
    _token_check_state["instagram"] = now
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    app_secret = os.environ.get("APP_SECRET", "")
    if not token or not app_secret:
        return
    try:
        debug = _api_get(
            f"{_GRAPH_BASE}/debug_token?input_token={urllib.parse.quote(token)}"
            f"&access_token={urllib.parse.quote(token)}"
        )
        info = debug.get("data", {})
        expires_at = info.get("expires_at", 0)
        app_id = info.get("app_id", "")
    except Exception as e:
        print(f"[sns_logic][WARN] Instagramトークン状態確認に失敗: {e}", file=sys.stderr)
        return
    if not expires_at or expires_at - now > _TOKEN_REFRESH_THRESHOLD_SEC:
        return
    try:
        result = _api_get(
            f"{_GRAPH_BASE}/oauth/access_token?grant_type=fb_exchange_token"
            f"&client_id={urllib.parse.quote(app_id)}&client_secret={urllib.parse.quote(app_secret)}"
            f"&fb_exchange_token={urllib.parse.quote(token)}"
        )
        new_token = result.get("access_token")
    except Exception as e:
        print(f"[sns_logic][WARN] Instagramトークン自動更新に失敗: {e}", file=sys.stderr)
        return
    if new_token:
        os.environ["INSTAGRAM_ACCESS_TOKEN"] = new_token
        _update_env_file("INSTAGRAM_ACCESS_TOKEN", new_token)
        print("[sns_logic][INFO] Instagramアクセストークンを自動更新しました", file=sys.stderr)


def _maybe_refresh_threads_token() -> None:
    now = time.time()
    if now - _token_check_state.get("threads", 0) < _TOKEN_CHECK_INTERVAL_SEC:
        return
    _token_check_state["threads"] = now
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    app_secret = os.environ.get("APP_SECRET", "")
    if not token or not app_secret:
        return
    try:
        debug = _api_get(
            f"{_THREADS_BASE}/debug_token?input_token={urllib.parse.quote(token)}"
            f"&access_token={urllib.parse.quote(token)}"
        )
        expires_at = debug.get("data", {}).get("expires_at", 0)
    except Exception as e:
        print(f"[sns_logic][WARN] Threadsトークン状態確認に失敗: {e}", file=sys.stderr)
        return
    if not expires_at or expires_at - now > _TOKEN_REFRESH_THRESHOLD_SEC:
        return
    try:
        result = _api_get(
            f"{_THREADS_BASE}/access_token?grant_type=th_exchange_token"
            f"&client_secret={urllib.parse.quote(app_secret)}&access_token={urllib.parse.quote(token)}"
        )
        new_token = result.get("access_token")
    except Exception as e:
        print(f"[sns_logic][WARN] Threadsトークン自動更新に失敗: {e}", file=sys.stderr)
        return
    if new_token:
        os.environ["THREADS_ACCESS_TOKEN"] = new_token
        _update_env_file("THREADS_ACCESS_TOKEN", new_token)
        print("[sns_logic][INFO] Threadsアクセストークンを自動更新しました", file=sys.stderr)


# ── Instagram関数 ─────────────────────────────────────────────

def get_instagram_account_summary() -> str:
    _maybe_refresh_instagram_token()
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        return "INSTAGRAM_ACCESS_TOKEN が未設定です"
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    if not account_id:
        return "INSTAGRAM_ACCOUNT_ID が未設定です"
    url = (
        f"{_GRAPH_BASE}/{urllib.parse.quote(account_id)}"
        f"?fields=id,username,name,biography,followers_count,media_count"
        f"&access_token={urllib.parse.quote(token)}"
    )
    try:
        data = _api_get(url)
    except Exception as e:
        return f"アカウント情報取得エラー: {e}"
    return json.dumps(data, ensure_ascii=False)


def get_instagram_recent_posts(limit: int = 20) -> str:
    _maybe_refresh_instagram_token()
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        return "INSTAGRAM_ACCESS_TOKEN が未設定です"
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    if not account_id:
        return "INSTAGRAM_ACCOUNT_ID が未設定です"
    url = (
        f"{_GRAPH_BASE}/{urllib.parse.quote(account_id)}/media"
        f"?fields=id,caption,timestamp,like_count&limit={int(limit)}"
        f"&access_token={urllib.parse.quote(token)}"
    )
    try:
        data = _api_get(url)
    except Exception as e:
        return f"投稿一覧取得エラー: {e}"
    return json.dumps(data, ensure_ascii=False)


def get_instagram_insights(post_id: str) -> str:
    _maybe_refresh_instagram_token()
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        return "INSTAGRAM_ACCESS_TOKEN が未設定です"
    url = (
        f"{_GRAPH_BASE}/{urllib.parse.quote(post_id)}/insights"
        f"?metric=reach,likes,saved,comments&access_token={urllib.parse.quote(token)}"
    )
    try:
        data = _api_get(url)
    except Exception as e:
        return f"インサイト取得エラー: {e}"
    return json.dumps(data, ensure_ascii=False)


def post_to_instagram(
    image_url: str, caption: str,
    theme: str = "", strategy: str = "", hashtags: str = "",
) -> str:
    """投稿に成功した場合、theme/strategy/hashtagsの指定有無に関わらずSQLiteへ記録する
    （post_id・status='posted'を付与）。記録自体に失敗しても投稿結果（post_id）は返す。"""
    _maybe_refresh_instagram_token()
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        return "INSTAGRAM_ACCESS_TOKEN が未設定です"
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    if not account_id:
        return "INSTAGRAM_ACCOUNT_ID が未設定です"
    try:
        container = _api_post(f"{_GRAPH_BASE}/{account_id}/media", {
            "image_url": image_url,
            "caption": caption,
            "access_token": token,
        })
        creation_id = container.get("id")
        if not creation_id:
            return f"コンテナ作成エラー: {json.dumps(container, ensure_ascii=False)}"
        published = _api_post(f"{_GRAPH_BASE}/{account_id}/media_publish", {
            "creation_id": creation_id,
            "access_token": token,
        })
        post_id = published.get("id")
        if not post_id:
            return f"公開エラー: {json.dumps(published, ensure_ascii=False)}"
    except Exception as e:
        return f"Instagram投稿エラー: {e}"
    try:
        _save_post(theme, strategy, caption, hashtags, image_url, post_id=post_id, status="posted")
    except Exception as e:
        print(f"[sns_logic][WARN] 投稿記録の保存に失敗: {e}", file=sys.stderr)
    return post_id


def save_post_record(theme: str, strategy: str, caption: str, hashtags: str, image_path: str) -> str:
    return str(_save_post(theme, strategy, caption, hashtags, image_path))


def load_past_posts(limit: int = 30) -> str:
    return json.dumps(_load_past_posts(limit), ensure_ascii=False)


# ── Threads関数 ───────────────────────────────────────────────

def get_threads_account_summary() -> str:
    _maybe_refresh_threads_token()
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        return "THREADS_ACCESS_TOKEN が未設定です"
    url = (
        f"{_THREADS_BASE}/me"
        f"?fields=id,username,threads_profile_picture_url,threads_biography"
        f"&access_token={urllib.parse.quote(token)}"
    )
    try:
        data = _api_get(url)
    except Exception as e:
        return f"アカウント情報取得エラー: {e}"
    return json.dumps(data, ensure_ascii=False)


def get_threads_recent_posts(limit: int = 20) -> str:
    _maybe_refresh_threads_token()
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        return "THREADS_ACCESS_TOKEN が未設定です"
    user_id = os.environ.get("THREADS_USER_ID", "")
    if not user_id:
        return "THREADS_USER_ID が未設定です"
    url = (
        f"{_THREADS_BASE}/{urllib.parse.quote(user_id)}/threads"
        f"?fields=id,text,timestamp,like_count&limit={int(limit)}"
        f"&access_token={urllib.parse.quote(token)}"
    )
    try:
        data = _api_get(url)
    except Exception as e:
        return f"投稿一覧取得エラー: {e}"
    return json.dumps(data, ensure_ascii=False)


def get_threads_insights(post_id: str) -> str:
    _maybe_refresh_threads_token()
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        return "THREADS_ACCESS_TOKEN が未設定です"
    url = (
        f"{_THREADS_BASE}/{urllib.parse.quote(post_id)}/insights"
        f"?metric=views,likes,replies,reposts,quotes&access_token={urllib.parse.quote(token)}"
    )
    try:
        data = _api_get(url)
    except Exception as e:
        return f"インサイト取得エラー: {e}"
    return json.dumps(data, ensure_ascii=False)


def post_to_threads(text: str, image_url: str | None = None, strategy: str = "") -> str:
    """投稿に成功した場合、strategyの指定有無に関わらずSQLiteへ記録する
    （post_id・status='posted'を付与）。記録自体に失敗しても投稿結果（post_id）は返す。"""
    _maybe_refresh_threads_token()
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        return "THREADS_ACCESS_TOKEN が未設定です"
    user_id = os.environ.get("THREADS_USER_ID", "")
    if not user_id:
        return "THREADS_USER_ID が未設定です"
    params = {"text": text, "access_token": token}
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"
    try:
        container = _api_post(f"{_THREADS_BASE}/{user_id}/threads", params)
        creation_id = container.get("id")
        if not creation_id:
            return f"コンテナ作成エラー: {json.dumps(container, ensure_ascii=False)}"
        published = _api_post(f"{_THREADS_BASE}/{user_id}/threads_publish", {
            "creation_id": creation_id,
            "access_token": token,
        })
        post_id = published.get("id")
        if not post_id:
            return f"公開エラー: {json.dumps(published, ensure_ascii=False)}"
    except Exception as e:
        return f"Threads投稿エラー: {e}"
    try:
        _save_threads_post(text, image_url or "", strategy, post_id=post_id, status="posted")
    except Exception as e:
        print(f"[sns_logic][WARN] 投稿記録の保存に失敗: {e}", file=sys.stderr)
    return post_id
