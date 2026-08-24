package delegate

import (
	"context"

	"mimic/internal/llm"
	"mimic/internal/tools"
)

// RegisterTools はdelegate_to_worker/delegate_to_teamを既存のRegistryへ追加する。
// tools パッケージが internal/delegate に依存しない構成
// （internal/react→internal/tools の依存があるため、tools→delegate→toolsの
// 循環を避けるべく、呼び出し側（cmd/mimic, internal/tui）から明示的に呼ぶ設計）。
func RegisterTools(r *tools.Registry, client *llm.Client) {
	r.Register("delegate_to_worker",
		"タスクをOverlayFS隔離されたWorker（自分自身のバイナリを再帰起動）に委任し、実行結果を実プロジェクトへ適用する。"+
			"Researcher段階は無く、taskは目的・対象範囲・制約条件を具体的に書くこと。verify_cmdを指定すると失敗するたびに同じOverlay上で最大3回まで自動修正再試行する。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"task":        map[string]any{"type": "string", "description": "Workerへの具体的な指示（目的・対象範囲・制約条件を含む）"},
				"project_dir": map[string]any{"type": "string", "description": "作業対象のプロジェクトディレクトリのフルパス（デフォルト: 現在の作業フォルダ）", "default": "."},
				"verify_cmd":  map[string]any{"type": "string", "description": "Worker完了後に実行する検証コマンド（省略可、失敗時は自動修正リトライ）", "default": ""},
			},
			"required": []string{"task"},
		},
		func(args map[string]any) (string, error) {
			return RunWorkerOnce(context.Background(),
				argStr(args, "task"), defaultDir(argStr(args, "project_dir")), argStr(args, "verify_cmd"))
		})

	r.Register("delegate_to_team",
		"Researcher（調査・設計ワークフロー作成）→ Worker（実装）の順に実行し、変更を実プロジェクトへ適用する委任ツール。"+
			"taskは目的・対象範囲・制約条件を書けば十分（詳細調査はResearcherが行う）。"+
			"verify_cmdを省略した場合、Researcherが提案したコマンドが自動採用されることがある。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"task":        map[string]any{"type": "string", "description": "Workerチームへの指示（目的・対象範囲・制約条件を含む）"},
				"project_dir": map[string]any{"type": "string", "description": "作業対象のプロジェクトディレクトリのフルパス（デフォルト: 現在の作業フォルダ）", "default": "."},
				"verify_cmd":  map[string]any{"type": "string", "description": "Worker完了後に実行する検証コマンド（省略可、Researcher提案を自動採用する場合あり）", "default": ""},
			},
			"required": []string{"task"},
		},
		func(args map[string]any) (string, error) {
			return RunTeamTask(context.Background(), client, r,
				argStr(args, "task"), defaultDir(argStr(args, "project_dir")), argStr(args, "verify_cmd"))
		})
}

func argStr(args map[string]any, key string) string {
	if v, ok := args[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}

func defaultDir(d string) string {
	if d == "" {
		return "."
	}
	return d
}
