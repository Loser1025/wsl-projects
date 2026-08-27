package delegate

import (
	"fmt"
	"sort"
	"strings"
	"sync"
)

// writeStreakLimit と writeStreak は「同じファイル群を書き込み委任で
// 連続修正し続けているのに進展していない」失敗モードを機械的に断つための
// 反復失敗インターロック（Python版 team.py::check_write_interlock の移植）。
const writeStreakLimit = 3

var (
	interlockMu sync.Mutex
	writeStreak []map[string]bool
)

// noteWriteDelegation は書き込み委任（delegate_to_worker/delegate_to_team）が
// 完了するたびに呼ぶ。直近の変更ファイル集合を記録し、古いものは捨てる。
func noteWriteDelegation(changedFiles []string) {
	interlockMu.Lock()
	defer interlockMu.Unlock()
	set := make(map[string]bool, len(changedFiles))
	for _, f := range changedFiles {
		set[f] = true
	}
	writeStreak = append(writeStreak, set)
	if len(writeStreak) > writeStreakLimit+2 {
		writeStreak = writeStreak[len(writeStreak)-(writeStreakLimit+2):]
	}
}

// noteReadonlyDelegation は読み取り専用委任（delegate_to_specialist の
// デフォルト権限分岐）が1回完了するたびに呼ぶ。書き込みストリークをリセットし、
// 次の書き込み委任のブロックを解除する（Python版 team.py::_note_readonly_delegation
// の移植）。
func noteReadonlyDelegation() {
	interlockMu.Lock()
	writeStreak = nil
	interlockMu.Unlock()
}

// checkWriteInterlock は書き込み委任を許可してよいか判定する。
// 拒否する場合は理由を説明する文字列を、許可する場合は空文字を返す。
func checkWriteInterlock() string {
	interlockMu.Lock()
	defer interlockMu.Unlock()
	if len(writeStreak) < writeStreakLimit {
		return ""
	}
	recent := writeStreak[len(writeStreak)-writeStreakLimit:]

	overlapping := false
	for i := 0; i < len(recent); i++ {
		for j := i + 1; j < len(recent); j++ {
			if len(recent[i]) == 0 || len(recent[j]) == 0 {
				continue
			}
			for f := range recent[i] {
				if recent[j][f] {
					overlapping = true
					break
				}
			}
			if overlapping {
				break
			}
		}
		if overlapping {
			break
		}
	}
	if !overlapping {
		return ""
	}

	union := make(map[string]bool)
	for _, s := range recent {
		for f := range s {
			union[f] = true
		}
	}
	files := make([]string, 0, len(union))
	for f := range union {
		files = append(files, f)
	}
	sort.Strings(files)
	if len(files) > 10 {
		files = files[:10]
	}

	return fmt.Sprintf(
		"[委任拒否: 反復失敗インターロック] 書き込み委任が連続%d回、同じファイル群（%s）を修正していますが問題が解決していません。\n"+
			"同じアプローチの繰り返しを防ぐため、次の書き込み委任はブロックされました。\n"+
			"先にread_file/grep_codebase等で対象ファイルを自分で精査し、根本原因を診断してから、"+
			"異なるアプローチで再度委任してください。",
		writeStreakLimit, strings.Join(files, ", "))
}
