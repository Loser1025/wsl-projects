// Package viewer はReactLogのJSONLセッションをブラウザで閲覧するための
// 軽量HTTPサーバーを実装する（Python版 viewer.py の縮小移植。
// delegate_*(委任)関連のtrace_id紐付け・子セッションバッジ表示は
// 委任未実装のため対象外）。
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

type sessionMeta struct {
	File      string `json:"file"`
	Model     string `json:"model"`
	Provider  string `json:"provider"`
	FirstUser string `json:"first_user"`
	Status    string `json:"status"` // done / running / stale
	Entries   int    `json:"entries"`
}

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
	m := sessionMeta{File: filepath.Base(path), Entries: len(entries)}
	hasFinal := false
	for _, e := range entries {
		t, _ := e["type"].(string)
		switch t {
		case "session_start":
			m.Model, _ = e["model"].(string)
			m.Provider, _ = e["provider"].(string)
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
		}
	}
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
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(map[string]any{"entries": entries})
	})

	go http.Serve(ln, mux)
	return fmt.Sprintf("http://127.0.0.1:%d", ln.Addr().(*net.TCPAddr).Port), nil
}

const pageHTML = `<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>mimic-go session viewer</title>
<style>
body{font-family:ui-monospace,monospace;background:#141613;color:#e8e6de;margin:0;display:flex;height:100vh}
#list{width:320px;overflow-y:auto;border-right:1px solid #333;padding:8px}
#detail{flex:1;overflow-y:auto;padding:16px}
.item{padding:8px;border-radius:6px;cursor:pointer;margin-bottom:4px;font-size:12px}
.item:hover{background:#222}
.item.active{background:#2a3a2f}
.status{font-size:10px;padding:1px 6px;border-radius:8px;margin-right:6px}
.status.done{background:#1c3a2a;color:#7fc496}
.status.running{background:#3a2f1c;color:#d99b5c}
.status.stale{background:#2a2a2a;color:#888}
.entry{border-left:2px solid #444;padding:6px 10px;margin-bottom:8px}
.entry.user_input{border-color:#8fb6e0}
.entry.final_answer{border-color:#7fc496}
.entry.action{border-color:#d99b5c}
.entry.observation{border-color:#7c7a6f}
pre{white-space:pre-wrap;word-break:break-all;font-size:12px}
.ts{color:#7c7a6f;font-size:10px}
</style></head>
<body>
<div id="list"></div>
<div id="detail">セッションを選択してください</div>
<script>
async function loadList(){
  const res = await fetch('/api/sessions');
  const sessions = await res.json();
  const list = document.getElementById('list');
  list.innerHTML = '';
  (sessions||[]).forEach(s => {
    const div = document.createElement('div');
    div.className = 'item';
    div.innerHTML = '<span class="status '+s.status+'">'+s.status+'</span>' + s.file + '<br><small>' + (s.provider||'') + '/' + (s.model||'') + '</small><br><small>' + (s.first_user||'') + '</small>';
    div.onclick = () => loadDetail(s.file, div);
    list.appendChild(div);
  });
}
async function loadDetail(file, el){
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
    else if (e.type === 'action') body = '<b>Action:</b> ' + (e.tool||'') + ' ' + escapeHtml(JSON.stringify(e.args||{}));
    else if (e.type === 'observation') body = '<b>Observation</b> (' + (e.tool||'') + '):<pre>' + escapeHtml(e.result||'') + '</pre>';
    else if (e.type === 'session_start') body = '<b>Session start</b> model=' + (e.model||'') + ' provider=' + (e.provider||'');
    else body = escapeHtml(JSON.stringify(e));
    div.innerHTML = '<span class="ts">' + (e.ts||'') + '</span><br>' + body;
    detail.appendChild(div);
  });
}
function escapeHtml(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
loadList();
setInterval(loadList, 5000);
</script>
</body></html>`
