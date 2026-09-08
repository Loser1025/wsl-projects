// Package delegate はWorker委任（delegate_to_worker/delegate_to_team/
// delegate_to_specialist）を実装する（Python版 team.py::run_worker_once /
// _run_delegation_core_inner の移植）。role検証・禁止事項フィールド・書き込み
// インターロック（interlock.go）、中断委任マニフェスト・クラッシュ再開・
// タイムアウトウォッチドッグ（registerInflight等）は実装済み。
//
// 対象外: trace_idによるセッション相互リンク（ビューアでの親子委任ツリー表示）。
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

// MaxDelegationConcurrency はWorkerサブプロセスの総同時実行数の上限
// （Python版 team.py::_MAX_DELEGATION_CONCURRENCY = 3 を踏襲）。
// delegate_to_team_parallel等はorchestratorの並列ツール実行経路で呼び出し数ぶん
// 同時に走り得るため、Workerの総数をここで絞る。
const MaxDelegationConcurrency = 3

var delegationSem = make(chan struct{}, MaxDelegationConcurrency)

// teamAutoGit はDirector側のAutoGitインスタンスを共有するための参照
// （Python版 team.py::set_team_autogit の移植）。これを設定しておくことで、
// delegate_to_team/delegate_to_worker等の適用後チェックポイントコミットが
// Directorの通常ターンと同じAutoGitインスタンスに積まれ、ターン終了時の
// squash対象に含まれるようになる。
var teamAutoGit *vcs.AutoGit

// teamSessionsDir はDirector自身の.mimic/sessionsディレクトリへの参照
// （get_delegation_traceツールがtrace_idを逆引きする際に使う）。
var teamSessionsDir string

// SetSessionsDir はDirector（TUI/非対話モード）起動時に一度だけ呼び出す。
func SetSessionsDir(dir string) {
	teamSessionsDir = dir
}

// launchEnvPath/launchProvider/launchModel はDirector自身が起動時に使った
// .envの絶対パスと、選択中のプロバイダー/モデルの参照（SetLaunchContextで
// 一度だけ設定）。Workerサブプロセスはoverlayでcwdが変わるため、`-env`の
// デフォルト（cwd相対の"./.env"）に頼るとDirectorとは別の.env（project_dir側の
// 未設定テンプレート等）を読んでしまう。Python版がload_config()の探索基準を
// 常にパッケージ自身の固定パス（Path(__file__).parent）にすることでこの問題を
// 構造的に回避しているのに対し、Goバイナリには固定インストール先が無いため、
// MIMIC_SESSIONS_DIRと同じ「Directorから明示的に渡す」方式で揃える。
// MIMIC_PROVIDER/MIMIC_MODELの引き継ぎも同じくPython版 __main__.py の移植で、
// Workerが.envの優先順位デフォルト（openrouter→gemini）に固定されず、
// Directorが実際に選択中のプロバイダー・モデルで動作するようにする。
var (
	launchEnvPath  string
	launchProvider string
	launchModel    string
)

// SetLaunchContext はDirector（TUI/非対話モード）起動時に一度だけ呼び出す。
func SetLaunchContext(envPath, provider, model string) {
	launchEnvPath = envPath
	launchProvider = provider
	launchModel = model
}

// SetTeamAutoGit はDirector（TUI/非対話モード）起動時に一度だけ呼び出す。
func SetTeamAutoGit(a *vcs.AutoGit) {
	teamAutoGit = a
}

// teamReactLog はDirector自身のReactLogへの参照（Python版 team.py::_log_team_event
// の移植先）。ビューアの委任親子ツリー表示（internal/viewer）が、Directorの
// セッションJSONLに記録されたsystem_eventからtrace_id紐付け・実行状況バッジを
// 導出できるようにする。
var teamReactLog *vcs.ReactLog

// SetTeamReactLog はDirector（TUI/非対話モード）起動時に一度だけ呼び出す。
func SetTeamReactLog(rl *vcs.ReactLog) {
	teamReactLog = rl
}

// logTeamEvent はDirectorのセッションJSONLへsystem_eventとして委任イベントを
// 記録する（Python版 team.py::_log_team_event の移植。Python版はevent dictを
// そのままcontentへ格納しビューア側でast.literal_evalするが、Go版は同じ役割を
// JSON文字列で担う — Go版のビューアもGo版のログしか読まないため互換性の
// 制約は無い）。
func logTeamEvent(event map[string]any) {
	if teamReactLog == nil {
		return
	}
	data, err := json.Marshal(event)
	if err != nil {
		return
	}
	teamReactLog.Add("system_event", map[string]any{"level": "info", "content": string(data)})
}

const (
	defaultWorkerTimeout = 1800 * time.Second // Python版 _TIMEOUT_SEC を踏襲
	defaultVerifyTimeout = 300 * time.Second  // Python版 _VERIFY_TIMEOUT_SEC を踏襲
	finalMarker          = "===MIMIC_FINAL==="

	// MaxVerifyRetries はverify失敗時の修正再試行上限（Python版 MAX_VERIFY_RETRIES）。
	MaxVerifyRetries = 3

	// MaxResumeAttempts はWorkerが完了マーカーなしで予期せず終了した場合に、
	// 同じOverlay上で（チェックポイントが残っていれば）再起動を試みる上限
	// （Python版 subagent.py::_MAX_RESUME_ATTEMPTS = 3 を踏襲）。
	MaxResumeAttempts = 3

	workerCheckpointRelPath = ".mimic/checkpoint.json"
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
	return runWorkerInWorkroom(ctx, w, task, verifyCmd, rolePrompt, applyChanges, false, nil)
}

// runWorkerInWorkroom は既存のWorkroom内でWorkerを実行する共通処理。
// keepSessionがtrueの場合、Worker起動時にMIMIC_KEEP_CHECKPOINT環境変数を立て、
// Worker自身の会話履歴（サンドボックス内チェックポイント）を正常完了後も
// 消さずに残す（continue_specialistでの追加指示継続用）。
// expectedFilesが空でなければ、実際の変更ファイルと食い違う場合に警告を付す
// （Python版 team.py::expected_files の移植。delegate_to_specialist専用）。
func runWorkerInWorkroom(ctx context.Context, w *sandbox.Workroom, task, verifyCmd, rolePrompt string, applyChanges, keepSession bool, expectedFiles []string) (string, error) {
	// 競合検出用: この時刻以降に本体側(project dir)で変更されたファイルを
	// 適用時に警告する（Python版 team.py:1044 `_t_start = time.time()` の移植）。
	tStart := time.Now()

	select {
	case delegationSem <- struct{}{}:
	default:
		fmt.Fprintf(os.Stderr, "  [delegate] ⏳ 委任スロット待機中（同時実行上限 %d）...\n", MaxDelegationConcurrency)
		select {
		case delegationSem <- struct{}{}:
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
	defer func() { <-delegationSem }()

	if applyChanges {
		if blocked := checkWriteInterlock(); blocked != "" {
			return blocked, nil
		}
	}

	traceID := newTraceID()
	registerInflight(traceID, w.Base, w.Lower, task, rolePrompt, verifyCmd, "worker", rolePrompt, applyChanges)
	defer unregisterInflight(traceID)

	mimicBin, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("自身の実行ファイルパスを取得できませんでした: %w", err)
	}

	// verify_cmd未指定の書き込み委任には、このプロジェクトで過去に検証通過した
	// コマンド、無ければ言語別テンプレート、それも無ければ軽量LLMプローブによる
	// 自動調達を試みる（Python版 team.py::get_learned_verify_cmd /
	// _template_verify_cmd / _suggest_verify_cmd の移植。Python版では
	// _suggest_verify_cmdはdelegate_to_specialist(can_write=True)専用だが、
	// Go版はWorker委任の入口を共通化しているため全delegate_to_*経路に広げている）。
	if verifyCmd == "" && applyChanges {
		if learned := GetLearnedVerifyCmd(w.Lower); learned != "" {
			verifyCmd = learned
		} else if tmpl := TemplateVerifyCmd(w.Lower); tmpl != "" {
			verifyCmd = tmpl
		} else if suggested := suggestVerifyCmd(ctx, task, w.Lower); suggested != "" {
			verifyCmd = suggested
		}
	}

	// 委任履歴（直近の委任の要約）をハーネス側でタスク冒頭に自動注入する。
	// task変数自体は汚さない（履歴記録・結果サマリには元のtaskを使う。
	// Python版 team.py:1046-1048 の移植）。
	currentTask := RenderDelegationHistory() + task
	var summary string
	var verifyExit *int
	var verifyOutput string
	var timedOut bool
	var triedSummaries []string
	var crashed bool
	var crashResumeAttempts int
	lastAttempt := 1

	for attempt := 1; attempt <= 1+MaxVerifyRetries; attempt++ {
		lastAttempt = attempt
		logTeamEvent(map[string]any{
			"event": "team_worker_start", "attempt": attempt, "trace_id": traceID,
			"task": truncateSummary(task, 200), "resumed": attempt > 1,
		})
		launchRes, resumeAttempts, runErr := runWithResume(ctx, w, launchCommand(mimicBin, currentTask, rolePrompt, traceID, w.Lower, keepSession), defaultWorkerTimeout)
		if runErr != nil {
			return "", fmt.Errorf("Worker実行に失敗しました: %w", runErr)
		}
		if launchRes.TimedOut {
			timedOut = true
			break
		}
		crashed = !strings.Contains(launchRes.Output, finalMarker)
		crashResumeAttempts = resumeAttempts
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
			SaveLearnedVerifyCmd(w.Lower, verifyCmd)
			break // 検証通過
		}
		if abortExitCodes[exitCode] {
			ForgetLearnedVerifyCmd(w.Lower, verifyCmd)
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

	// 適用承認ゲート（APPLY_APPROVAL=ask/threshold時のみ発動。既定(auto)や
	// ハンドラ未登録時は常に自動適用＝従来挙動）。Python版 team.py:1121-1130 の移植。
	if len(changed) > 0 && applyChanges && needsApplyApproval(changed) {
		if !requestApplyApproval(task, changed, summary) {
			applyChanges = false
			discardedNote = "（ユーザーが適用を拒否したため変更は破棄されました）"
		}
	}

	var conflictFiles []string
	if applyChanges {
		if len(changed) > 0 {
			// 委任実行中に本体側でも変更されたファイルを検出する（applyは
			// last-writer-winsで上書きするため、警告として差分サマリに載せる。
			// Python版 team.py:1132-1141 の移植）。
			for _, f := range changed {
				dst := filepath.Join(w.Lower, f)
				if info, statErr := os.Stat(dst); statErr == nil && info.ModTime().After(tStart) {
					conflictFiles = append(conflictFiles, f)
				}
			}
			if err := sandbox.ApplyChanges(w, changed); err != nil {
				return "", fmt.Errorf("変更の適用に失敗しました: %w", err)
			}
			if teamAutoGit != nil {
				teamAutoGit.Checkpoint(w.Lower, "delegate", strings.Join(changed, ", "))
			}
		}
		// 書き込みストリークの記録（Python版 team.py:1222-1229 の移植）。
		// 機械検証を通過した変更は「進展」とみなしストリークをリセットする。
		if verifyCmd != "" && verifyExit != nil && *verifyExit == 0 {
			noteReadonlyDelegation()
		} else {
			noteWriteDelegation(changed)
		}
	} else {
		if len(changed) > 0 && discardedNote == "" {
			discardedNote = "（実行専用のため変更は適用されず破棄されました）"
		}
		// 実行専用（変更破棄）の委任完了は読み取り専用委任と同様に扱いストリークをリセットする。
		noteReadonlyDelegation()
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
	if verifyCmd == "" && applyChanges {
		// verify_cmd未指定のまま書き込み委任が完了した場合、Workerの自己申告のみを
		// 根拠に「完了」と断言されるのを防ぐため明示的にラベルを付ける
		// （Python版 team.py:1179 " ※未検証（verify_cmd未指定・Workerの自己申告のみ）"の移植。
		// 最終回答ゲートB(detectUnverifiedClaim)がこの文字列を検出条件に使う）。
		verifySection = "\n\n[検証] ※未検証（verify_cmd未指定・Workerの自己申告のみ）"
	}
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

	// ── ハーネスによる機械判定（Workerの自己申告に依存しない注記） ──
	// Python版 team.py::_run_delegation_core_inner の該当ロジックの移植。
	harnessNote := ""
	if applyChanges && len(changed) == 0 {
		harnessNote += "\n\n⚠ ハーネス判定: 書き込み権限（can_write）の委任ですが、変更ファイルは0件でした。" +
			"Workerの完了報告と矛盾する場合、タスクは実施されていない可能性があります。" +
			"結果を鵜呑みにせず、読み取り専用の委任で実ファイルの状態を確認してください。"
	}
	if len(expectedFiles) > 0 && len(changed) > 0 {
		expectedSet := make(map[string]bool, len(expectedFiles))
		for _, f := range expectedFiles {
			expectedSet[strings.TrimPrefix(f, "./")] = true
		}
		var unexpected []string
		for _, f := range changed {
			if !expectedSet[f] {
				unexpected = append(unexpected, f)
			}
		}
		if len(unexpected) > 0 {
			shown := unexpected
			if len(shown) > 10 {
				shown = shown[:10]
			}
			harnessNote += fmt.Sprintf("\n\n⚠ ハーネス判定: 変更予定（expected_files）に含まれないファイルが変更されました: %s\n"+
				"意図した変更範囲からの逸脱がないか差分サマリを確認してください。", strings.Join(shown, ", "))
		}
	}

	if len(conflictFiles) > 0 {
		harnessNote += fmt.Sprintf("\n\n⚠ 競合の可能性: 委任実行中にプロジェクト側でも変更されていたファイルを上書きしました: %s",
			strings.Join(conflictFiles, ", "))
	}

	crashNote := ""
	if crashed {
		crashNote = fmt.Sprintf("⚠ Workerが完了シグナルなしで終了しました（再開試行: %d/%d回）。\n", crashResumeAttempts, MaxResumeAttempts)
	}
	result := fmt.Sprintf("%s[Worker] (trace_id=%s) 変更ファイル数: %d %s\n%s\n\n[Workerの報告]\n%s%s%s",
		crashNote, traceID, len(changed), discardedNote, strings.Join(changed, ", "), summary, verifySection, harnessNote)

	// 委任履歴リングバッファへ記録（Python版 team.py::_record_delegation の移植）。
	// 次のsystemPrompt構築時にcontext headerへ自動注入される。
	statusLabel := "✓完了"
	switch {
	case crashed:
		statusLabel = "⚠完了シグナルなし"
	case verifyExit != nil && *verifyExit == 0:
		statusLabel = "✓検証通過"
	case verifyExit != nil:
		statusLabel = "✗検証失敗"
	}
	RecordDelegationWithTrace("Worker", task, statusLabel, changed, traceID)

	// ビューアの委任実行状況バッジ用（Python版 team_supervisor_verdict イベントに
	// 相当。Go版にはResearcher/Supervisor段階が無いため、Worker完了時点の結果を
	// そのままverdictとして記録する）。
	verdictStatus := "ok"
	if crashed || (verifyExit != nil && *verifyExit != 0) {
		verdictStatus = "fail"
	}
	logTeamEvent(map[string]any{
		"event": "team_supervisor_verdict", "trace_id": traceID,
		"status": verdictStatus, "attempt": lastAttempt,
	})

	return result, nil
}

// runWithResume はWorkerを起動し、完了マーカーなしで予期せず終了した場合、
// タイムアウトしておらずチェックポイントが残っている限り、同じOverlay上で
// 最大MaxResumeAttempts回まで再起動する（Python版 subagent.py の
// resume_attemptループの移植）。戻り値の第2引数は実際に再開した回数。
func runWithResume(ctx context.Context, w *sandbox.Workroom, command string, timeout time.Duration) (sandbox.RunResult, int, error) {
	var last sandbox.RunResult
	for resumeAttempt := 0; resumeAttempt <= MaxResumeAttempts; resumeAttempt++ {
		res, err := w.Run(ctx, command, timeout)
		if err != nil {
			return res, resumeAttempt, err
		}
		last = res
		if res.TimedOut || strings.Contains(res.Output, finalMarker) {
			return last, resumeAttempt, nil
		}
		// チェックポイントが無ければ再開しても意味がないため打ち切る。
		if _, statErr := os.Stat(filepath.Join(w.Upper, workerCheckpointRelPath)); statErr != nil {
			return last, resumeAttempt, nil
		}
	}
	return last, MaxResumeAttempts, nil
}

func launchCommand(mimicBin, task, rolePrompt, traceID, lowerDir string, keepSession bool) string {
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
	// MIMIC_TRACE_ID/MIMIC_SESSIONS_DIRはWorker自身のsession_startイベントに
	// trace_idを記録させ、実プロジェクトのsessionsディレクトリへ直接書き込ませる
	// （unshare -m は既存パスへのアクセスを妨げないため、lowerDir=実プロジェクトへの
	// 絶対パスはOverlay越しでなくそのまま書き込める）。Director側の
	// get_delegation_traceツールがこのtrace_idでセッションjsonlを逆引きできるようにする
	// （Python版 __main__.py::MIMIC_TRACE_ID / viewer.py::get_session_trace_text の移植）。
	traceExport := ""
	if traceID != "" {
		sessionsDir := lowerDir + "/.mimic/sessions"
		traceExport = fmt.Sprintf("export MIMIC_TRACE_ID=%s\nexport MIMIC_SESSIONS_DIR=%s\n",
			shellQuote(traceID), shellQuote(sessionsDir))
	}
	// Directorが使っている.envの絶対パスをWorkerにも明示的に渡す（project_dirの
	// cwd相対 "./.env" 解決に頼らせない）。プロバイダー/モデルも合わせて渡し、
	// Workerが.envの先頭優先設定に落ちずDirectorと同じもので動くようにする。
	providerExport := ""
	if launchProvider != "" {
		providerExport = fmt.Sprintf("export MIMIC_PROVIDER=%s\n", shellQuote(launchProvider))
		if launchModel != "" {
			providerExport += fmt.Sprintf("export MIMIC_MODEL=%s\n", shellQuote(launchModel))
		}
	}
	envFlag := ""
	if launchEnvPath != "" {
		envFlag = "-env " + shellQuote(launchEnvPath) + " "
	}
	return fmt.Sprintf("export MIMIC_NO_AUTOGIT=1\n%s%s%s%s%s %s-auto-prompt %s",
		roleExport, keepExport, traceExport, providerExport, shellQuote(mimicBin), envFlag, shellQuote(task))
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
