package react

import (
	"strings"
	"sync"

	"mimic/internal/delegate"
)

// recentWrites はこのプロセス（Director）内で書き込んだファイルパスの履歴
// （Python版 agent.py::_recent_writes の移植。セッション全体で保持し、
// 直近8件をcontext headerへ自動記録する）。
const recentWritesShown = 8
const recentWritesKeep = 30

var (
	recentWritesMu sync.Mutex
	recentWrites   []string
)

// recordWrite は書き込み系ツールが成功するたびに呼ぶ。同一パスは末尾へ
// 移動（最新順）し、上限を超えた古いものは捨てる。
func recordWrite(path string) {
	if path == "" {
		return
	}
	recentWritesMu.Lock()
	defer recentWritesMu.Unlock()
	for i, p := range recentWrites {
		if p == path {
			recentWrites = append(recentWrites[:i], recentWrites[i+1:]...)
			break
		}
	}
	recentWrites = append(recentWrites, path)
	if len(recentWrites) > recentWritesKeep {
		recentWrites = recentWrites[len(recentWrites)-recentWritesKeep:]
	}
}

// buildMachineNotes は「ハーネスが確実に知っている事実」を整形する
// （Python版 agent.py::_build_machine_notes の移植。タスクゴールの自動記録は
// Go版にその概念自体が無いため対象外——書き込み履歴と委任履歴のみ）。
func buildMachineNotes() string {
	var lines []string

	recentWritesMu.Lock()
	if len(recentWrites) > 0 {
		shown := recentWrites
		if len(shown) > recentWritesShown {
			shown = shown[len(shown)-recentWritesShown:]
		}
		lines = append(lines, "このセッションで書き込んだファイル: "+strings.Join(shown, ", "))
	}
	recentWritesMu.Unlock()

	if brief := delegate.GetDelegationHistoryBrief(3); len(brief) > 0 {
		lines = append(lines, "直近の委任: "+strings.Join(brief, " / "))
	}

	if len(lines) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString("\n\n--- [ハーネス自動記録（機械生成・正確）] ---\n")
	for _, ln := range lines {
		b.WriteString("- " + ln + "\n")
	}
	b.WriteString("--- [自動記録 ここまで] ---")
	return b.String()
}
