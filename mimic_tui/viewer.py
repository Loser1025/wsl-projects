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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

_TRACE_ID_RE = re.compile(r"'trace_id':\s*'([0-9a-f]+)'")

# ビューア表示用の上限（実際のリトライは廃止済みだがバッジ表示に使用）。
_MAX_TEAM_RETRIES = 1

# この秒数以内に更新されたセッションファイルは「実行中」とみなす。
_RUNNING_THRESHOLD_SEC = 90


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
    has_final_answer = False
    team_events: dict[str, list[dict]] = {}
    for e in entries:
        t = e.get("type")
        if t == "session_start":
            model = e.get("model", "")
            provider = e.get("provider", "")
            cwd = e.get("cwd", "")
            own_trace_id = e.get("trace_id", "") or ""
        elif t == "user_input" and not first_user:
            first_user = e.get("content", "")[:100]
        elif t == "final_answer":
            has_final_answer = True
        elif t == "system_event":
            content = e.get("content", "")
            m = _TRACE_ID_RE.search(content)
            if m:
                team_trace_ids.add(m.group(1))
            try:
                obj = ast.literal_eval(content)
            except Exception:
                obj = None
            if isinstance(obj, dict) and str(obj.get("event", "")).startswith("team_") and obj.get("trace_id"):
                team_events.setdefault(obj["trace_id"], []).append(obj)

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    if has_final_answer:
        status = "done"
    elif time.time() - mtime < _RUNNING_THRESHOLD_SEC:
        status = "running"
    else:
        status = "stale"

    return {
        "file": path.name,
        "model": model,
        "provider": provider,
        "cwd": cwd,
        "first_user": first_user,
        "own_trace_id": own_trace_id,
        "team_trace_ids": sorted(team_trace_ids),
        "status": status,
        "_team_events": team_events,
    }


def _team_badge(events: list[dict]) -> Optional[dict]:
    """このtrace_idに関する最新のteam_*イベントから、子セッションの実行状況バッジを導出する。"""
    if not events:
        return None
    last = events[-1]
    ev = last.get("event")
    attempt = last.get("attempt")
    if ev == "team_research_done":
        return {"icon": "🔎", "label": "Researcher調査中"}
    if ev == "team_worker_start":
        return {"icon": "🔄", "label": f"Worker実行中 ({attempt}/{_MAX_TEAM_RETRIES})"}
    if ev == "team_supervisor_verdict":
        if last.get("status") == "ok":
            return {"icon": "✓", "label": "完了"}
        if (attempt or 0) >= _MAX_TEAM_RETRIES:
            return {"icon": "✗", "label": "失敗（リトライ上限）"}
        return {"icon": "⚠", "label": f"retry待ち ({attempt}/{_MAX_TEAM_RETRIES})"}
    return None


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


def _scratchpad_history(entries: list[dict]) -> list[dict]:
    """update_scratchpad ツール呼び出しの履歴を時系列で返す。"""
    history = []
    for e in entries:
        if e.get("type") == "action" and e.get("tool") == "update_scratchpad":
            content = (e.get("args") or {}).get("content", "")
            history.append({"ts": e.get("ts", ""), "step": e.get("step"), "content": content})
    return history


def _list_sessions(sessions_dir: Path) -> list[dict]:
    out = []
    for f in sorted(sessions_dir.glob("*.jsonl"), reverse=True):
        entries = _load_entries(f)
        if entries:
            out.append(_session_meta(f, entries))

    # trace_id -> このtrace_idをown_trace_idとして持つセッション（=子セッション）
    by_trace: dict[str, list[str]] = {}
    for m in out:
        if m["own_trace_id"]:
            by_trace.setdefault(m["own_trace_id"], []).append(m["file"])

    for m in out:
        children: list[str] = []
        for tid in m["team_trace_ids"]:
            children.extend(by_trace.get(tid, []))
        m["children"] = children

    # 親が記録した最新のteam_*イベントから、各子セッションの実行状況バッジを導出する。
    by_file = {m["file"]: m for m in out}
    for m in out:
        for tid in m["team_trace_ids"]:
            badge = _team_badge(m["_team_events"].get(tid, []))
            if badge is None:
                continue
            for child_file in by_trace.get(tid, []):
                child = by_file.get(child_file)
                if child is not None:
                    child["badge"] = badge

    child_files: set[str] = set()
    for m in out:
        child_files.update(m["children"])
    for m in out:
        m["is_root"] = m["file"] not in child_files
        del m["_team_events"]

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
  .session { padding: 8px; border-radius: 4px; cursor: pointer; margin-bottom: 4px; font-size: 13px; border-left: 2px solid transparent; }
  .session:hover, .session.active { background: #333; }
  .session.active { border-left-color: #8cf; }
  .session .file { color: #8cf; font-weight: bold; }
  .session .meta { color: #999; font-size: 11px; }
  .session .role { color: #6a9; font-weight: normal; }
  .session .toggle { display: inline-block; width: 14px; text-align: center; color: #888; cursor: pointer; user-select: none; }
  .session-children.collapsed { display: none; }
  .badge { display: inline-block; margin-left: 6px; padding: 0 5px; border-radius: 3px; font-size: 11px; font-weight: normal; }
  .badge-running { background: #2a4a6a; color: #9cf; }
  .badge-retry { background: #4a3a1a; color: #fc9; }
  .badge-failed { background: #4a1a1a; color: #f99; }
  .badge-ok { background: #1a3a1a; color: #9d9; }
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
  .scratchpad { margin: 10px 0; padding: 8px 10px; border-radius: 4px; background: #233322; border: 1px solid #355; }
  .scratchpad-title { font-size: 12px; color: #9c9; font-weight: bold; margin-bottom: 4px; }
  .scratchpad-rev { margin: 6px 0; padding-top: 4px; border-top: 1px solid #355; }
  .scratchpad-ts { font-size: 11px; color: #999; }
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
// ユーザーが明示的に開閉を切り替えたノードは、自動更新で再描画されても
// その状態を維持する（file -> collapsed(bool)）。
const manualCollapse = new Map();
let currentFile = null;

function badgeClass(icon) {
  if (icon === '🔄' || icon === '🔎') return 'badge-running';
  if (icon === '⚠') return 'badge-retry';
  if (icon === '✗') return 'badge-failed';
  if (icon === '✓') return 'badge-ok';
  return '';
}

function badgeHtml(s) {
  let b = s.badge;
  if (!b && s.status === 'running') b = { icon: '🔄', label: '実行中' };
  if (!b) return '';
  return ` <span class="badge ${badgeClass(b.icon)}">${b.icon} ${esc(b.label)}</span>`;
}

// このノード、またはその子孫のいずれかが「進行中/要注目」状態かどうか。
function isActive(s, byFile, seen) {
  seen = seen || new Set();
  if (seen.has(s.file)) return false;
  seen.add(s.file);
  if (s.status === 'running') return true;
  if (s.badge && (s.badge.icon === '🔄' || s.badge.icon === '⚠' || s.badge.icon === '🔎')) return true;
  for (const childFile of (s.children || [])) {
    const child = byFile[childFile];
    if (child && isActive(child, byFile, seen)) return true;
  }
  return false;
}

function renderSessionNode(container, s, byFile, depth, seen) {
  if (seen.has(s.file)) return;
  seen.add(s.file);

  const wrapper = document.createElement('div');
  wrapper.className = 'session-wrapper';

  const hasChildren = (s.children || []).length > 0;
  const div = document.createElement('div');
  div.className = 'session';
  if (s.file === currentFile) div.classList.add('active');
  div.style.marginLeft = (depth * 14) + 'px';
  div.dataset.file = s.file;
  const role = s.own_trace_id ? ' <span class="role">[Worker/Researcher/Supervisor]</span>'
                               : (hasChildren ? ' <span class="role">[Director]</span>' : '');
  // デフォルト: 進行中/要注目のサブツリーは自動展開、それ以外は折りたたみ。
  // 手動で切り替えた場合はその状態を優先する。
  const defaultCollapsed = !isActive(s, byFile);
  const collapsed = manualCollapse.has(s.file) ? manualCollapse.get(s.file) : defaultCollapsed;
  const toggle = hasChildren ? `<span class="toggle">${collapsed ? '▶' : '▼'}</span>` : '<span class="toggle"></span>';
  div.innerHTML = `<div class="file">${toggle}${s.file}${role}${badgeHtml(s)}</div>` +
                  `<div class="meta">${s.model || ''} ${s.provider || ''}</div>` +
                  `<div class="meta">${(s.first_user || '').replace(/</g,'&lt;')}</div>`;
  div.onclick = (ev) => {
    if (hasChildren && ev.target.classList.contains('toggle')) {
      const childrenDiv = wrapper.querySelector('.session-children');
      const nowCollapsed = childrenDiv.classList.toggle('collapsed');
      manualCollapse.set(s.file, nowCollapsed);
      ev.target.textContent = nowCollapsed ? '▶' : '▼';
      return;
    }
    loadDetail(s.file);
  };
  wrapper.appendChild(div);

  if (hasChildren) {
    const childrenDiv = document.createElement('div');
    childrenDiv.className = 'session-children' + (collapsed ? ' collapsed' : '');
    for (const childFile of s.children) {
      const child = byFile[childFile];
      if (child) renderSessionNode(childrenDiv, child, byFile, depth + 1, seen);
    }
    wrapper.appendChild(childrenDiv);
  }

  container.appendChild(wrapper);
}

async function loadList() {
  const res = await fetch('/api/sessions');
  const sessions = await res.json();
  const byFile = {};
  for (const s of sessions) byFile[s.file] = s;
  const list = document.getElementById('list');
  list.innerHTML = '';
  const seen = new Set();
  for (const s of sessions) {
    if (s.is_root) renderSessionNode(list, s, byFile, 0, seen);
  }
  // is_root の判定漏れ（循環参照など）で取り残されたセッションも末尾に表示する
  for (const s of sessions) {
    if (!seen.has(s.file)) renderSessionNode(list, s, byFile, 0, seen);
  }
  return byFile;
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

function jsonBlock(value, id) {
  const pretty = JSON.stringify(value, null, 2);
  const inner = `<pre class="json">${syntaxHighlight(pretty)}</pre>`;
  if (pretty.length <= COLLAPSE_THRESHOLD) return inner;
  return `<details data-id="${esc(id || '')}"><summary>展開/折りたたみ（${pretty.length}文字）</summary>${inner}</details>`;
}

function textBlock(text, id) {
  text = text || '';
  const inner = `<pre class="text">${esc(text)}</pre>`;
  if (text.length <= COLLAPSE_THRESHOLD) return inner;
  return `<details data-id="${esc(id || '')}"><summary>展開/折りたたみ（${text.length}文字）</summary>${inner}</details>`;
}

async function loadDetail(file) {
  currentFile = file;
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
  if (data.scratchpad_history && data.scratchpad_history.length) {
    const hist = data.scratchpad_history;
    const latest = hist[hist.length - 1];
    html += '<div class="scratchpad">';
    html += `<div class="scratchpad-title">📋 スクラッチパッド（最終更新: ${esc(latest.ts || '')}）</div>`;
    html += `<pre class="text">${esc(latest.content || '')}</pre>`;
    if (hist.length > 1) {
      html += `<details data-id="scratchpad-history"><summary>更新履歴（${hist.length}件）</summary>`;
      for (const h of hist) {
        html += `<div class="scratchpad-rev"><div class="scratchpad-ts">${esc(h.ts || '')}</div><pre class="text">${esc(h.content || '')}</pre></div>`;
      }
      html += '</details>';
    }
    html += '</div>';
  }
  for (let i = 0; i < data.entries.length; i++) {
    const e = data.entries[i];
    const id = `entry-${i}`;
    let body = '';
    if (e.type === 'user_input' || e.type === 'final_answer' || e.type === 'thought') {
      body = textBlock(e.content || '', id);
    } else if (e.type === 'action') {
      body = `<span class="tool-name">${esc(e.tool || '')}</span>` + jsonBlock(e.args || {}, id);
    } else if (e.type === 'observation') {
      const result = e.result || '';
      let parsed = null;
      try { parsed = JSON.parse(result); } catch (_) {}
      if (parsed !== null && typeof parsed === 'object') {
        body = jsonBlock(parsed, id);
      } else {
        body = textBlock(result, id);
      }
    } else if (e.type === 'system_event') {
      if (e.content_obj !== undefined) {
        body = `<span class="tool-name">[${esc(e.level || '')}]</span>` + jsonBlock(e.content_obj, id);
      } else {
        body = `<span class="tool-name">[${esc(e.level || '')}]</span>` + textBlock(e.content || '', id);
      }
    } else {
      body = jsonBlock(e, id);
    }
    html += `<div class="entry ${e.type}"><div class="type">${e.type} ${e.ts || ''}</div>${body}</div>`;
  }

  // 自動更新で再描画されても、開いている<details>と縦スクロール位置を維持する。
  const openIds = new Set();
  detail.querySelectorAll('details[open]').forEach(d => {
    if (d.dataset.id) openIds.add(d.dataset.id);
  });
  const scrollTop = detail.scrollTop;

  detail.innerHTML = html;
  detail.querySelectorAll('details').forEach(d => {
    if (d.dataset.id && openIds.has(d.dataset.id)) d.open = true;
  });
  detail.scrollTop = scrollTop;

  detail.querySelectorAll('a[data-file]').forEach(a => {
    a.onclick = (ev) => { ev.preventDefault(); loadDetail(a.dataset.file); };
  });
}

loadList();

// 進行中のチーム実行を見失わないよう、定期的にツリーと現在の詳細表示を更新する。
const REFRESH_MS = 4000;
setInterval(async () => {
  await loadList();
  if (currentFile) await loadDetail(currentFile);
}, REFRESH_MS);
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
            scratchpad_history = _scratchpad_history(entries)
            self._send_json({
                "entries": entries,
                "linked_sessions": linked,
                "scratchpad_history": scratchpad_history,
            })
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
