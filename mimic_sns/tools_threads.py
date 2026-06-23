"""
tools_threads.py — Threads API ツール群（@tools.register() で既存registryに登録）
tools_sns.py と同じパターンで urllib のみを使用（requests 不使用）。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import _parse_env_file
from .tools import tools
from .sns_data import save_threads_post as _save_threads_post

_THREADS_BASE = "https://graph.threads.net/v1.0"
_ENV_PATH = Path(__file__).parent / ".env"


def _get_env(key: str) -> str:
    """.env から値を読む（os.environ には反映されないため独自に読む）。"""
    if not _ENV_PATH.exists():
        return ""
    return _parse_env_file(_ENV_PATH).get(key, "")


def _api_get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", errors="replace")) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ネットワークエラー: {e.reason}") from e


def _api_post(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", errors="replace")) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"ネットワークエラー: {e.reason}") from e


@tools.register(
    name="get_threads_account_summary",
    description="Threadsアカウントの基本情報（id, username, threads_profile_picture_url, threads_biography）を取得する。",
    parameters={"type": "object", "properties": {}, "required": []},
)
def get_threads_account_summary() -> str:
    token = _get_env("THREADS_ACCESS_TOKEN")
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


@tools.register(
    name="get_threads_recent_posts",
    description="Threadsアカウントの直近N件の投稿（id, text, timestamp, like_count）を取得する。",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "取得件数（デフォルト20）", "default": 20},
        },
        "required": [],
    },
)
def get_threads_recent_posts(limit: int = 20) -> str:
    token = _get_env("THREADS_ACCESS_TOKEN")
    if not token:
        return "THREADS_ACCESS_TOKEN が未設定です"
    user_id = _get_env("THREADS_USER_ID")
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


@tools.register(
    name="get_threads_insights",
    description="指定したThreads投稿IDのインサイト（views, likes, replies, reposts, quotes）を取得する。",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "string", "description": "Threads投稿ID"},
        },
        "required": ["post_id"],
    },
)
def get_threads_insights(post_id: str) -> str:
    token = _get_env("THREADS_ACCESS_TOKEN")
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


@tools.register(
    name="post_to_threads",
    description=(
        "Threadsにテキストまたは画像を投稿する（コンテナ作成→公開の2ステップ）。"
        "image_url を省略した場合はテキストのみの投稿になる。"
        "image_url は公開アクセス可能なURLである必要がある。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "text":      {"type": "string", "description": "投稿テキスト"},
            "image_url": {"type": "string", "description": "公開URL形式の画像URL（省略可）"},
        },
        "required": ["text"],
    },
)
def post_to_threads(text: str, image_url: str | None = None) -> str:
    token = _get_env("THREADS_ACCESS_TOKEN")
    if not token:
        return "THREADS_ACCESS_TOKEN が未設定です"
    user_id = _get_env("THREADS_USER_ID")
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
        return post_id
    except Exception as e:
        return f"Threads投稿エラー: {e}"


@tools.register(
    name="save_threads_record",
    description="生成したThreads投稿データ（テキスト・画像パス・戦略）をSQLiteに保存する。",
    parameters={
        "type": "object",
        "properties": {
            "text":       {"type": "string", "description": "投稿テキスト本文"},
            "image_path": {"type": "string", "description": "画像ファイルパス（テキストのみの場合は空文字）"},
            "strategy":   {"type": "string", "description": "戦略メモ"},
        },
        "required": ["text", "image_path", "strategy"],
    },
)
def save_threads_record(text: str, image_path: str, strategy: str) -> str:
    record_id = _save_threads_post(text, image_path, strategy)
    return str(record_id)
