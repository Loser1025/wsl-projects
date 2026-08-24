package delegate

import (
	"context"
	"fmt"
	"strings"

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

	r.Register("delegate_to_team_parallel",
		"互いに依存しない複数のタスクを、それぞれdelegate_to_teamと同じResearcher→Workerパイプラインで並列実行する。"+
			"tasksは必ず文字列の配列で渡すこと（1つの文字列に区切り文字で連結してはならない）。要素数は最大10件まで。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"tasks":       map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "Workerチームに与えるタスク一覧（各要素が独立した自己完結タスクであること、最大10件）"},
				"project_dir": map[string]any{"type": "string", "description": "作業対象のプロジェクトディレクトリのフルパス（デフォルト: 現在の作業フォルダ）", "default": "."},
				"verify_cmd":  map[string]any{"type": "string", "description": "各タスクのWorker完了後に実行する検証コマンド（全タスク共通、省略可）", "default": ""},
			},
			"required": []string{"tasks"},
		},
		func(args map[string]any) (string, error) {
			tasks, err := argStrArray(args, "tasks")
			if err != nil {
				return "", err
			}
			if len(tasks) == 0 {
				return "エラー: tasksが空です。", nil
			}
			if len(tasks) > maxParallelTasks {
				return fmt.Sprintf("エラー: tasksが%d件あります。1回の呼び出しは%d件以下に分割してください。", len(tasks), maxParallelTasks), nil
			}
			results := RunTeamTasksParallel(context.Background(), client, r,
				tasks, defaultDir(argStr(args, "project_dir")), argStr(args, "verify_cmd"))
			var blocks []string
			for i, res := range results {
				blocks = append(blocks, fmt.Sprintf("── チーム %d/%d ──\n%s", i+1, len(results), res))
			}
			return fmt.Sprintf("[delegate_to_team_parallel: %d件完了]\n\n%s", len(results), strings.Join(blocks, "\n\n")), nil
		})
}

// argStrArray はJSON配列引数([]any として来る)を[]stringへ変換する。
// 文字列1つがそのまま渡された場合はエラーにする
// （Python版の「1文字ごとにWorkerが起動してしまう」事故防止チェックを踏襲）。
func argStrArray(args map[string]any, key string) ([]string, error) {
	v, ok := args[key]
	if !ok {
		return nil, nil
	}
	if _, isStr := v.(string); isStr {
		return nil, fmt.Errorf("tasksは文字列ではなく、文字列の配列（list[str]）で渡してください。例: [\"タスク1の説明\", \"タスク2の説明\"]")
	}
	arr, ok := v.([]any)
	if !ok {
		return nil, fmt.Errorf("tasksの形式が不正です")
	}
	out := make([]string, 0, len(arr))
	for _, item := range arr {
		if s, ok := item.(string); ok {
			out = append(out, s)
		}
	}
	return out, nil
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
