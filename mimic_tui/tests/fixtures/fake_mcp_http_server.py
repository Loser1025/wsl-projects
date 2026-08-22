#!/usr/bin/env python3
"""P2検証用の最小リモートMCPサーバー（Streamable HTTP, 通常のJSON応答のみ）。"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length))
        method = req.get("method")
        req_id = req.get("id")
        auth = self.headers.get("Authorization", "")

        if method == "initialize":
            body = {"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-http-mcp", "version": "0.1"},
            }}
        elif method == "tools/list":
            body = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
                {
                    "name": "whoami",
                    "description": "受け取ったAuthorizationヘッダーをそのまま返す（認証テスト用）",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]}}
        elif method == "tools/call":
            body = {"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"auth={auth}"}], "isError": False,
            }}
        else:
            body = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown method"}}

        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "test-session-123")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8933
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
