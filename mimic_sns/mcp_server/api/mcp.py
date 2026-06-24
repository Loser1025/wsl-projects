"""
api/mcp.py — Vercel Python Serverless Function による MCPエンドポイント

【実装方針についての注記】
依頼書では `mcp.server` / `starlette` / SSE（GET接続を張りっぱなしにしてPOSTからpushする
旧HTTP+SSEトランスポート）を使う想定だったが、Vercelのサーバーレス関数はリクエストごとに
独立して実行され、別リクエスト間で状態やソケットを共有できないため、その方式は動作しない。
そのため、MCP仕様の "Streamable HTTP" トランスポートに準じた、POST 1回 = JSON-RPC応答1回の
ステートレスな実装にしている（Claude.aiのカスタムMCPインテグレーションが使う方式と互換）。
GETはSSEではなく、サーバー情報を返す簡易ヘルスチェックとして実装する。

認証: Authorization: Bearer <MCP_AUTH_TOKEN> が無いと全リクエストを401で拒否する
（CORSがApplication全開放のため、認証なしでは誰でも投稿系ツールを呼び出せてしまう）。
"""
from __future__ import annotations

import hmac
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sns_logic  # noqa: E402

_SERVER_NAME = "mimic-sns-mcp"
_SERVER_VERSION = "1.0.0"

# ── ツール定義（名前・説明・入力スキーマ・実体関数） ──────────────────

_TOOLS = [
    {
        "name": "get_instagram_account_summary",
        "description": "Instagramアカウントの基本情報（id, username, name, biography, followers_count, media_count）を取得する。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "func": lambda args: sns_logic.get_instagram_account_summary(),
    },
    {
        "name": "get_instagram_recent_posts",
        "description": "Instagramアカウントの直近N件の投稿（id, caption, timestamp, like_count）を取得する。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "取得件数（デフォルト20）"}},
            "required": [],
        },
        "func": lambda args: sns_logic.get_instagram_recent_posts(int(args.get("limit", 20))),
    },
    {
        "name": "get_instagram_insights",
        "description": "指定したInstagram投稿IDのインサイト（reach, likes, saved, comments）を取得する。",
        "inputSchema": {
            "type": "object",
            "properties": {"post_id": {"type": "string", "description": "Instagram投稿ID"}},
            "required": ["post_id"],
        },
        "func": lambda args: sns_logic.get_instagram_insights(args["post_id"]),
    },
    {
        "name": "post_to_instagram",
        "description": "Instagramに画像を投稿する（コンテナ作成→公開の2ステップ）。image_url は公開アクセス可能なURLである必要がある。"
        "投稿成功時はtheme/strategy/hashtagsの指定有無に関わらずSQLiteに自動記録される（save_post_recordを別途呼ぶ必要はない）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_url": {"type": "string", "description": "公開URL形式の画像URL"},
                "caption": {"type": "string", "description": "投稿キャプション（ハッシュタグ込み）"},
                "theme": {"type": "string", "description": "投稿テーマ（記録用、省略可）"},
                "strategy": {"type": "string", "description": "投稿戦略（記録用、省略可）"},
                "hashtags": {"type": "string", "description": "ハッシュタグ（記録用、省略可）"},
            },
            "required": ["image_url", "caption"],
        },
        "func": lambda args: sns_logic.post_to_instagram(
            args["image_url"], args["caption"],
            args.get("theme", ""), args.get("strategy", ""), args.get("hashtags", ""),
        ),
    },
    {
        "name": "save_post_record",
        "description": "生成した投稿データ（テーマ・戦略・キャプション・ハッシュタグ・画像パス）をSQLiteに保存する。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "theme": {"type": "string"},
                "strategy": {"type": "string"},
                "caption": {"type": "string"},
                "hashtags": {"type": "string"},
                "image_path": {"type": "string"},
            },
            "required": ["theme", "strategy", "caption", "hashtags", "image_path"],
        },
        "func": lambda args: sns_logic.save_post_record(
            args["theme"], args["strategy"], args["caption"], args["hashtags"], args["image_path"]
        ),
    },
    {
        "name": "load_past_posts",
        "description": "過去のInstagram投稿データをSQLiteから取得する（直近limit件）。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "取得件数（デフォルト30）"}},
            "required": [],
        },
        "func": lambda args: sns_logic.load_past_posts(int(args.get("limit", 30))),
    },
    {
        "name": "get_threads_account_summary",
        "description": "Threadsアカウントの基本情報（id, username, threads_profile_picture_url, threads_biography）を取得する。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "func": lambda args: sns_logic.get_threads_account_summary(),
    },
    {
        "name": "get_threads_recent_posts",
        "description": "Threadsアカウントの直近N件の投稿（id, text, timestamp, like_count）を取得する。",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "取得件数（デフォルト20）"}},
            "required": [],
        },
        "func": lambda args: sns_logic.get_threads_recent_posts(int(args.get("limit", 20))),
    },
    {
        "name": "get_threads_insights",
        "description": "指定したThreads投稿IDのインサイト（views, likes, replies, reposts, quotes）を取得する。",
        "inputSchema": {
            "type": "object",
            "properties": {"post_id": {"type": "string", "description": "Threads投稿ID"}},
            "required": ["post_id"],
        },
        "func": lambda args: sns_logic.get_threads_insights(args["post_id"]),
    },
    {
        "name": "post_to_threads",
        "description": "Threadsにテキストまたは画像を投稿する（コンテナ作成→公開の2ステップ）。image_url省略時はテキストのみ投稿。"
        "投稿成功時はstrategyの指定有無に関わらずSQLiteに自動記録される。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "投稿テキスト"},
                "image_url": {"type": "string", "description": "公開URL形式の画像URL（省略可）"},
                "strategy": {"type": "string", "description": "投稿戦略（記録用、省略可）"},
            },
            "required": ["text"],
        },
        "func": lambda args: sns_logic.post_to_threads(
            args["text"], args.get("image_url"), args.get("strategy", ""),
        ),
    },
]

_TOOLS_BY_NAME = {t["name"]: t for t in _TOOLS}


def _check_auth(auth_header: str | None, query_token: str | None = None) -> bool:
    """Authorizationヘッダー（Bearer）優先、無ければ ?token= クエリパラメータも受け付ける。
    クエリパラメータはアクセスログ・リファラーに残りやすいため、ヘッダーが使えるクライアントでは
    そちらを優先すること（MCPクライアント側がカスタムヘッダーに対応していない場合の代替手段）。
    """
    expected = os.environ.get("MCP_AUTH_TOKEN", "")
    if not expected:
        return False
    provided = ""
    if auth_header and auth_header.startswith("Bearer "):
        provided = auth_header[len("Bearer "):]
    elif query_token:
        provided = query_token
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def _jsonrpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle_rpc(body: dict) -> dict | None:
    method = body.get("method")
    req_id = body.get("id")

    if method == "initialize":
        return _jsonrpc_result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None  # 通知には応答しない

    if method == "tools/list":
        return _jsonrpc_result(req_id, {
            "tools": [
                {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                for t in _TOOLS
            ]
        })

    if method == "tools/call":
        params = body.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = _TOOLS_BY_NAME.get(name)
        if tool is None:
            return _jsonrpc_error(req_id, -32602, f"未知のツールです: {name}")
        try:
            text = tool["func"](arguments)
        except KeyError as e:
            return _jsonrpc_error(req_id, -32602, f"必須引数が不足しています: {e}")
        except Exception as e:
            return _jsonrpc_result(req_id, {
                "content": [{"type": "text", "text": f"ツール実行エラー: {e}"}],
                "isError": True,
            })
        return _jsonrpc_result(req_id, {"content": [{"type": "text", "text": str(text)}]})

    return _jsonrpc_error(req_id, -32601, f"未対応のメソッドです: {method}")


class handler(BaseHTTPRequestHandler):
    def _query_token(self) -> str:
        query = urllib.parse.urlparse(self.path).query
        return urllib.parse.parse_qs(query).get("token", [""])[0]

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if not _check_auth(self.headers.get("Authorization"), self._query_token()):
            self._send_json(401, {"error": "認証が必要です（Authorization: Bearer <token> または ?token=<token>）"})
            return
        self._send_json(200, {
            "name": _SERVER_NAME,
            "version": _SERVER_VERSION,
            "transport": "streamable-http",
            "tools_count": len(_TOOLS),
        })

    def do_POST(self):
        if not _check_auth(self.headers.get("Authorization"), self._query_token()):
            self._send_json(401, {"error": "認証が必要です（Authorization: Bearer <token> または ?token=<token>）"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, _jsonrpc_error(None, -32700, "不正なJSONです"))
            return
        response = _handle_rpc(body)
        if response is None:
            self.send_response(204)
            self._cors_headers()
            self.end_headers()
            return
        self._send_json(200, response)

    def log_message(self, format, *args):
        pass  # Vercelのログに任せる（標準エラー出力への二重出力を防ぐ）
