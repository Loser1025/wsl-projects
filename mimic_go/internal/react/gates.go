// 最終回答ゲート（弱いモデルの失敗モードを機械検査で差し戻す）
// Python版 orchestrator.py の _detect_command_offload / _detect_unverified_claim
// および呼び出し側ロジックの移植。「ツールなし応答＝最終回答」を無条件受理せず、
// 観測済みの失敗パターンを受理前に文字列検査する。各ゲートは1ターンにつき
// 1回だけ差し戻す（無限ループ防止）。
package react

import (
	"regexp"
	"strings"
)

var (
	offloadRe = regexp.MustCompile(
		`実行してください|実行して下さい|実行をお願い|お手元で実行|ご自身で実行` +
			`|手動で(?:実行|編集|修正)|以下のコマンドを実行|コマンドを叩いて`)
	offloadExemptRe = regexp.MustCompile(
		`ログイン|認証|サインイン|パスワード|ブラウザで開いて|この環境では実行できな`)
	completionClaimRe = regexp.MustCompile(
		`完了しました|解決しました|完了です|修正しました|対応しました|実装しました|適用しました`)
)

// execCapableTools はGate A判定の対象となる「実行手段を持つツール」の集合
// （Python版 _EXEC_CAPABLE_TOOLS の移植）。
var execCapableTools = map[string]bool{
	"run_bash":                  true,
	"run_pipeline":              true,
	"run_host_command":          true,
	"delegate_to_worker":        true,
	"delegate_to_team":          true,
	"delegate_to_team_parallel": true,
	"delegate_to_specialist":    true,
}

// detectCommandOffload は実行手段を持つのにユーザーへ実行を丸投げしている
// 最終回答を検知する。
func detectCommandOffload(text string, availableTools []string) bool {
	if text == "" {
		return false
	}
	hasExecTool := false
	for _, t := range availableTools {
		if execCapableTools[t] {
			hasExecTool = true
			break
		}
	}
	if !hasExecTool {
		return false
	}
	if !offloadRe.MatchString(text) {
		return false
	}
	return !offloadExemptRe.MatchString(text)
}

// detectUnverifiedClaim は未検証の変更を「完了/解決」と断言している最終回答を検知する。
// turnHadUnverified はこのターン内に「※未検証」の委任結果が存在したかを示す
// （internal/delegate/worker.goがverify_cmd未指定の書き込み委任結果に
// "※未検証（verify_cmd未指定・Workerの自己申告のみ）"を付与し、loop.goがそれを
// 検出してこのフラグを立てる。以前は委任未実装のため常にfalseだったが現在は有効）。
func detectUnverifiedClaim(text string, turnHadUnverified bool) bool {
	if !turnHadUnverified || text == "" {
		return false
	}
	if containsAny(text, "未検証", "動作未確認", "確認できていません") {
		return false
	}
	return completionClaimRe.MatchString(text)
}

func containsAny(s string, subs ...string) bool {
	for _, sub := range subs {
		if strings.Contains(s, sub) {
			return true
		}
	}
	return false
}
