"""
tools_sns.py — Instagram Graph API ツール群（@tools.register() で既存registryに登録）
既存コードに合わせ urllib のみを使用（requests 不使用）。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import _parse_env_file
from .tools import tools
from .sns_data import (
    save_post as _save_post,
    load_past_posts as _load_past_posts,
)

_GRAPH_API_VERSION = "v19.0"
_GRAPH_BASE = f"https://graph.facebook.com/{_GRAPH_API_VERSION}"
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
    name="get_instagram_insights",
    description="指定したInstagram投稿IDのインサイト（リーチ・いいね・保存・コメント数）を取得する。",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "string", "description": "Instagram投稿ID"},
        },
        "required": ["post_id"],
    },
)
def get_instagram_insights(post_id: str) -> str:
    token = _get_env("INSTAGRAM_ACCESS_TOKEN")
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


@tools.register(
    name="get_account_recent_posts",
    description="Instagramアカウントの直近N件の投稿ID・キャプション・投稿日時・いいね数を取得する。",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "取得件数（デフォルト20）", "default": 20},
        },
        "required": [],
    },
)
def get_account_recent_posts(limit: int = 20) -> str:
    token = _get_env("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        return "INSTAGRAM_ACCESS_TOKEN が未設定です"
    account_id = _get_env("INSTAGRAM_ACCOUNT_ID")
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


@tools.register(
    name="post_to_instagram",
    description=(
        "Instagramに画像を投稿する（コンテナ作成→公開の2ステップ）。"
        "image_url は公開アクセス可能なURLである必要がある。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_url": {"type": "string", "description": "公開URL形式の画像URL"},
            "caption":   {"type": "string", "description": "投稿キャプション（ハッシュタグ込み）"},
        },
        "required": ["image_url", "caption"],
    },
)
def post_to_instagram(image_url: str, caption: str) -> str:
    token = _get_env("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        return "INSTAGRAM_ACCESS_TOKEN が未設定です"
    account_id = _get_env("INSTAGRAM_ACCOUNT_ID")
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
        return post_id
    except Exception as e:
        return f"Instagram投稿エラー: {e}"


@tools.register(
    name="save_post_record",
    description="生成した投稿データ（テーマ・戦略・キャプション・ハッシュタグ・画像パス）をSQLiteに保存する。",
    parameters={
        "type": "object",
        "properties": {
            "theme":      {"type": "string", "description": "投稿テーマ"},
            "strategy":   {"type": "string", "description": "戦略メモ"},
            "caption":    {"type": "string", "description": "キャプション本文"},
            "hashtags":   {"type": "string", "description": "ハッシュタグ（スペース区切り）"},
            "image_path": {"type": "string", "description": "画像ファイルパス"},
        },
        "required": ["theme", "strategy", "caption", "hashtags", "image_path"],
    },
)
def save_post_record(theme: str, strategy: str, caption: str, hashtags: str, image_path: str) -> str:
    record_id = _save_post(theme, strategy, caption, hashtags, image_path)
    return str(record_id)


@tools.register(
    name="load_past_posts",
    description="過去のInstagram投稿データをSQLiteから取得する（直近limit件）。",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "取得件数（デフォルト30）", "default": 30},
        },
        "required": [],
    },
)
def load_past_posts(limit: int = 30) -> str:
    rows = _load_past_posts(limit)
    return json.dumps(rows, ensure_ascii=False)
