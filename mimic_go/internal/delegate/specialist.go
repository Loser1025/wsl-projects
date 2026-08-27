package delegate

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"

	"mimic/internal/llm"
	"mimic/internal/sandbox"
	"mimic/internal/tools"
)

// roleMinChars はrole説明文の最低文字数（Python版 _ROLE_MIN_CHARS）。
const roleMinChars = 20

// roleForbiddenKeywords はroleに「禁止事項」が明記されているとみなすキーワード
// （Python版 _ROLE_FORBIDDEN_KEYWORDS）。既定では未記載でも拒否しないが、
// 環境変数MIMIC_ROLE_REQUIRE_FORBIDDEN=1を立てると必須項目として拒否化できる
// （Python版と同じ2段階導入方針。以前はこの変数自体が一度も参照されず、
// チェック自体が呼ばれないデッドコードになっていたため修正）。
var roleForbiddenKeywords = []string{"禁止事項", "禁止:", "してはいけない"}

// roleRequireForbidden はMIMIC_ROLE_REQUIRE_FORBIDDEN=1が設定されているかを返す
// （Python版 _role_require_forbidden の移植）。
func roleRequireForbidden() bool {
	return strings.TrimSpace(os.Getenv("MIMIC_ROLE_REQUIRE_FORBIDDEN")) == "1"
}

// validateSpecialistRole はdelegate_to_specialistのroleを検証する。
// 問題があればエラー文字列を、問題なければ空文字を返す
// （Python版 team.py::validate_specialist_role の移植）。
func validateSpecialistRole(role string) string {
	role = strings.TrimSpace(role)
	var problems []string
	if len(role) < roleMinChars {
		problems = append(problems, fmt.Sprintf("roleが短すぎます（%d文字 < %d文字）", len([]rune(role)), roleMinChars))
	}
	if !strings.Contains(role, "完了基準") {
		problems = append(problems, "roleに「完了基準」の明記がありません")
	}
	hasForbidden := false
	for _, kw := range roleForbiddenKeywords {
		if strings.Contains(role, kw) {
			hasForbidden = true
			break
		}
	}
	if !hasForbidden && roleRequireForbidden() {
		problems = append(problems, "roleに「禁止事項」の明記がありません")
	}
	if len(problems) == 0 {
		return ""
	}
	return "[委任拒否: role不備] " + strings.Join(problems, " / ") + "\n" +
		"roleは以下のテンプレートを埋めて再送してください（このチェックは機械的な文字列検査です）:\n" +
		"  視点: <どの専門性・観点で作業するか>\n" +
		"  制約: <やってはいけないこと・守るべき既存の流儀>\n" +
		"  禁止事項: <境界外ファイルへの書き込み・破壊的コマンド等、明示的に除外すること>\n" +
		"  完了基準: <何が確認できたらタスク完了とみなすか（検証可能な形で）>"
}

// structuredAnswerGuidance はPython版 team.py::STRUCTURED_ANSWER_GUIDANCE の移植。
const structuredAnswerGuidance = `
# 最終回答の形式（必須）
最終回答は必ず以下の4見出しで構成すること（該当なしの項目は「なし」と書く）:
【結論】タスクの結果を1〜3行で
【変更・実施内容】変更/実行したファイル・コマンドと内容
【残課題】未解決の問題・確認できなかったこと
【次の推奨】依頼元が次に行うべきこと
`

// buildDynamicSystemPrompt はDirectorが自由記述したロール説明から
// システムプロンプトを組み立てる（Python版 team.py::_build_dynamic_system_prompt
// の移植。ブラウザツールの案内はGo版未実装のため含めない）。
func buildDynamicSystemPrompt(role string, canWrite, canExecute bool) string {
	var toolsDesc string
	switch {
	case canWrite:
		toolsDesc = "- ファイルの読み書き・シェル実行・検索・Web調査など、委任以外の全ツールが使える\n" +
			"- 変更はOverlayFS隔離された作業部屋で行われ、タスク完了後にプロジェクトへ適用される\n"
	case canExecute:
		toolsDesc = "- ファイル読み取り・検索・Web調査に加え、run_bash / run_pipeline でコマンド（テスト・ビルド・診断等）を実行できる\n" +
			"- **作業部屋はOverlayFS隔離されており、ファイルへの変更はタスク終了後に破棄される。**実行・診断・分析と、その結果の報告に集中すること（修正の実装は行わない）\n"
	default:
		toolsDesc = "- read_file, grep_codebase, file_info, smart_read, get_repo_map でプロジェクト内を調査できる\n" +
			"- web_search / fetch_webpage で外部情報を調べられる（書き込み・コマンド実行は不可）\n"
	}
	return fmt.Sprintf(
		"あなたは以下の専門家ロールで動作するエージェントです。\n\n"+
			"# ロール\n%s\n\n# 使えるツール\n%s\n# 重要\nロールの専門性に集中し、範囲外の作業は行わない。"+
			"最終回答は日本語で簡潔に結果のみ伝える。\n%s",
		role, toolsDesc, structuredAnswerGuidance)
}

// RunSpecialistTask はrole検証済みの自由記述ロールでタスクを実行する
// （Python版 team.py::run_specialist_task の移植。3段階権限:
// 読み取り専用（デフォルト）/ can_execute=True（実行専用、変更は破棄）/
// can_write=True（実装・適用）。expectedFilesが空でなければ、実際の変更
// ファイルが想定外の場合に警告を付す）。
func RunSpecialistTask(ctx context.Context, client *llm.Client, baseRegistry *tools.Registry,
	role, task, projectDir, verifyCmd string, canWrite, canExecute bool, expectedFiles []string) (string, error) {

	dynamicPrompt := buildDynamicSystemPrompt(role, canWrite, canExecute)

	if !canWrite && !canExecute {
		// 直前の別実行分の取りこぼしをこの委任の集計に混ぜないため破棄
		// （Python版 team.py:966-967 の移植）。
		tools.PopUsedSkills()
		registry := baseRegistry.Subset(researcherTools)
		// 委任履歴を作業フォルダ通知に続けてタスク冒頭へ注入する（Python版 team.py:969-973 の移植）。
		prompt := fmt.Sprintf("[作業フォルダ] %s\n\n%s[タスク]\n%s\n", projectDir, RenderDelegationHistory(), task)
		answer, err := runIsolated(ctx, client, dynamicPrompt, prompt, registry, roundsForSpecialist(role, task))
		if err != nil {
			return "", fmt.Errorf("Specialist実行に失敗しました: %w", err)
		}
		// インプロセスSkill使用のverify結果をtrustスコアに反映する
		// （Python版 team.py:980-983 の移植。read-onlyには機械verify_cmdが無いため、
		// 「ラウンド上限未到達で完了」をverifyPassed相当として扱う）。
		completed := strings.TrimSpace(answer) != "" && !strings.HasPrefix(answer, "[ラウンド上限到達")
		for _, skillName := range tools.PopUsedSkills() {
			tools.RecordSkillOutcome(projectDir, skillName, completed)
		}
		// ロール保存は完了した委任のみ（Python版 run_specialist_task の読み取り専用分岐の移植）。
		if completed {
			SaveSpecialistRole(role, "read")
			// 読み取り専用委任の完了で書き込みストリークをリセットする
			// （Python版 team.py:987 `_note_readonly_delegation()` の移植）。
			noteReadonlyDelegation()
		}
		return "[Specialist:読取専用] " + answer, nil
	}

	if !canWrite {
		// can_execute=True（実行専用）はセッション継続の対象外
		// （Python版もcan_write=Trueの完了時のみセッションWorkerを保持する）。
		result, err := RunWorkerOnce(ctx, task, projectDir, verifyCmd, dynamicPrompt, false)
		if err != nil {
			return "", err
		}
		// ロール保存は機械検証を通過した委任のみ（自己申告の「完了」では保存しない）。
		if strings.Contains(result, "✓ 通過しました") {
			SaveSpecialistRole(role, "execute")
		}
		return "[Specialist:実行専用] " + result, nil
	}

	w, err := sandbox.NewWorkroom(projectDir)
	if err != nil {
		return "", fmt.Errorf("workroom作成に失敗しました: %w", err)
	}
	result, err := runWorkerInWorkroom(ctx, w, task, verifyCmd, dynamicPrompt, true, true, expectedFiles)
	if err != nil {
		w.Cleanup()
		return "", err
	}
	setSessionWorker(w, dynamicPrompt, projectDir, verifyCmd)
	if strings.Contains(result, "✓ 通過しました") {
		SaveSpecialistRole(role, "write")
	}
	return "[Specialist:実装] " + result + "\n\n(continue_specialistで同じセッションに追加指示を出せます)", nil
}

// ── セッションWorker（continue_specialist用） ──────────────────────
// can_write=Trueの委任完了後もOverlay(workroom)と会話チェックポイントを破棄せず
// 保持し、continue_specialistで「前回の続き」として追加指示を出せるようにする
// （Python版 team.py::_set_session_worker / _get_session_worker の移植。
// 保持は常に最新1件のみ）。

type sessionWorkerState struct {
	workroom   *sandbox.Workroom
	rolePrompt string
	projectDir string
	verifyCmd  string
}

var (
	sessionMu sync.Mutex
	session   *sessionWorkerState
)

func setSessionWorker(w *sandbox.Workroom, rolePrompt, projectDir, verifyCmd string) {
	sessionMu.Lock()
	old := session
	session = &sessionWorkerState{workroom: w, rolePrompt: rolePrompt, projectDir: projectDir, verifyCmd: verifyCmd}
	sessionMu.Unlock()
	if old != nil && old.workroom != w {
		old.workroom.Cleanup()
	}
}

func getSessionWorker() *sessionWorkerState {
	sessionMu.Lock()
	defer sessionMu.Unlock()
	return session
}

// DiscardSessionWorker は保持中のセッションWorkerを破棄する（/clearコマンドから
// 呼ばれる。Python版 team.py::discard_session_worker の移植）。
func DiscardSessionWorker() {
	sessionMu.Lock()
	old := session
	session = nil
	sessionMu.Unlock()
	if old != nil {
		old.workroom.Cleanup()
	}
}

// RunSpecialistContinue は保持中のセッションWorkerに追加指示を出し、
// 前回の会話+Overlayの続きで実行する（Python版 team.py::run_specialist_continue
// の移植。中断委任マニフェスト・クラッシュ再開との連携部分は未移植）。
func RunSpecialistContinue(ctx context.Context, task, verifyCmd string) (string, error) {
	s := getSessionWorker()
	if s == nil {
		return "[継続不可] 保持中のセッションWorkerがありません（未実行・破棄済み）。\n" +
			"delegate_to_specialist(can_write=true) で新しい委任を開始してください。", nil
	}
	if blocked := checkWriteInterlock(); blocked != "" {
		return blocked, nil
	}
	if verifyCmd == "" {
		verifyCmd = s.verifyCmd
	}
	result, err := runWorkerInWorkroom(ctx, s.workroom, task, verifyCmd, s.rolePrompt, true, true, nil)
	if err != nil {
		return "", err
	}
	return "[Continue] " + result, nil
}
