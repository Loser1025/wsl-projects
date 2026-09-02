package delegate

import (
	"fmt"
	"strings"
	"sync"
)

// 委任履歴リングバッファ（Python版 team.py::_record_delegation /
// get_delegation_history_brief の移植）。Directorのscratchpad転記に依存せず、
// 直近の委任結果をハーネス側で記録し、次のsystemPromptへ自動注入するために使う。

const delegationHistoryKeep = 5

type delegationHistoryEntry struct {
	Label        string
	Task         string
	Status       string
	ChangedFiles []string
	TraceID      string
}

var (
	historyMu sync.Mutex
	history   []delegationHistoryEntry
)

// RecordDelegation は完了した委任の要約を履歴バッファへ記録する。
func RecordDelegation(label, task, status string, changedFiles []string) {
	RecordDelegationWithTrace(label, task, status, changedFiles, "")
}

// RecordDelegationWithTrace はtrace_id付きで委任履歴を記録する
// （Scratchpadタブのサブエージェント表示[GetRecentWorkerTraceIDs]用。
// Python版 app.py::_refresh_scratchpad_tab はReactLogのsystem_event
// `team_worker_start`からtrace_idを拾うが、Go版はreactLogがinternal/delegateから
// 見えないため、既存の委任履歴リングバッファにtrace_idも保持する形で代替する）。
func RecordDelegationWithTrace(label, task, status string, changedFiles []string, traceID string) {
	historyMu.Lock()
	defer historyMu.Unlock()
	taskShort := strings.Join(strings.Fields(task), " ")
	if len(taskShort) > 120 {
		taskShort = taskShort[:120]
	}
	shown := changedFiles
	if len(shown) > 8 {
		shown = shown[:8]
	}
	history = append(history, delegationHistoryEntry{Label: label, Task: taskShort, Status: status, ChangedFiles: shown, TraceID: traceID})
	if len(history) > delegationHistoryKeep {
		history = history[len(history)-delegationHistoryKeep:]
	}
}

// GetRecentWorkerTraceIDs は直近の委任履歴からtrace_idを重複除去して返す
// （Scratchpadタブでサブエージェント分を表示する際の対象一覧用）。
func GetRecentWorkerTraceIDs() []string {
	historyMu.Lock()
	defer historyMu.Unlock()
	seen := make(map[string]bool)
	var out []string
	for _, e := range history {
		if e.TraceID != "" && !seen[e.TraceID] {
			seen[e.TraceID] = true
			out = append(out, e.TraceID)
		}
	}
	return out
}

// GetDelegationHistoryBrief は直近の委任の1行要約を返す
// （コンテキストヘッダーの自動記録区画用）。
func GetDelegationHistoryBrief(limit int) []string {
	historyMu.Lock()
	defer historyMu.Unlock()
	if limit <= 0 || limit > len(history) {
		limit = len(history)
	}
	start := len(history) - limit
	out := make([]string, 0, limit)
	for _, e := range history[start:] {
		out = append(out, fmt.Sprintf("[%s] %s", e.Label, e.Status))
	}
	return out
}

// RenderDelegationHistory は直近の委任履歴を、委任タスク冒頭へ注入するテキストとして
// 整形する（Python版 team.py::render_delegation_history の移植）。履歴が無ければ空文字。
func RenderDelegationHistory() string {
	historyMu.Lock()
	entries := append([]delegationHistoryEntry(nil), history...)
	historyMu.Unlock()
	if len(entries) == 0 {
		return ""
	}
	lines := []string{"[直近の委任履歴（ハーネス自動記録・あなた以前に行われた作業）]"}
	for _, e := range entries {
		cf := ""
		if len(e.ChangedFiles) > 0 {
			cf = " 変更: " + strings.Join(e.ChangedFiles, ", ")
		}
		lines = append(lines, fmt.Sprintf("- [%s] %s%s", e.Label, e.Status, cf))
		lines = append(lines, "  依頼: "+e.Task)
	}
	lines = append(lines, "※ 上記と矛盾する変更（直前の委任が行った変更を打ち消す等）を行う場合は、"+
		"その理由を最終回答に明記すること。")
	return strings.Join(lines, "\n") + "\n\n"
}

// ClearDelegationHistory は委任履歴・書き込みストリークをリセットする
// （/clear コマンド用。Python版 clear_delegation_history の移植）。
func ClearDelegationHistory() {
	historyMu.Lock()
	history = nil
	historyMu.Unlock()
	interlockMu.Lock()
	writeStreak = nil
	interlockMu.Unlock()
}
