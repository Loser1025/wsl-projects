package delegate

import (
	"os"
	"strings"
	"sync"
)

// 適用承認ゲート（Python版 team.py::set_apply_approval_handler /
// _needs_apply_approval の移植）。Workerは全速力で作業し、人間は「適用/破棄」を
// 委任単位の1判断で行う。ポリシーは環境変数APPLY_APPROVALで選択:
//
//	auto      … 常に自動適用（デフォルト・従来挙動、後方互換）
//	ask       … 毎回承認を求める
//	threshold … 変更ファイルがapplyApprovalFileThreshold件を超えたときのみ承認を求める
//
// 承認ハンドラ未登録（--auto-prompt等の非対話実行、Worker自身の再帰委任）時は
// 常に自動適用となる。

const applyApprovalFileThreshold = 3

// ApplyApprovalHandler は委任結果の適用前承認を行うコールバック。
// label（委任の呼称）・changedFiles（変更ファイル一覧）・summary（結果サマリの先頭2000字）
// を受け取り、適用してよければtrueを返す。
type ApplyApprovalHandler func(label string, changedFiles []string, summary string) bool

var (
	applyApprovalMu sync.Mutex
	applyApproval   ApplyApprovalHandler
)

// SetApplyApprovalHandler は適用前承認ハンドラを登録する（TUI側から呼ぶ）。
// nilを渡すと承認なし（常に自動適用）。
func SetApplyApprovalHandler(h ApplyApprovalHandler) {
	applyApprovalMu.Lock()
	applyApproval = h
	applyApprovalMu.Unlock()
}

func applyApprovalPolicy() string {
	mode := strings.ToLower(strings.TrimSpace(os.Getenv("APPLY_APPROVAL")))
	switch mode {
	case "ask", "threshold":
		return mode
	default:
		return "auto"
	}
}

// needsApplyApproval はこの委任の適用前に人間の承認を要するかを判定する。
func needsApplyApproval(changedFiles []string) bool {
	applyApprovalMu.Lock()
	h := applyApproval
	applyApprovalMu.Unlock()
	if h == nil {
		return false
	}
	switch applyApprovalPolicy() {
	case "ask":
		return true
	case "threshold":
		return len(changedFiles) > applyApprovalFileThreshold
	default:
		return false
	}
}

// requestApplyApproval はneedsApplyApprovalがtrueの場合にのみ呼ぶこと。
// ハンドラ異常時は従来挙動（自動適用）に倒す（Python版と同じフェイルセーフ方針）。
func requestApplyApproval(label string, changedFiles []string, summary string) (approved bool) {
	applyApprovalMu.Lock()
	h := applyApproval
	applyApprovalMu.Unlock()
	if h == nil {
		return true
	}
	defer func() {
		if r := recover(); r != nil {
			approved = true
		}
	}()
	return h(label, changedFiles, summary)
}
