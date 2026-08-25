// Package delegate はResearcherを介さない最小構成のWorker委任を実装する
// （Python版 team.py::run_worker_once / _run_delegation_core_inner の縮小移植）。
//
// 対象外（v2ロードマップ フェーズ3の次ステップ以降）:
//   - Researcher段階（計画のJSON構造化）
//   - role検証・禁止事項フィールド・書き込みインターロック
//   - 中断委任マニフェスト・クラッシュ再開・タイムアウトウォッチドッグ
//   - trace_idによるセッション相互リンク（ビューアでの親子表示）
//   - 委任同時実行数セマフォ（並列委任は現状delegate_to_worker単発呼び出しのみのため不要）
//
// verify_cmd失敗時は同じOverlay上でWorkerが最大MaxVerifyRetries回まで修正再試行する
// （Python版のReflexionブロックも簡略版として移植: 直前の失敗要約のみ次の指示に含める）。
package delegate

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"mimic/internal/sandbox"
	"mimic/internal/tools"
	"mimic/internal/vcs"
)

// teamAutoGit はDirector側のAutoGitインスタンスを共有するための参照
// （Python版 team.py::set_team_autogit の移植）。これを設定しておくことで、
// delegate_to_team/delegate_to_worker等の適用後チェックポイントコミットが
// Directorの通常ターンと同じAutoGitインスタンスに積まれ、ターン終了時の
// squash対象に含まれるようになる。
var teamAutoGit *vcs.AutoGit

// SetTeamAutoGit はDirector（TUI/非対話モード）起動時に一度だけ呼び出す。
func SetTeamAutoGit(a *vcs.AutoGit) {
	teamAutoGit = a
}

const (
	defaultWorkerTimeout = 1800 * time.Second // Python版 _TIMEOUT_SEC を踏襲
	defaultVerifyTimeout = 300 * time.Second  // Python版 _VERIFY_TIMEOUT_SEC を踏襲
	finalMarker          = "===MIMIC_FINAL==="

	// MaxVerifyRetries はverify失敗時の修正再試行上限（Python版 MAX_VERIFY_RETRIES）。
	MaxVerifyRetries = 3
)

// abortExitCodes はWorkerが修正不可能な失敗として即座にリトライを打ち切る終了コード
// （2=bash構文エラー、126=権限なし、127=コマンド不明。Python版と同じ判定基準）。
var abortExitCodes = map[int]bool{2: true, 126: true, 127: true}

// RunWorkerOnce はサンドボックス内でWorker（自分自身のバイナリを--auto-promptで
// 再帰起動）を実行し、verify_cmd指定時は失敗するたびに同じOverlay上で最大
// MaxVerifyRetries回まで修正再試行してから、変更を実プロジェクトへ適用する。
// rolePromptが空でなければ、Worker起動時にMIMIC_ROLE_PROMPT環境変数として渡し、
// システムプロンプトの先頭に付加させる（delegate_to_specialist用）。
// applyChanges=falseの場合、変更は実プロジェクトへ適用せず破棄する
// （can_execute=True・実行専用Specialist用。verify/実行はそのまま行われる）。
// Workroomは毎回新規作成し、完了後に破棄する（継続不可の単発実行）。
func RunWorkerOnce(ctx context.Context, task, projectDir, verifyCmd, rolePrompt string, applyChanges bool) (string, error) {
	w, err := sandbox.NewWorkroom(projectDir)
	if err != nil {
		return "", fmt.Errorf("workroom作成に失敗しました: %w", err)
	}
	defer w.Cleanup()
	return runWorkerInWorkroom(ctx, w, task, verifyCmd, rolePrompt, applyChanges, false)
}

// runWorkerInWorkroom は既存のWorkroom内でWorkerを実行する共通処理。
// keepSessionがtrueの場合、Worker起動時にMIMIC_KEEP_CHECKPOINT環境変数を立て、
// Worker自身の会話履歴（サンドボックス内チェックポイント）を正常完了後も
// 消さずに残す（continue_specialistでの追加指示継続用）。
func runWorkerInWorkroom(ctx context.Context, w *sandbox.Workroom, task, verifyCmd, rolePrompt string, applyChanges, keepSession bool) (string, error) {
	if applyChanges {
		if blocked := checkWriteInterlock(); blocked != "" {
			return blocked, nil
		}
	}

	mimicBin, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("自身の実行ファイルパスを取得できませんでした: %w", err)
	}

	currentTask := task
	var summary string
	var verifyExit *int
	var verifyOutput string
	var timedOut bool
	var triedSummaries []string

	for attempt := 1; attempt <= 1+MaxVerifyRetries; attempt++ {
		launchRes, runErr := w.Run(ctx, launchCommand(mimicBin, currentTask, rolePrompt, keepSession), defaultWorkerTimeout)
		if runErr != nil {
			return "", fmt.Errorf("Worker実行に失敗しました: %w", runErr)
		}
		if launchRes.TimedOut {
			timedOut = true
			break
		}
		summary = extractFinalAnswer(launchRes.Output)

		if verifyCmd == "" {
			break
		}
		verifyRes, vErr := w.Run(ctx, verifyCmd, defaultVerifyTimeout)
		if vErr != nil {
			return "", fmt.Errorf("検証コマンド実行に失敗しました: %w", vErr)
		}
		if verifyRes.TimedOut {
			verifyOutput = "(検証コマンドがタイムアウトしました)"
			break
		}
		exitCode := verifyRes.ExitCode
		verifyExit = &exitCode
		verifyOutput = verifyRes.Output

		if exitCode == 0 {
			break // 検証通過
		}
		if abortExitCodes[exitCode] {
			break // Workerが修正できない種類の失敗 → リトライ中止
		}
		if attempt > MaxVerifyRetries {
			break // 試行上限
		}
		triedSummaries = append(triedSummaries, truncateSummary(summary, 200))
		currentTask = buildVerifyRetryTask(task, verifyCmd, exitCode, verifyOutput, attempt, triedSummaries)
	}

	if timedOut {
		return fmt.Sprintf("[Worker] タイムアウトしました（%s経過）。変更は破棄されました。", defaultWorkerTimeout), nil
	}

	changed, err := w.ChangedFiles()
	if err != nil {
		return "", fmt.Errorf("差分の取得に失敗しました: %w", err)
	}
	changed = dedupe(changed)
	discardedNote := ""
	if applyChanges {
		if len(changed) > 0 {
			if err := sandbox.ApplyChanges(w, changed); err != nil {
				return "", fmt.Errorf("変更の適用に失敗しました: %w", err)
			}
			if teamAutoGit != nil {
				teamAutoGit.Checkpoint(w.Lower, "delegate", strings.Join(changed, ", "))
			}
		}
		noteWriteDelegation(changed)
	} else if len(changed) > 0 {
		discardedNote = "（実行専用のため変更は適用されず破棄されました）"
	}

	// Workerがload_skillを使っていれば、machine verify結果を信頼スコアに反映する
	// （verify_cmd未指定の実行は自己申告のみなのでスコア対象外。Python版
	// team.py::_run_delegation_core_inner の該当ロジックの移植）。
	if verifyExit != nil {
		for _, skillName := range findSkillUsagesInUpper(w.Upper, changed) {
			tools.RecordSkillOutcome(w.Lower, skillName, *verifyExit == 0)
		}
	}

	verifySection := ""
	if verifyCmd != "" {
		switch {
		case verifyExit == nil:
			verifySection = "\n\n[検証] タイムアウト等のため結果を取得できませんでした。"
		case *verifyExit == 0:
			verifySection = "\n\n[検証] ✓ 通過しました。"
		default:
			out := verifyOutput
			if len(out) > 2000 {
				out = out[len(out)-2000:]
			}
			retriedNote := ""
			if len(triedSummaries) > 0 {
				retriedNote = fmt.Sprintf("（%d回試行後もなお失敗）", len(triedSummaries)+1)
			}
			verifySection = fmt.Sprintf("\n\n[検証] ✗ 失敗(exit=%d)%s\nコマンド: %s\n%s",
				*verifyExit, retriedNote, verifyCmd, out)
		}
	}

	result := fmt.Sprintf("[Worker] 変更ファイル数: %d %s\n%s\n\n[Workerの報告]\n%s%s",
		len(changed), discardedNote, strings.Join(changed, ", "), summary, verifySection)
	return result, nil
}

func launchCommand(mimicBin, task, rolePrompt string, keepSession bool) string {
	// Worker自身にはAutoGitのbackup/checkpoint/squashを行わせない
	// （upperdirに.gitの変更が混入し差分サマリが汚染されるのを防ぐ。
	// Python版 NullAutoGit と同じ意図をMIMIC_NO_AUTOGIT環境変数で伝える）。
	roleExport := ""
	if rolePrompt != "" {
		roleExport = fmt.Sprintf("export MIMIC_ROLE_PROMPT=%s\n", shellQuote(rolePrompt))
	}
	keepExport := ""
	if keepSession {
		keepExport = "export MIMIC_KEEP_CHECKPOINT=1\n"
	}
	return fmt.Sprintf("export MIMIC_NO_AUTOGIT=1\n%s%s%s -auto-prompt %s", roleExport, keepExport, shellQuote(mimicBin), shellQuote(task))
}

// buildVerifyRetryTask はverify失敗フィードバックを含む修正指示文を生成する
// （Python版 _build_verify_retry_task の縮小移植。Reflexionブロックは
// 常時有効の簡略版とする——設定フラグ化はしない）。
func buildVerifyRetryTask(originalTask, verifyCmd string, exitCode int, output string, attempt int, tried []string) string {
	tail := output
	if len(tail) > 3000 {
		tail = "…（出力省略、末尾3000文字のみ表示）\n" + tail[len(tail)-3000:]
	}
	reflexion := ""
	if len(tried) > 0 {
		var lines []string
		for i, s := range tried {
			lines = append(lines, fmt.Sprintf("  試行%d: %s", i+1, s))
		}
		reflexion = fmt.Sprintf("\n[既に失敗した方針（繰り返さないこと）]\n%s\n"+
			"上記と同じ変更内容を繰り返しても検証は通りません。エラーメッセージから原因を再分析し、これまでと異なるアプローチを取ってください。\n",
			strings.Join(lines, "\n"))
	}
	return fmt.Sprintf(
		"%s\n\n[検証失敗 — 修正してください（試行 %d/%d）]\n検証コマンド: %s\n終了コード: %d\n出力:\n%s\n%s\n"+
			"前回の変更内容はOverlay上に残っています。エラーを修正し、検証が通るようにしてください。",
		originalTask, attempt, MaxVerifyRetries, verifyCmd, exitCode, tail, reflexion)
}

func truncateSummary(s string, max int) string {
	s = strings.Join(strings.Fields(s), " ")
	if len(s) > max {
		return s[:max]
	}
	return s
}

// extractFinalAnswer は --auto-prompt の出力から MIMIC_FINAL マーカー以降を取り出す。
func extractFinalAnswer(output string) string {
	idx := strings.Index(output, finalMarker)
	if idx < 0 {
		return strings.TrimSpace(output)
	}
	return strings.TrimSpace(output[idx+len(finalMarker):])
}

// findSkillUsagesInUpper はWorker自身のセッションJSONL（changedFiles中の
// .mimic/sessions/*.jsonl、実体はupperdir上）を走査し、load_skillツールで
// 使われたSkill名の集合を返す（Python版 skills.py::find_session_skill_usages
// の縮小移植。trace_idによる紐付けは行わず、このWorker実行の変更ファイルに
// 含まれるセッションログを全て対象にする）。
func findSkillUsagesInUpper(upperDir string, changedFiles []string) []string {
	seen := make(map[string]bool)
	var names []string
	for _, rel := range changedFiles {
		if !strings.HasPrefix(rel, ".mimic/sessions/") || !strings.HasSuffix(rel, ".jsonl") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(upperDir, rel))
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var entry struct {
				Type string `json:"type"`
				Tool string `json:"tool"`
				Args struct {
					Name string `json:"name"`
				} `json:"args"`
			}
			if err := json.Unmarshal([]byte(line), &entry); err != nil {
				continue
			}
			if entry.Type == "action" && entry.Tool == "load_skill" && entry.Args.Name != "" && !seen[entry.Args.Name] {
				seen[entry.Args.Name] = true
				names = append(names, entry.Args.Name)
			}
		}
	}
	return names
}

func dedupe(files []string) []string {
	seen := make(map[string]bool)
	var out []string
	for _, f := range files {
		if !seen[f] {
			seen[f] = true
			out = append(out, f)
		}
	}
	return out
}

func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}
