// Package viewer はReactLogのJSONLセッションをブラウザで閲覧するための
// 軽量HTTPサーバーを実装する（Python版 viewer.py の縮小移植）。
package viewer

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const runningThresholdSec = 120

type teamBadge struct {
	Icon  string `json:"icon"`
	Label string `json:"label"`
}

type sessionMeta struct {
	File         string     `json:"file"`
	Model        string     `json:"model"`
	Provider     string     `json:"provider"`
	FirstUser    string     `json:"first_user"`
	Status       string     `json:"status"` // done / running / stale
	Entries      int        `json:"entries"`
	OwnTraceID   string     `json:"own_trace_id"`
	TeamTraceIDs []string   `json:"team_trace_ids"`
	Children     []string   `json:"children"`
	IsRoot       bool       `json:"is_root"`
	Badge        *teamBadge `json:"badge,omitempty"`

	teamEvents map[string][]map[string]any // trace_id -> このセッションが記録したteam_*イベント列
}

// maxTeamRetries はバッジ表示の分母に使う想定リトライ回数
// （Python版 team.py::MAX_VERIFY_RETRIES と同じ値。internal/delegateの
// MaxVerifyRetriesを直接参照すると import cycle になるため定数を複製する）。
const maxTeamRetries = 3

func loadEntries(path string) []map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var entries []map[string]any
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var e map[string]any
		if err := json.Unmarshal([]byte(line), &e); err == nil {
			entries = append(entries, e)
		}
	}
	return entries
}

func buildSessionMeta(path string, entries []map[string]any) sessionMeta {
	m := sessionMeta{File: filepath.Base(path), Entries: len(entries), teamEvents: map[string][]map[string]any{}}
	hasFinal := false
	teamTraceIDs := make(map[string]bool)
	for _, e := range entries {
		t, _ := e["type"].(string)
		switch t {
		case "session_start":
			m.Model, _ = e["model"].(string)
			m.Provider, _ = e["provider"].(string)
			m.OwnTraceID, _ = e["trace_id"].(string)
		case "user_input":
			if m.FirstUser == "" {
				content, _ := e["content"].(string)
				if len(content) > 100 {
					content = content[:100]
				}
				m.FirstUser = content
			}
		case "final_answer":
			hasFinal = true
		case "system_event":
			// Go版はsystem_event.contentへJSON文字列として委任イベントを記録する
			// （Python版 team.py::_log_team_event の移植先。internal/delegate/
			// worker.go::logTeamEvent参照）。
			content, _ := e["content"].(string)
			var obj map[string]any
			if err := json.Unmarshal([]byte(content), &obj); err != nil {
				continue
			}
			evName, _ := obj["event"].(string)
			tid, _ := obj["trace_id"].(string)
			if tid != "" && strings.HasPrefix(evName, "team_") {
				teamTraceIDs[tid] = true
				m.teamEvents[tid] = append(m.teamEvents[tid], obj)
			}
		}
	}
	for tid := range teamTraceIDs {
		m.TeamTraceIDs = append(m.TeamTraceIDs, tid)
	}
	sort.Strings(m.TeamTraceIDs)
	info, err := os.Stat(path)
	mtime := time.Time{}
	if err == nil {
		mtime = info.ModTime()
	}
	switch {
	case hasFinal:
		m.Status = "done"
	case time.Since(mtime) < runningThresholdSec*time.Second:
		m.Status = "running"
	default:
		m.Status = "stale"
	}
	return m
}

func listSessions(sessionsDir string) []sessionMeta {
	matches, _ := filepath.Glob(filepath.Join(sessionsDir, "*.jsonl"))
	sort.Sort(sort.Reverse(sort.StringSlice(matches)))
	var out []sessionMeta
	for _, f := range matches {
		entries := loadEntries(f)
		if len(entries) > 0 {
			out = append(out, buildSessionMeta(f, entries))
		}
	}
	return computeSessionTree(out)
}

// teamBadgeFor はtrace_idに関する最新のteam_*イベントから、子セッションの
// 実行状況バッジを導出する（Python版 viewer.py::_team_badge の移植）。
func teamBadgeFor(events []map[string]any) *teamBadge {
	if len(events) == 0 {
		return nil
	}
	last := events[len(events)-1]
	ev, _ := last["event"].(string)
	attemptF, _ := last["attempt"].(float64)
	attempt := int(attemptF)
	switch ev {
	case "team_research_done":
		return &teamBadge{Icon: "🔎", Label: "Researcher調査中"}
	case "team_worker_start":
		return &teamBadge{Icon: "🔄", Label: fmt.Sprintf("Worker実行中 (%d/%d)", attempt, maxTeamRetries)}
	case "team_supervisor_verdict":
		status, _ := last["status"].(string)
		if status == "ok" {
			return &teamBadge{Icon: "✓", Label: "完了"}
		}
		if attempt >= maxTeamRetries {
			return &teamBadge{Icon: "✗", Label: "失敗（リトライ上限）"}
		}
		return &teamBadge{Icon: "⚠", Label: fmt.Sprintf("retry待ち (%d/%d)", attempt, maxTeamRetries)}
	}
	return nil
}

// computeSessionTree は各セッションのown_trace_id/team_trace_idsから親子関係
// （children/is_root）とバッジを導出する（Python版 viewer.py::_list_sessions の
// 後半ロジックの移植）。
func computeSessionTree(sessions []sessionMeta) []sessionMeta {
	byTrace := make(map[string][]string) // trace_id -> このtrace_idをown_trace_idとして持つセッション(子)
	for _, m := range sessions {
		if m.OwnTraceID != "" {
			byTrace[m.OwnTraceID] = append(byTrace[m.OwnTraceID], m.File)
		}
	}
	for i := range sessions {
		for _, tid := range sessions[i].TeamTraceIDs {
			sessions[i].Children = append(sessions[i].Children, byTrace[tid]...)
		}
	}

	byFile := make(map[string]*sessionMeta, len(sessions))
	for i := range sessions {
		byFile[sessions[i].File] = &sessions[i]
	}
	for i := range sessions {
		for _, tid := range sessions[i].TeamTraceIDs {
			badge := teamBadgeFor(sessions[i].teamEvents[tid])
			if badge == nil {
				continue
			}
			for _, childFile := range byTrace[tid] {
				if child, ok := byFile[childFile]; ok {
					child.Badge = badge
				}
			}
		}
	}

	childFiles := make(map[string]bool)
	for _, m := range sessions {
		for _, c := range m.Children {
			childFiles[c] = true
		}
	}
	for i := range sessions {
		sessions[i].IsRoot = !childFiles[sessions[i].File]
		sessions[i].teamEvents = nil
	}
	return sessions
}

// annotateSystemEvents はsystem_eventのcontent（JSON文字列）をパースできれば
// content_objとして付与する（Python版 viewer.py::_annotate_system_events の移植。
// フロントエンド側でオブジェクトを整形表示するために使う）。
func annotateSystemEvents(entries []map[string]any) {
	for _, e := range entries {
		if t, _ := e["type"].(string); t != "system_event" {
			continue
		}
		content, _ := e["content"].(string)
		var obj any
		if err := json.Unmarshal([]byte(content), &obj); err == nil {
			e["content_obj"] = obj
		}
	}
}

// linkedSessions はmetaと相互にtrace_idで結びついている（親子いずれかの
// 関係にある）他セッションのファイル名一覧を返す
// （Python版 viewer.py::_linked_sessions の移植）。
func linkedSessions(meta sessionMeta, allMeta []sessionMeta) []string {
	linked := make(map[string]bool)
	for _, other := range allMeta {
		if other.File == meta.File {
			continue
		}
		if other.OwnTraceID != "" && containsStr(meta.TeamTraceIDs, other.OwnTraceID) {
			linked[other.File] = true
		}
		if meta.OwnTraceID != "" && containsStr(other.TeamTraceIDs, meta.OwnTraceID) {
			linked[other.File] = true
		}
	}
	out := make([]string, 0, len(linked))
	for f := range linked {
		out = append(out, f)
	}
	sort.Strings(out)
	return out
}

func containsStr(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// scratchpadHistoryFromEntries はupdate_scratchpad呼び出し履歴を時系列で返す
// （Python版 viewer.py::_scratchpad_history の移植。internal/viewer/trace.goの
// GetSessionScratchpadHistoryはtrace_id起点の検索用、こちらはentries直接指定用）。
func scratchpadHistoryFromEntries(entries []map[string]any) []map[string]any {
	var out []map[string]any
	for _, e := range entries {
		t, _ := e["type"].(string)
		tool, _ := e["tool"].(string)
		if t != "action" || tool != "update_scratchpad" {
			continue
		}
		content := ""
		if args, ok := e["args"].(map[string]any); ok {
			content, _ = args["content"].(string)
		}
		out = append(out, map[string]any{"ts": e["ts"], "step": e["step"], "content": content})
	}
	return out
}

// StartServer は127.0.0.1のランダムポートでビューアサーバーを起動し、URLを返す。
// OpenBrowser はurlを既定のブラウザで開こうとする（Python版
// viewer.py::start_viewer_server の webbrowser.open(url) の移植）。
// 開けなくても致命的エラーにはしない（ベストエフォート）。
func OpenBrowser(url string) {
	candidates := [][]string{
		{"wslview", url},                // WSL専用（wslu）
		{"xdg-open", url},               // 一般的なLinuxデスクトップ
		{"cmd.exe", "/c", "start", url}, // WSLからWindows既定ブラウザを開く
		{"open", url},                   // macOS
	}
	for _, argv := range candidates {
		if _, err := exec.LookPath(argv[0]); err != nil {
			continue
		}
		cmd := exec.Command(argv[0], argv[1:]...)
		if cmd.Start() == nil {
			return
		}
	}
}

func StartServer(sessionsDir string) (string, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", err
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write([]byte(pageHTML))
	})
	mux.HandleFunc("/api/sessions", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(listSessions(sessionsDir))
	})
	mux.HandleFunc("/api/sessions/", func(w http.ResponseWriter, r *http.Request) {
		filename := strings.TrimPrefix(r.URL.Path, "/api/sessions/")
		if strings.Contains(filename, "/") || strings.Contains(filename, "..") {
			http.NotFound(w, r)
			return
		}
		path := filepath.Join(sessionsDir, filename)
		entries := loadEntries(path)
		if entries == nil {
			http.NotFound(w, r)
			return
		}
		meta := buildSessionMeta(path, entries)
		annotateSystemEvents(entries)
		allMeta := listSessions(sessionsDir)
		linked := linkedSessions(meta, allMeta)
		scratchpadHistory := scratchpadHistoryFromEntries(entries)
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]any{
			"entries":            entries,
			"linked_sessions":    linked,
			"scratchpad_history": scratchpadHistory,
		})
	})

	go http.Serve(ln, mux)
	return fmt.Sprintf("http://127.0.0.1:%d", ln.Addr().(*net.TCPAddr).Port), nil
}

const pageHTML = `<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>mimic-go session viewer</title>
<style>
body{font-family:ui-monospace,monospace;background:#141613;color:#e8e6de;margin:0;display:flex;height:100vh}
#list{width:340px;overflow-y:auto;border-right:1px solid #333;padding:8px}
#detail{flex:1;overflow-y:auto;padding:16px}
.item{padding:8px;border-radius:6px;cursor:pointer;margin-bottom:4px;font-size:12px}
.item:hover{background:#222}
.item.active{background:#2a3a2f}
.item.child{margin-left:18px;border-left:2px solid #3a4a3f}
.status{font-size:10px;padding:1px 6px;border-radius:8px;margin-right:6px}
.status.done{background:#1c3a2a;color:#7fc496}
.status.running{background:#3a2f1c;color:#d99b5c}
.status.stale{background:#2a2a2a;color:#888}
.badge{font-size:10px;padding:1px 6px;border-radius:8px;margin-left:4px;background:#2a2a3a;color:#a8b6ff}
.entry{border-left:2px solid #444;padding:6px 10px;margin-bottom:8px}
.entry.user_input{border-color:#8fb6e0}
.entry.final_answer{border-color:#7fc496}
.entry.action{border-color:#d99b5c}
.entry.observation{border-color:#7c7a6f}
.entry.system_event{border-color:#a8b6ff}
pre{white-space:pre-wrap;word-break:break-all;font-size:12px;margin:4px 0}
.ts{color:#7c7a6f;font-size:10px}
details{margin-top:4px}
summary{cursor:pointer;color:#8fb6e0;font-size:11px}
.jkey{color:#8fb6e0}
.jstr{color:#d99b5c}
.jnum{color:#a8d99b}
.jbool{color:#e07c9b}
.jnull{color:#888}
#linked,#scratch{margin-top:16px;padding-top:12px;border-top:1px solid #333}
#linked a{color:#8fb6e0;cursor:pointer;text-decoration:underline}
</style></head>
<body>
<div id="list"></div>
<div id="detail">セッションを選択してください</div>
<script>
let allSessions = [];
async function loadList(){
  const res = await fetch('/api/sessions');
  allSessions = await res.json() || [];
  renderList();
}
function renderList(){
  const list = document.getElementById('list');
  const activeFile = list.dataset.active || '';
  list.innerHTML = '';
  const byFile = {};
  allSessions.forEach(s => byFile[s.file] = s);
  const rendered = new Set();
  function renderItem(s, depth){
    if (rendered.has(s.file)) return;
    rendered.add(s.file);
    const div = document.createElement('div');
    div.className = 'item' + (depth > 0 ? ' child' : '') + (s.file === activeFile ? ' active' : '');
    let badgeHtml = '';
    if (s.badge) badgeHtml = '<span class="badge">' + s.badge.icon + ' ' + escapeHtml(s.badge.label) + '</span>';
    div.innerHTML = '<span class="status '+s.status+'">'+s.status+'</span>' + escapeHtml(s.file) + badgeHtml + '<br><small>' + escapeHtml(s.provider||'') + '/' + escapeHtml(s.model||'') + '</small><br><small>' + escapeHtml(s.first_user||'') + '</small>';
    div.onclick = () => loadDetail(s.file, div);
    list.appendChild(div);
    (s.children||[]).forEach(childFile => {
      const child = byFile[childFile];
      if (child) renderItem(child, depth + 1);
    });
  }
  allSessions.filter(s => s.is_root).forEach(s => renderItem(s, 0));
  // is_rootの判定漏れ（親が別セッションに無い等）のフォールバックで未表示分も出す
  allSessions.forEach(s => { if (!rendered.has(s.file)) renderItem(s, 0); });
}
async function loadDetail(file, el){
  document.getElementById('list').dataset.active = file;
  document.querySelectorAll('.item').forEach(e=>e.classList.remove('active'));
  if (el) el.classList.add('active');
  const res = await fetch('/api/sessions/' + encodeURIComponent(file));
  const data = await res.json();
  const detail = document.getElementById('detail');
  detail.innerHTML = '';
  (data.entries||[]).forEach(e => {
    const div = document.createElement('div');
    div.className = 'entry ' + e.type;
    let body = '';
    if (e.type === 'user_input') body = '<b>User:</b> ' + escapeHtml(e.content||'');
    else if (e.type === 'final_answer') body = '<b>Final:</b> ' + escapeHtml(e.content||'');
    else if (e.type === 'action') body = '<b>Action:</b> ' + escapeHtml(e.tool||'') + ' ' + jsonBlock(e.args||{});
    else if (e.type === 'observation') body = '<b>Observation</b> (' + escapeHtml(e.tool||'') + '):' + textOrJsonBlock(e.result||'');
    else if (e.type === 'session_start') body = '<b>Session start</b> model=' + escapeHtml(e.model||'') + ' provider=' + escapeHtml(e.provider||'') + (e.trace_id ? ' trace_id=' + escapeHtml(e.trace_id) : '');
    else if (e.type === 'system_event') body = '<b>Event:</b> ' + (e.content_obj ? jsonBlock(e.content_obj) : escapeHtml(e.content||''));
    else body = jsonBlock(e);
    div.innerHTML = '<span class="ts">' + escapeHtml(e.ts||'') + '</span><br>' + body;
    detail.appendChild(div);
  });
  renderLinked(data.linked_sessions||[]);
  renderScratchpadHistory(data.scratchpad_history||[]);
}
function renderLinked(linked){
  const old = document.getElementById('linked');
  if (old) old.remove();
  if (!linked.length) return;
  const div = document.createElement('div');
  div.id = 'linked';
  div.innerHTML = '<b>関連セッション:</b><br>' + linked.map(f =>
    '<a onclick="loadDetail(' + JSON.stringify(f) + ')">' + escapeHtml(f) + '</a>').join('<br>');
  document.getElementById('detail').appendChild(div);
}
function renderScratchpadHistory(history){
  const old = document.getElementById('scratch');
  if (old) old.remove();
  if (!history.length) return;
  const div = document.createElement('div');
  div.id = 'scratch';
  let html = '<b>スクラッチパッド更新履歴（' + history.length + '件）:</b>';
  history.slice().reverse().forEach(h => {
    html += '<details><summary>' + escapeHtml(h.ts||'') + '</summary><pre>' + escapeHtml(h.content||'') + '</pre></details>';
  });
  div.innerHTML = html;
  document.getElementById('detail').appendChild(div);
}
// textOrJsonBlock: JSONとしてパースできればjsonBlockで色付け表示、できなければ折りたたみ可能なpreで表示
function textOrJsonBlock(text){
  try {
    const obj = JSON.parse(text);
    return jsonBlock(obj);
  } catch(e) {
    if (text.length > 500) {
      return '<details><summary>' + text.length + '文字（クリックで展開）</summary><pre>' + escapeHtml(text) + '</pre></details>';
    }
    return '<pre>' + escapeHtml(text) + '</pre>';
  }
}
// jsonBlock: JSON値を折りたたみ可能な構文ハイライト付きHTMLへ変換する
function jsonBlock(obj){
  const html = highlightJSON(obj, 0);
  return '<details open><summary>JSON</summary><pre>' + html + '</pre></details>';
}
function highlightJSON(obj, indent){
  const pad = '  '.repeat(indent);
  const pad2 = '  '.repeat(indent+1);
  if (obj === null) return '<span class="jnull">null</span>';
  if (typeof obj === 'boolean') return '<span class="jbool">' + obj + '</span>';
  if (typeof obj === 'number') return '<span class="jnum">' + obj + '</span>';
  if (typeof obj === 'string') return '<span class="jstr">"' + escapeHtml(obj) + '"</span>';
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '[]';
    const items = obj.map(v => pad2 + highlightJSON(v, indent+1)).join(',\n');
    return '[\n' + items + '\n' + pad + ']';
  }
  if (typeof obj === 'object') {
    const keys = Object.keys(obj);
    if (keys.length === 0) return '{}';
    const items = keys.map(k => pad2 + '<span class="jkey">"' + escapeHtml(k) + '"</span>: ' + highlightJSON(obj[k], indent+1)).join(',\n');
    return '{\n' + items + '\n' + pad + '}';
  }
  return escapeHtml(String(obj));
}
function escapeHtml(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
loadList();
setInterval(loadList, 5000);
</script>
</body></html>`
