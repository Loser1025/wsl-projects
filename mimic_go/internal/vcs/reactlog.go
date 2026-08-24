package vcs

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// maxReactLogEntries を超えた分はJSONLに永続化済みなのでRAM上からは破棄してよい
// （Python版 autogit.py::ReactLog._MAX_REACT_LOG_ENTRIES を踏襲）。
const maxReactLogEntries = 3000

// Entry はReActループの1イベント（Thought/Action/Observation等）。
// Python版はkwargsで任意フィールドを持つ辞書だったため、Goでも
// map[string]any をベースにした柔軟な表現とする。
type Entry map[string]any

// ReactLog はReActループのThought/Action/Observationを蓄積・JSONL永続化・
// Markdownエクスポートする（Python版 autogit.py::ReactLog の移植）。
type ReactLog struct {
	mu           sync.Mutex
	entries      []Entry
	sessionStart time.Time
	jsonlPath    string
}

func NewReactLog() *ReactLog {
	return &ReactLog{sessionStart: time.Now()}
}

// SetJSONLPath はJSONL逐次書き込み先を設定する（Python版と異なり、
// 既存ファイルからの復元は行わない簡略版 — チェックポイント再開は
// internal/react.LoadCheckpoint が別途担っているため）。
func (rl *ReactLog) SetJSONLPath(path string) error {
	if dir := filepath.Dir(path); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	rl.mu.Lock()
	rl.jsonlPath = path
	rl.mu.Unlock()
	return nil
}

func (rl *ReactLog) enforceCap() {
	if len(rl.entries) <= maxReactLogEntries {
		return
	}
	head := 0
	if len(rl.entries) > 0 {
		if t, _ := rl.entries[0]["type"].(string); t == "session_start" {
			head = 1
		}
	}
	keepTail := maxReactLogEntries - head
	tail := rl.entries[len(rl.entries)-keepTail:]
	rl.entries = append(append([]Entry{}, rl.entries[:head]...), tail...)
}

// Add は1エントリを追記し、JSONLパス設定済みなら即座に1行追記する。
func (rl *ReactLog) Add(entryType string, fields map[string]any) {
	entry := Entry{"type": entryType, "ts": time.Now().Format("2006-01-02T15:04:05")}
	for k, v := range fields {
		entry[k] = v
	}

	rl.mu.Lock()
	rl.entries = append(rl.entries, entry)
	rl.enforceCap()
	jsonlPath := rl.jsonlPath
	rl.mu.Unlock()

	if jsonlPath == "" {
		return
	}
	data, err := json.Marshal(entry)
	if err != nil {
		return
	}
	f, err := os.OpenFile(jsonlPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	f.Write(data)
	f.Write([]byte("\n"))
}

// ExportMarkdown はエントリ群を人間可読なMarkdownへ書き出す
// （Python版 export_markdown の移植。/sessions等のUIコマンドは
// 本バッチでは未実装のため、呼び出し口は今のところ無い）。
func (rl *ReactLog) ExportMarkdown(path string) (string, error) {
	rl.mu.Lock()
	entries := append([]Entry{}, rl.entries...)
	sessionStart := rl.sessionStart
	rl.mu.Unlock()

	var b strings.Builder
	fmt.Fprintf(&b, "# Session Log\n\n**開始時刻**: %s\n**エントリ数**: %d\n\n---\n\n",
		sessionStart.Format("2006-01-02 15:04:05"), len(entries))

	turn := 0
	currentStep := -1
	levelIcon := map[string]string{"error": "🔴", "warning": "🟡", "info": "ℹ️"}

	for _, e := range entries {
		t, _ := e["type"].(string)
		ts, _ := e["ts"].(string)

		switch t {
		case "user_input":
			turn++
			currentStep = -1
			fmt.Fprintf(&b, "## Turn %d  `%s`\n\n**User**: %v\n\n\n", turn, ts, e["content"])
		case "final_answer":
			fmt.Fprintf(&b, "**Result** `%s`\n\n%v\n\n---\n\n", ts, e["content"])
		case "system_event":
			level, _ := e["level"].(string)
			icon := levelIcon[level]
			if icon == "" {
				icon = "・"
			}
			fmt.Fprintf(&b, "%s `%s` %v\n\n", icon, ts, e["content"])
		case "session_start":
			fmt.Fprintf(&b, "> 🟢 セッション開始 `%s`  model=`%v`  provider=`%v`\n\n", ts, e["model"], e["provider"])
		default:
			step := 0
			if s, ok := e["step"].(int); ok {
				step = s
			} else if s, ok := e["step"].(float64); ok {
				step = int(s)
			}
			if step != currentStep {
				currentStep = step
				fmt.Fprintf(&b, "### Step %d\n\n", step)
			}
			switch t {
			case "thought":
				fmt.Fprintf(&b, "#### 💭 Thought `%s`\n\n%v\n\n", ts, e["content"])
			case "action":
				argsJSON, _ := json.MarshalIndent(e["args"], "", "  ")
				fmt.Fprintf(&b, "#### ⚙ Action: `%v` `%s`\n\n```json\n%s\n```\n\n", e["tool"], ts, argsJSON)
			case "observation":
				result, _ := e["result"].(string)
				if len(result) > 2000 {
					result = result[:2000]
				}
				fmt.Fprintf(&b, "#### 👁 Observation: `%v` `%s`\n\n```\n%s\n```\n\n", e["tool"], ts, result)
			}
		}
	}

	if dir := filepath.Dir(path); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return "", err
		}
	}
	if err := os.WriteFile(path, []byte(b.String()), 0o644); err != nil {
		return "", err
	}
	return fmt.Sprintf("エクスポート完了: %s  (%d エントリ)", path, len(entries)), nil
}

// SaveSession はタイムスタンプ付きセッションファイルに自動保存する。
func (rl *ReactLog) SaveSession(sessionsDir string) (string, error) {
	if err := os.MkdirAll(sessionsDir, 0o755); err != nil {
		return "", err
	}
	rl.mu.Lock()
	ts := rl.sessionStart.Format("2006-01-02_15-04")
	rl.mu.Unlock()
	return rl.ExportMarkdown(filepath.Join(sessionsDir, ts+".md"))
}

// PruneOldSessions はsessionsDir直下の古いJSONL/mdセッションファイルを
// 更新日時の新しい順にkeep件だけ残して削除する（Python版 prune_old_sessions の移植）。
func PruneOldSessions(sessionsDir string, keep int) {
	entries, err := os.ReadDir(sessionsDir)
	if err != nil {
		return
	}
	type fileInfo struct {
		path    string
		modTime time.Time
	}
	var files []fileInfo
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if !strings.HasSuffix(name, ".jsonl") && !strings.HasSuffix(name, ".md") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		files = append(files, fileInfo{filepath.Join(sessionsDir, name), info.ModTime()})
	}
	sort.Slice(files, func(i, j int) bool { return files[i].modTime.After(files[j].modTime) })
	if len(files) <= keep {
		return
	}
	for _, f := range files[keep:] {
		os.Remove(f.path)
	}
}
