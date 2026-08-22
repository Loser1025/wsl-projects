#!/usr/bin/env python3
"""P0検証用の最小MCPサーバー（stdio, newline-delimited JSON-RPC）。
initialize / tools.list / tools.call の3メソッドだけ実装する。
"""
import json
import sys

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-mcp", "version": "0.1"},
            }})
        elif method == "notifications/initialized":
            pass  # 応答不要
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
                {
                    "name": "echo",
                    "description": "入力テキストをそのまま返す（接続テスト用）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
                {
                    "name": "add",
                    "description": "2つの整数を足す",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                        "required": ["a", "b"],
                    },
                },
            ]}})
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "echo":
                text = f"echo: {args.get('text', '')}"
            elif name == "add":
                text = f"result: {int(args.get('a', 0)) + int(args.get('b', 0))}"
            else:
                send({"jsonrpc": "2.0", "id": req_id,
                      "error": {"code": -32601, "message": f"unknown tool {name}"}})
                continue
            send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": text}], "isError": False,
            }})

if __name__ == "__main__":
    main()
