# mimic_tui: MCP(Model Context Protocol) stdioクライアント（設計書 P0/P1）
#
# .mcp.json の mcpServers を読み、各サーバーを subprocess として起動し
# JSON-RPC (newline-delimited JSON, stdio transport) で initialize→tools/list→tools/call を行う。
# 取得したツールは mcp__<server>__<tool> の名前で ToolRegistry に動的登録する。
#
# SkillsとMCPの違い: Skillは「モデルが読む文字列」だが、MCPサーバーは
# ハーネスの外で実際に動くプログラム。デフォルトで全ツールを書込み承認フック
# (_request_write_approval) 経由にする — read-only判定はMCP側の自己申告を信用しない。
from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

_PROTOCOL_VERSION = "2024-11-05"
_INIT_TIMEOUT = 10
_CALL_TIMEOUT = 60


class McpError(Exception):
    pass


class McpServerProcess:
    """1台のMCPサーバー(subprocess)とのJSON-RPC通信を担う。呼び出しはサーバー単位で直列化する。"""

    def __init__(self, name: str, command: str, args: Optional[list] = None,
                 env: Optional[dict] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc: Optional[subprocess.Popen] = None
        self.tools: dict[str, dict] = {}
        self.started = False
        self.failed_reason: Optional[str] = None
        self._id = 0
        self._lock = threading.Lock()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def start(self) -> bool:
        """初回ツール呼び出し時（またはregister時）に起動する。二重起動しない。"""
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return True
            try:
                full_env = dict(os.environ)
                for k, v in self.env.items():
                    full_env[k] = os.path.expandvars(str(v))
                self.proc = subprocess.Popen(
                    [self.command, *self.args],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, bufsize=1, env=full_env,
                )
            except Exception as e:
                self.failed_reason = f"起動失敗: {e}"
                self.proc = None
                return False
            try:
                self._handshake_locked()
            except Exception as e:
                self.failed_reason = f"ハンドシェイク失敗: {e}"
                self._stop_locked()
                return False
            self.started = True
            self.failed_reason = None
            return True

    # ── JSON-RPC (newline-delimited JSON, MCP stdio transport) ─────────
    def _send_locked(self, msg: dict) -> None:
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

    def _recv_locked(self, expect_id: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError("応答タイムアウト")
            ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not ready:
                continue
            line = self.proc.stdout.readline()
            if line == "":
                raise McpError("サーバーが接続を切断しました")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue  # 壊れた行・stderr混入等は無視して次を待つ
            if obj.get("id") == expect_id:
                return obj
            # 通知やずれたレスポンスは無視（MCPは同時複数リクエストを許容するが、
            # このクライアントはサーバーごとに直列実行するため取りこぼしはない）

    def _handshake_locked(self) -> None:
        req_id = self._next_id()
        self._send_locked({
            "jsonrpc": "2.0", "id": req_id, "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mimic_tui", "version": "0.1"},
            },
        })
        resp = self._recv_locked(req_id, _INIT_TIMEOUT)
        if "error" in resp:
            raise McpError(str(resp["error"]))
        self._send_locked({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        list_id = self._next_id()
        self._send_locked({"jsonrpc": "2.0", "id": list_id, "method": "tools/list", "params": {}})
        resp = self._recv_locked(list_id, _INIT_TIMEOUT)
        if "error" in resp:
            raise McpError(str(resp["error"]))
        for t in resp.get("result", {}).get("tools", []):
            n = t.get("name")
            if n:
                self.tools[n] = t

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                self.started = False
            if not self.started:
                ok = self.start()
                if not ok:
                    return f"エラー: MCPサーバー '{self.name}' に接続できません ({self.failed_reason})"
            req_id = self._next_id()
            try:
                self._send_locked({
                    "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                })
                resp = self._recv_locked(req_id, _CALL_TIMEOUT)
            except McpError as e:
                self._stop_locked()
                return f"エラー: MCPツール呼び出し失敗 ({e})。次回呼び出し時に再接続を試みます。"
            if "error" in resp:
                return f"エラー: {resp['error']}"
            result = resp.get("result", {}) or {}
            content = result.get("content", [])
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                else:
                    texts.append(json.dumps(block, ensure_ascii=False))
            text = "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)
            if result.get("isError"):
                return f"[MCPツールエラー: {self.name}/{tool_name}] {text}"
            return text

    def _stop_locked(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None
        self.started = False

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()


# ── サーバー設定の読み込み ───────────────────────────────────────
def _config_paths() -> list[Path]:
    """Claude Codeと同じ .mcp.json / mcpServers キーをそのまま読む。
    ユーザーホーム→プロジェクト直下の順（後者が同名サーバーを上書き）。"""
    return [Path.home() / ".mcp.json", Path.cwd() / ".mcp.json"]


def load_server_configs() -> dict[str, dict]:
    servers: dict[str, dict] = {}
    for p in _config_paths():
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for name, spec in (data.get("mcpServers") or {}).items():
                if isinstance(spec, dict) and spec.get("command"):
                    servers[name] = spec
        except Exception:
            continue
    return servers


# ── サーバー管理・ツール登録 ────────────────────────────────────
_servers: dict[str, McpServerProcess] = {}
_servers_lock = threading.Lock()


def _make_tool_fn(server_name: str, tool_name: str):
    def _fn(**kwargs):
        from .tools import _request_write_approval, UserRejectedWriteError
        from .utils import cache_tool_output

        policy = _load_policy()
        trusted = policy.get(server_name, {}).get("trust") == "read-only"
        if not trusted:
            preview = (
                f"MCPツール呼び出し: {server_name}/{tool_name}\n"
                f"引数: {json.dumps(kwargs, ensure_ascii=False)[:500]}"
            )
            _request_write_approval(f"mcp__{server_name}__{tool_name}", kwargs, preview)

        with _servers_lock:
            proc = _servers.get(server_name)
        if proc is None:
            return f"エラー: MCPサーバー '{server_name}' は接続されていません。"
        result = proc.call_tool(tool_name, kwargs)
        return cache_tool_output(f"mcp_{server_name}_{tool_name}", str(result))
    return _fn


def _register_tools_for(proc: McpServerProcess) -> int:
    from .tools import tools as _base_tools
    n = 0
    for tool_name, spec in proc.tools.items():
        full_name = f"mcp__{proc.name}__{tool_name}"
        params = spec.get("inputSchema") or {"type": "object", "properties": {}}
        desc = f"[MCP:{proc.name}] " + (spec.get("description") or tool_name)
        _base_tools.register(name=full_name, description=desc[:800], parameters=params)(
            _make_tool_fn(proc.name, tool_name)
        )
        n += 1
    return n


def connect_all() -> list[tuple[str, bool, str]]:
    """設定済みMCPサーバー全台に接続し、ツールをToolRegistryへ登録する。
    戻り値: [(サーバー名, 成功したか, 詳細メッセージ)]。
    Directorプロセス（Interactive/--prompt）でのみ呼ぶこと — Worker側では呼ばない
    （設計書§5: MCPツールはWorkerのoverlay隔離から直接呼べないため意図的に非対応）。"""
    configs = load_server_configs()
    results: list[tuple[str, bool, str]] = []
    for name, spec in configs.items():
        proc = McpServerProcess(name, spec["command"], spec.get("args", []), spec.get("env", {}))
        ok = proc.start()
        if ok:
            with _servers_lock:
                _servers[name] = proc
            n = _register_tools_for(proc)
            results.append((name, True, f"{n}件のツールを登録"))
        else:
            results.append((name, False, proc.failed_reason or "不明なエラー"))
    return results


def shutdown_all() -> None:
    with _servers_lock:
        for proc in _servers.values():
            proc.stop()


def list_status() -> list[dict]:
    configs = load_server_configs()
    out = []
    with _servers_lock:
        for name, spec in configs.items():
            proc = _servers.get(name)
            connected = bool(proc and proc.proc and proc.proc.poll() is None)
            out.append({
                "name": name,
                "command": spec.get("command", ""),
                "connected": connected,
                "tool_count": len(proc.tools) if proc else 0,
                "error": proc.failed_reason if (proc and not connected) else None,
            })
    return out


def reconnect(name: str) -> str:
    configs = load_server_configs()
    spec = configs.get(name)
    if not spec:
        return f"エラー: '{name}' は .mcp.json に見つかりません。"
    with _servers_lock:
        old = _servers.pop(name, None)
    if old:
        old.stop()
    proc = McpServerProcess(name, spec["command"], spec.get("args", []), spec.get("env", {}))
    ok = proc.start()
    if not ok:
        return f"✗ 再接続失敗: {proc.failed_reason}"
    with _servers_lock:
        _servers[name] = proc
    n = _register_tools_for(proc)
    return f"✓ 再接続完了: {n}件のツールを登録しました。"


# ── ポリシー（design doc §5: read-only信頼設定は .mcp.json ではなく別ファイルに分離） ──
_POLICY_LOCK = threading.Lock()


def _policy_path() -> Path:
    p = Path(__file__).parent / ".mimic"
    p.mkdir(parents=True, exist_ok=True)
    return p / "mcp_policy.json"


def _load_policy() -> dict:
    p = _policy_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_server_trust(server_name: str, trust: str) -> None:
    """trust='read-only' の場合のみ承認フックを省略する。それ以外は常に承認必須。"""
    with _POLICY_LOCK:
        data = _load_policy()
        data.setdefault(server_name, {})["trust"] = trust
        _policy_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
