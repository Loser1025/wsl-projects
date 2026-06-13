"""viewer.py — ローカル観測ビューア。

`.mimic/sessions/*.jsonl` を読み取り、Director/Researcher/Worker/Supervisorの
セッション（team.py が発行する trace_id で相互リンク）をブラウザで閲覧できる
簡易SPAを、標準ライブラリの http.server だけで配信する。

`/viewer` スラッシュコマンド（commands.py）から明示的に起動するまで一切動作しない。
新規の依存関係は追加しない。
"""
from __future__ import annotations

import ast
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

_TRACE_ID_RE = re.compile(r"'trace_id':\s*'([0-9a-f]+)'")


def _load_entries(path: Path) -> list[dict]:
    entries = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return entries


def _session_meta(path: Path, entries: list[dict]) -> dict:
    model = provider = cwd = own_trace_id = ""
    first_user = ""
    team_trace_ids: set[str] = set()
    for e in entries:
        t = e.get("type")
        if t == "session_start":
            model = e.get("model", "")
            provider = e.get("provider", "")
            cwd = e.get("cwd", "")
            own_trace_id = e.get("trace_id", "") or ""
        elif t == "user_input" and not first_user:
            first_user = e.get("content", "")[:100]
        elif t == "system_event":
            m = _TRACE_ID_RE.search(e.get("content", ""))
            if m:
                team_trace_ids.add(m.group(1))
    return {
        "file": path.name,
        "model": model,
        "provider": provider,
        "cwd": cwd,
        "first_user": first_user,
        "own_trace_id": own_trace_id,
        "team_trace_ids": sorted(team_trace_ids),
    }


def _annotate_system_events(entries: list[dict]) -> list[dict]:
    """system_event の content (Python repr の dict/list) を可能なら content_obj として付与する。"""
    for e in entries:
        if e.get("type") != "system_event":
            continue
        content = e.get("content", "")
        try:
            obj = ast.literal_eval(content)
        except Exception:
            continue
        if isinstance(obj, (dict, list)):
            e["content_obj"] = obj
    return entries


def _list_sessions(sessions_dir: Path) -> list[dict]:
    out = []
    for f in sorted(sessions_dir.glob("*.jsonl"), reverse=True):
        entries = _load_entries(f)
        if entries:
            out.append(_session_meta(f, entries))
    return out


def _linked_sessions(meta: dict, all_meta: list[dict]) -> list[str]:
    linked = set()
    for other in all_meta:
        if other["file"] == meta["file"]:
            continue
        # Director (meta) -> Worker (other): meta が発行した trace_id を other が session_start で持つ
        if other["own_trace_id"] and other["own_trace_id"] in meta["team_trace_ids"]:
            linked.add(other["file"])
        # Worker (meta) -> Director (other): meta 自身の trace_id を other が team_trace_ids に持つ
        if meta["own_trace_id"] and meta["own_trace_id"] in other["team_trace_ids"]:
            linked.add(other["file"])
    return sorted(linked)


_PAGE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>mimic_tui セッションビューア</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; display: flex; height: 100vh; background: #1e1e1e; color: #ddd; }
  #list { width: 340px; overflow-y: auto; border-right: 1px solid #444; padding: 8px; box-sizing: border-box; }
  #detail { flex: 1; overflow-y: auto; padding: 12px 20px; }
  .session { padding: 8px; border-radius: 4px; cursor: pointer; margin-bottom: 4px; font-size: 13px; }
  .session:hover, .session.active { background: #333; }
  .session .file { color: #8cf; font-weight: bold; }
  .session .meta { color: #999; font-size: 11px; }
  .entry { margin: 6px 0; padding: 6px 10px; border-radius: 4px; font-size: 13px; }
  .entry .type { font-size: 11px; color: #999; margin-bottom: 2px; }
  .entry .tool-name { color: #8cf; font-weight: bold; }
  .user_input { background: #234; }
  .thought { background: #2a2a1a; }
  .action { background: #1a2a2a; }
  .observation { background: #222; color: #aaa; }
  .final_answer { background: #1a2a1a; }
  .system_event { background: #2a1a1a; color: #c99; }
  .links { margin-top: 10px; }
  .links a { display: inline-block; margin: 2px 6px 2px 0; padding: 4px 8px; background: #345; color: #cde; border-radius: 4px; text-decoration: none; font-size: 12px; }
  h2 { font-size: 16px; }
  pre.json, pre.text { white-space: pre-wrap; word-break: break-word; margin: 4px 0 0 0; font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 12px; }
  .json-key { color: #9cdcfe; }
  .json-string { color: #ce9178; }
  .json-number { color: #b5cea8; }
  .json-bool, .json-null { color: #569cd6; }
  details > summary { cursor: pointer; color: #8cf; font-size: 11px; margin-top: 2px; }
  details[open] > summary { margin-bottom: 2px; }
</style>
</head>
<body>
<div id="list"></div>
<div id="detail"><p>左のリストからセッションを選択してください。</p></div>
<script>
async function loadList() {
  const res = await fetch('/api/sessions');
  const sessions = await res.json();
  const list = document.getElementById('list');
  list.innerHTML = '';
  for (const s of sessions) {
    const div = document.createElement('div');
    div.className = 'session';
    div.dataset.file = s.file;
    const role = s.own_trace_id ? ' [Worker]' : (s.team_trace_ids.length ? ' [Director]' : '');
    div.innerHTML = `<div class="file">${s.file}${role}</div>` +
                    `<div class="meta">${s.model || ''} ${s.provider || ''}</div>` +
                    `<div class="meta">${(s.first_user || '').replace(/</g,'&lt;')}</div>`;
    div.onclick = () => loadDetail(s.file);
    list.appendChild(div);
  }
}

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function syntaxHighlight(json) {
  json = esc(json);
  return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
    let cls = 'json-number';
    if (/^"/.test(match)) {
      cls = /:$/.test(match) ? 'json-key' : 'json-string';
    } else if (/^(true|false)$/.test(match)) {
      cls = 'json-bool';
    } else if (match === 'null') {
      cls = 'json-null';
    }
    return '<span class="' + cls + '">' + match + '</span>';
  });
}

const COLLAPSE_THRESHOLD = 600;

function jsonBlock(value) {
  const pretty = JSON.stringify(value, null, 2);
  const inner = `<pre class="json">${syntaxHighlight(pretty)}</pre>`;
  if (pretty.length <= COLLAPSE_THRESHOLD) return inner;
  return `<details><summary>展開/折りたたみ（${pretty.length}文字）</summary>${inner}</details>`;
}

function textBlock(text) {
  text = text || '';
  const inner = `<pre class="text">${esc(text)}</pre>`;
  if (text.length <= COLLAPSE_THRESHOLD) return inner;
  return `<details><summary>展開/折りたたみ（${text.length}文字）</summary>${inner}</details>`;
}

async function loadDetail(file) {
  document.querySelectorAll('#list .session').forEach(el => {
    el.classList.toggle('active', el.dataset.file === file);
  });
  const res = await fetch('/api/sessions/' + encodeURIComponent(file));
  const data = await res.json();
  const detail = document.getElementById('detail');
  let html = `<h2>${file}</h2>`;
  if (data.linked_sessions && data.linked_sessions.length) {
    html += '<div class="links">関連セッション: ';
    for (const lf of data.linked_sessions) {
      html += `<a href="#" data-file="${lf}">${lf}</a>`;
    }
    html += '</div>';
  }
  for (const e of data.entries) {
    let body = '';
    if (e.type === 'user_input' || e.type === 'final_answer' || e.type === 'thought') {
      body = textBlock(e.content || '');
    } else if (e.type === 'action') {
      body = `<span class="tool-name">${esc(e.tool || '')}</span>` + jsonBlock(e.args || {});
    } else if (e.type === 'observation') {
      const result = e.result || '';
      let parsed = null;
      try { parsed = JSON.parse(result); } catch (_) {}
      if (parsed !== null && typeof parsed === 'object') {
        body = jsonBlock(parsed);
      } else {
        body = textBlock(result);
      }
    } else if (e.type === 'system_event') {
      if (e.content_obj !== undefined) {
        body = `<span class="tool-name">[${esc(e.level || '')}]</span>` + jsonBlock(e.content_obj);
      } else {
        body = `<span class="tool-name">[${esc(e.level || '')}]</span>` + textBlock(e.content || '');
      }
    } else {
      body = jsonBlock(e);
    }
    html += `<div class="entry ${e.type}"><div class="type">${e.type} ${e.ts || ''}</div>${body}</div>`;
  }
  detail.innerHTML = html;
  detail.querySelectorAll('a[data-file]').forEach(a => {
    a.onclick = (ev) => { ev.preventDefault(); loadDetail(a.dataset.file); };
  });
}

loadList();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    sessions_dir: Path  # set via partial/class attr by start_viewer_server

    def log_message(self, *args, **kwargs):  # サーバーログを抑制
        pass

    def _send_json(self, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path == "/" or self.path == "/index.html":
            self._send_html(_PAGE)
            return

        if self.path == "/api/sessions":
            self._send_json(_list_sessions(self.sessions_dir))
            return

        if self.path.startswith("/api/sessions/"):
            filename = unquote(self.path[len("/api/sessions/"):])
            if "/" in filename or ".." in filename:
                self.send_error(404)
                return
            f = self.sessions_dir / filename
            if not f.exists():
                self.send_error(404)
                return
            entries = _load_entries(f)
            meta = _session_meta(f, entries)
            entries = _annotate_system_events(entries)
            all_meta = _list_sessions(self.sessions_dir)
            linked = _linked_sessions(meta, all_meta)
            self._send_json({"entries": entries, "linked_sessions": linked})
            return

        self.send_error(404)


_server: Optional[ThreadingHTTPServer] = None
_server_url: Optional[str] = None


def start_viewer_server(sessions_dir: Path, port: int = 0) -> str:
    """ビューアサーバーを起動し、URLを返す。既に起動済みなら同じURLを返す。"""
    global _server, _server_url
    if _server is not None and _server_url is not None:
        return _server_url

    handler_cls = type("_BoundHandler", (_Handler,), {"sessions_dir": sessions_dir})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    _server = server
    _server_url = f"http://127.0.0.1:{server.server_address[1]}"
    return _server_url
