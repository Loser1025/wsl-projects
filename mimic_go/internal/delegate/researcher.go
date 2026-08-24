package delegate

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"mimic/internal/llm"
	"mimic/internal/tools"
)

// isolatedMaxRounds はResearcherの最大ラウンド数（Python版 _ISOLATED_MAX_ROUNDS）。
const isolatedMaxRounds = 8

// researcherTools はResearcherに与える読み取り専用+Web系ツールの一覧
// （Python版 _RESEARCHER_TOOLS を踏襲。read_tool_cache/load_skill/list_skillsは
// Go版で対応するツールが揃っているためそのまま含める）。
var researcherTools = []string{
	"read_file", "get_repo_map", "grep_codebase", "file_info", "smart_read",
	"web_search", "fetch_webpage", "load_skill", "list_skills",
}

// researcherSystemPrompt はPython版 team.py::RESEARCHER_SYSTEM_PROMPT の移植。
const researcherSystemPrompt = `あなたは調査役（Researcher）です。
Director（指示役）から渡された「元の指示」を実現するために必要な調査を行い、
その結果をもとに、Workerがそのまま着手できる具体的な設計ワークフローを作成してください。

# 調査
- read_file, grep_codebase, file_info, smart_read, get_repo_map で
  対象ファイル・関連コードの現状を確認する
- 必要であれば web_search / fetch_webpage で外部の仕様・ドキュメント・ライブラリの
  使い方などを調べる（書き込みは一切できない）

# 出力（最終回答）
最終回答は、調査結果の説明ではなく、Workerへの指示文としてそのまま使える
「設計ワークフロー」のテキストにすること。Markdownで構わない。最低限、以下を含めること:
- 対象ファイルの絶対パス
- 変更前の現状（関連する既存コードの抜粋・関数シグネチャなど）
- 実装手順（ステップごとに具体的に）
- 追加・変更後のコード例（できるだけ実際に貼り付けられる形で）
- 完了の判定基準（Supervisorが確認できる程度に具体的に）

元の指示の意図から外れた提案や、無関係な追加作業は書かないこと。

# 検証コマンドの提案（任意）
今回の変更スコープに対応するテスト・ビルド・Lint コマンドを特定できた場合は、
最終回答の末尾に以下の形式で1行だけ記載すること（Directorが未指定の場合に自動採用される）:

[推奨verify_cmd] <コマンド>

- 今回の変更スコープに絞った最小限のコマンドにすること（フルスイートは避ける）
- 実行に数分以上かかるものは不適切
- 適切なコマンドが特定できない場合はこのセクションを省略してよい`

var suggestedVerifyCmdRe = regexp.MustCompile(`(?i)\[推奨verify_cmd\]\s*[:` + "`" + `]?\s*(.+?)(?:\n|$)`)
var jsonFenceRe = regexp.MustCompile(`(?s)` + "```json\\s*(\\{.*?\\})\\s*```")

// runIsolated はDirectorの会話履歴・スクラッチパッドを一切共有しないフレッシュな
// 1ターン実行を行う（Python版 team.py::_run_isolated の縮小版）。ゲート・
// ループブレーカー・チェックポイント・AutoGit連携は不要なため internal/react を
// 再利用せず、ここに専用の簡易ループを持つ
// （internal/react は internal/tools に依存しており、internal/delegate も
// internal/tools に依存するため、internal/react を経由すると
// tools→delegate→react→tools の依存循環になってしまうことを避ける構成上の理由もある）。
func runIsolated(ctx context.Context, client *llm.Client, systemPrompt, userMessage string, registry *tools.Registry) (string, error) {
	specs := registry.Specs()
	history := []llm.Message{{Role: "user", Content: userMessage}}
	lastText := ""

	for round := 0; round < isolatedMaxRounds; round++ {
		result, err := client.StreamChat(ctx, systemPrompt, history, specs, func(string) {})
		if err != nil {
			return "", err
		}
		if result.Text != "" {
			lastText = result.Text
		}
		if len(result.ToolCalls) == 0 {
			return result.Text, nil
		}
		history = append(history, llm.Message{Role: "assistant", Content: result.Text, ToolCalls: result.ToolCalls})
		for _, tc := range result.ToolCalls {
			output := registry.Call(tc.Function.Name, tc.Function.Arguments)
			history = append(history, llm.Message{Role: "tool", ToolCallID: tc.ID, Content: output})
		}
	}
	return lastText, nil
}

// extractSuggestedVerifyCmd はResearcher出力から推奨verify_cmdを抽出する
// （Python版 _extract_suggested_verify_cmd の移植。構造化JSONブロック優先、
// 無ければ [推奨verify_cmd] 行を正規表現で抽出する2段構え）。
func extractSuggestedVerifyCmd(research string) string {
	if m := jsonFenceRe.FindStringSubmatch(research); m != nil {
		var data map[string]any
		if err := json.Unmarshal([]byte(m[1]), &data); err == nil {
			if cmd, ok := data["verify_cmd"].(string); ok && strings.TrimSpace(cmd) != "" {
				return strings.TrimSpace(cmd)
			}
		}
	}
	if m := suggestedVerifyCmdRe.FindStringSubmatch(research); m != nil {
		return strings.Trim(strings.TrimSpace(m[1]), "`")
	}
	return ""
}

// RunTeamTask はResearcher→Workerの二段委任を実行する
// （Python版 team.py::run_team_task の縮小移植。書き込みインターロック・
// 委任履歴リングバッファ・中断委任マニフェストは未移植）。
func RunTeamTask(ctx context.Context, client *llm.Client, baseRegistry *tools.Registry, task, projectDir, verifyCmd string) (string, error) {
	researcherRegistry := baseRegistry.Subset(researcherTools)
	research, err := runIsolated(ctx, client, researcherSystemPrompt, task, researcherRegistry)
	if err != nil {
		return "", fmt.Errorf("Researcher調査に失敗しました: %w", err)
	}

	if verifyCmd == "" {
		if suggested := extractSuggestedVerifyCmd(research); suggested != "" {
			verifyCmd = suggested
		}
	}

	workerTask := task
	if research != "" {
		workerTask = task + "\n\n[Researcherによる設計ワークフロー]\n" + research
	}

	result, err := RunWorkerOnce(ctx, workerTask, projectDir, verifyCmd, "", true)
	if err != nil {
		return "", err
	}
	return "[Team] Researcher調査 → " + result, nil
}

// researchQASystemPrompt はPython版 team.py::RESEARCH_QA_SYSTEM_PROMPT の移植。
// delegate_research（調べ物専用の軽量委任）用。設計ワークフローではなく
// 質問への回答だけを簡潔に返す点がresearcherSystemPromptと異なる。
const researchQASystemPrompt = `あなたは調査役（Researcher）です。
Director（指示役）から渡された「調べてほしいこと」について必要な調査を行い、
その結果だけをユーザーへの回答として整理して返してください。

# 調査
- read_file, grep_codebase, file_info, smart_read, get_repo_map で
  プロジェクト内の関連情報を確認できる
- 必要であれば web_search / fetch_webpage で外部の仕様・公式ドキュメント等を調べる
  （書き込みは一切できない）

# 出力（最終回答）
- 「調べてほしいこと」に対する答えだけを、簡潔に日本語で書くこと。
  調査の過程・余談・関係ない情報は書かない。
- Markdownの区切り線（---）を多用しない。見出しは最小限にする。
- 情報源（URL等）があれば末尾に簡潔に添える。`

// RunResearchQA はフレッシュな文脈で調べ物を行い、回答だけを返す
// （Python版 team.py::run_research_qa の移植。Worker/サンドボックスは使わず、
// runIsolatedによるin-process実行のみで完結する）。
func RunResearchQA(ctx context.Context, client *llm.Client, baseRegistry *tools.Registry, question, projectDir string) (string, error) {
	registry := baseRegistry.Subset(researcherTools)
	prompt := fmt.Sprintf("[作業フォルダ] %s\n\n[調べてほしいこと]\n%s\n", projectDir, question)
	return runIsolated(ctx, client, researchQASystemPrompt, prompt, registry)
}
