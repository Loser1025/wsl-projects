"""ローカル運用用エントリポイント。

api/mcp.py の handler（BaseHTTPRequestHandler）は標準ライブラリのみに依存しているため、
Vercelのビルダー（uv等）を介さずそのまま http.server で起動できる。

使い方:
    python3 local_run.py [port]   # デフォルト 8787
"""
from __future__ import annotations

import os
import sys
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    _load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
    from mcp import handler  # noqa: E402

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"mimic-sns-mcp ローカルサーバー起動: http://0.0.0.0:{port}/api/mcp", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
