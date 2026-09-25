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

// writeStreakEntry は書き込み委任1回分の「変更ファイル集合」と「verify結果」。
type writeStreakEntry struct {
	files      map[string]bool
	verifyExit *int // verify_cmd未指定/未実行ならnil
}

var (
	interlockMu sync.Mutex
	writeStreak []writeStreakEntry
)

// noteWriteDelegation は書き込み委任（delegate_to_worker/delegate_to_team）が
// 完了するたびに呼ぶ。直近の変更ファイル集合とverify結果を記録し、古いものは捨てる。
// verifyExitは委任側のverify_cmd実行結果（未実行/未指定ならnil）で、ファイル集合が
// 毎回異なっていても同じ失敗を繰り返しているケースの検知に使う。
func noteWriteDelegation(changedFiles []string, verifyExit *int) {
	interlockMu.Lock()
	defer interlockMu.Unlock()
	set := make(map[string]bool, len(changedFiles))
	for _, f := range changedFiles {
		set[f] = true
	}
	writeStreak = append(writeStreak, writeStreakEntry{files: set, verifyExit: verifyExit})
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
// 2種類の「進展していない」パターンを検知する:
//  1. overlapping: 直近writeStreakLimit回の変更ファイル集合のどれか2つが重なる
//     （同じファイルを繰り返し触っている）。
//  2. sameExitCode: ファイル集合は毎回異なっていても、直近writeStreakLimit回の
//     verify失敗exit codeが全て同一（触るファイルを変えているだけで同じ失敗を
//     繰り返している——弱いモデルが対症療法的に別ファイルへ手を広げる失敗パターン）。
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
			if len(recent[i].files) == 0 || len(recent[j].files) == 0 {
				continue
			}
			for f := range recent[i].files {
				if recent[j].files[f] {
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

	sameExitCode := true
	exitCode := 0
	for i, e := range recent {
		if e.verifyExit == nil || *e.verifyExit == 0 {
			sameExitCode = false
			break
		}
		if i == 0 {
			exitCode = *e.verifyExit
		} else if *e.verifyExit != exitCode {
			sameExitCode = false
			break
		}
	}

	if !overlapping && !sameExitCode {
		return ""
	}

	union := make(map[string]bool)
	for _, e := range recent {
		for f := range e.files {
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

	reason := fmt.Sprintf("同じファイル群（%s）を修正していますが", strings.Join(files, ", "))
	if !overlapping && sameExitCode {
		reason = fmt.Sprintf("ファイルは変えているものの同じ検証失敗(exit=%d)を繰り返しており", exitCode)
	}

	return fmt.Sprintf(
		"[委任拒否: 反復失敗インターロック] 書き込み委任が連続%d回、%s問題が解決していません。\n"+
			"同じアプローチの繰り返しを防ぐため、次の書き込み委任はブロックされました。\n"+
			"先にread_file/grep_codebase等で対象ファイルを自分で精査し、根本原因を診断してから、"+
			"異なるアプローチで再度委任してください。",
		writeStreakLimit, reason)
}
