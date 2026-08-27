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
}

var (
	historyMu sync.Mutex
	history   []delegationHistoryEntry
)

// RecordDelegation は完了した委任の要約を履歴バッファへ記録する。
func RecordDelegation(label, task, status string, changedFiles []string) {
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
	history = append(history, delegationHistoryEntry{Label: label, Task: taskShort, Status: status, ChangedFiles: shown})
	if len(history) > delegationHistoryKeep {
		history = history[len(history)-delegationHistoryKeep:]
	}
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
