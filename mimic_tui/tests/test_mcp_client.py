# mimic_tui: mcp_client.py の安全境界テスト（bench/test設計書 Track B）
#
# 対象は「壊れたら危険な境界」のみ:
#   - 書込み承認フックを実際に経由し、拒否されればブロックされること
#   - read-only信頼設定でのみ承認が省略されること
#   - Worker向け readonly_only=True が「信頼済みread-onlyのみ」に絞り込むこと
#   - 本物のstdioハンドシェイク(initialize→tools/list→tools/call)が通ること
#
# 新規依存は追加しない（標準ライブラリの unittest のみ）。
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mimic_tui import mcp_client
from mimic_tui.tools import UserRejectedWriteError, set_write_approval_handler

_FIXTURES = Path(__file__).parent / "fixtures"
_FAKE_STDIO_SERVER = _FIXTURES / "fake_mcp_server.py"


def _write_mcp_config(path: Path, servers: dict) -> None:
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


class _McpTestCase(unittest.TestCase):
    """各テストで .mimic/mcp_policy.json とグローバルな接続状態を汚さないための共通セットアップ。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self._policy_patch = patch.object(
            mcp_client, "_policy_path", return_value=self.tmp_path / "mcp_policy.json"
        )
        self._policy_patch.start()
        self.addCleanup(self._policy_patch.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(set_write_approval_handler, None)
        self.addCleanup(self._shutdown_servers)

    def _shutdown_servers(self):
        mcp_client.shutdown_all()
        with mcp_client._servers_lock:
            mcp_client._servers.clear()


class TestWriteApprovalBoundary(_McpTestCase):
    def test_blocks_when_approval_rejected(self):
        proc = mcp_client.McpServerProcess("fake", sys.executable, [str(_FAKE_STDIO_SERVER)])
        self.assertTrue(proc.start())
        with mcp_client._servers_lock:
            mcp_client._servers["fake"] = proc

        rejections = []

        def reject(tool_name, args, preview):
            rejections.append(tool_name)
            return False

        set_write_approval_handler(reject)
        fn = mcp_client._make_tool_fn("fake", "echo")
        with self.assertRaises(UserRejectedWriteError):
            fn(text="should be blocked")
        self.assertEqual(rejections, ["mcp__fake__echo"])

    def test_read_only_trust_skips_approval(self):
        proc = mcp_client.McpServerProcess("fake", sys.executable, [str(_FAKE_STDIO_SERVER)])
        self.assertTrue(proc.start())
        with mcp_client._servers_lock:
            mcp_client._servers["fake"] = proc

        set_write_approval_handler(lambda *a: False)  # 拒否ハンドラーでも
        mcp_client.set_server_trust("fake", "read-only")  # read-only信頼済みなら素通りするはず

        fn = mcp_client._make_tool_fn("fake", "echo")
        result = fn(text="trusted call")
        self.assertIn("trusted call", result)


class TestWorkerReadonlyFilter(_McpTestCase):
    """readonly_only=True (Worker向け) は信頼済みread-onlyサーバーだけを接続する。
    Workerには承認ハンドラーが存在しないため、この接続時フィルタだけが安全境界になる。"""

    def test_no_trust_set_connects_nothing(self):
        cfg = self.tmp_path / ".mcp.json"
        _write_mcp_config(cfg, {
            "fake": {"command": sys.executable, "args": [str(_FAKE_STDIO_SERVER)]},
        })
        with patch.object(mcp_client, "_config_paths", return_value=[cfg]):
            results = mcp_client.connect_all(readonly_only=True)
        self.assertEqual(results, [])

    def test_only_trusted_server_connects(self):
        cfg = self.tmp_path / ".mcp.json"
        _write_mcp_config(cfg, {
            "trusted": {"command": sys.executable, "args": [str(_FAKE_STDIO_SERVER)]},
            "untrusted": {"command": sys.executable, "args": [str(_FAKE_STDIO_SERVER)]},
        })
        mcp_client.set_server_trust("trusted", "read-only")
        with patch.object(mcp_client, "_config_paths", return_value=[cfg]):
            results = mcp_client.connect_all(readonly_only=True)

        connected_names = {name for name, ok, _ in results if ok}
        self.assertEqual(connected_names, {"trusted"})

    def test_full_director_connect_ignores_trust(self):
        """readonly_only=False (Director) は信頼設定に関わらず全サーバーへ接続する。"""
        cfg = self.tmp_path / ".mcp.json"
        _write_mcp_config(cfg, {
            "a": {"command": sys.executable, "args": [str(_FAKE_STDIO_SERVER)]},
            "b": {"command": sys.executable, "args": [str(_FAKE_STDIO_SERVER)]},
        })
        with patch.object(mcp_client, "_config_paths", return_value=[cfg]):
            results = mcp_client.connect_all(readonly_only=False)

        connected_names = {name for name, ok, _ in results if ok}
        self.assertEqual(connected_names, {"a", "b"})


class TestStdioHandshakeRoundtrip(_McpTestCase):
    """本物のsubprocess+JSON-RPCで initialize→tools/list→tools/call が通ること。"""

    def test_handshake_list_and_call(self):
        proc = mcp_client.McpServerProcess("fake", sys.executable, [str(_FAKE_STDIO_SERVER)])
        self.assertTrue(proc.start())
        self.assertIn("echo", proc.tools)
        self.assertIn("add", proc.tools)

        self.assertEqual(proc.call_tool("echo", {"text": "hi"}), "echo: hi")
        self.assertEqual(proc.call_tool("add", {"a": 2, "b": 5}), "result: 7")

        # 存在しないツールはエラーを返す（クラッシュしない）
        err = proc.call_tool("nope", {})
        self.assertIn("エラー", err)

        proc.stop()
        self.assertIsNone(proc.proc)


if __name__ == "__main__":
    unittest.main()
