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
				argStr(args, "task"), defaultDir(argStr(args, "project_dir")), argStr(args, "verify_cmd"), "", true)
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

	r.Register("delegate_research",
		"外部の公式ドキュメント・仕様などを調べる「調べ物」を、フレッシュな文脈の調査役（Researcher）に委任し、調査結果（回答）だけを受け取る。"+
			"複数回のweb_search/fetch_webpageが必要になりそうな調べ物は、自分（Director）で直接行わず必ずこれを使うこと。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"question":    map[string]any{"type": "string", "description": "調べてほしいこと（ユーザーの質問の意図が伝わるように具体的に書く）"},
				"project_dir": map[string]any{"type": "string", "description": "作業対象のプロジェクトディレクトリのフルパス（デフォルト: 現在の作業フォルダ）", "default": "."},
			},
			"required": []string{"question"},
		},
		func(args map[string]any) (string, error) {
			return RunResearchQA(context.Background(), client, r,
				argStr(args, "question"), defaultDir(argStr(args, "project_dir")))
		})

	r.Register("delegate_to_specialist",
		"指定したロール説明を持つ専門家エージェントにタスクを委任する。ロールはDirectorが自由に定義できる。"+
			"権限は3段階: デフォルト（読み取り専用）、can_execute=True（コマンド実行可・変更は破棄）、can_write=True（実装・適用）。"+
			"roleには「視点」「制約」「完了基準」を必ず含めること（「完了基準」の明記がないと機械チェックで差し戻される）。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"role":        map[string]any{"type": "string", "description": "専門家ロールの説明。「視点」「制約」「完了基準」の3要素を必ず含めること"},
				"task":        map[string]any{"type": "string", "description": "そのロールに実行させるタスク"},
				"can_write":   map[string]any{"type": "boolean", "description": "Trueでファイル変更可能（OverlayFS隔離、変更は適用される）、False（デフォルト）で読み取り専用", "default": false},
				"can_execute": map[string]any{"type": "boolean", "description": "Trueで実行専用（コマンド実行可だが変更は破棄）。can_write=Trueが優先される", "default": false},
				"project_dir": map[string]any{"type": "string", "description": "作業ディレクトリ（デフォルト: カレント）", "default": "."},
				"verify_cmd":  map[string]any{"type": "string", "description": "can_write/can_execute時、実行後に評価する検証コマンド（省略可）", "default": ""},
			},
			"required": []string{"role", "task"},
		},
		func(args map[string]any) (string, error) {
			role := argStr(args, "role")
			if roleErr := validateSpecialistRole(role); roleErr != "" {
				return roleErr, nil
			}
			return RunSpecialistTask(context.Background(), client, r,
				role, argStr(args, "task"), defaultDir(argStr(args, "project_dir")), argStr(args, "verify_cmd"),
				argBool(args, "can_write"), argBool(args, "can_execute"))
		})

	r.Register("continue_specialist",
		"delegate_to_specialist(can_write=true)で保持されたセッションWorkerに追加指示を出し、前回の会話・作業内容の続きから実行する。"+
			"新しいDirectorとのやり取りを踏まえて同じロールのWorkerに作業を継続させたい場合に使う。保持中のセッションが無い場合はエラーを返す。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"task":       map[string]any{"type": "string", "description": "追加で実行させたい指示"},
				"verify_cmd": map[string]any{"type": "string", "description": "検証コマンド（省略時は前回のverify_cmdを引き継ぐ）", "default": ""},
			},
			"required": []string{"task"},
		},
		func(args map[string]any) (string, error) {
			return RunSpecialistContinue(context.Background(), argStr(args, "task"), argStr(args, "verify_cmd"))
		})
}

func argBool(args map[string]any, key string) bool {
	if v, ok := args[key]; ok {
		if b, ok := v.(bool); ok {
			return b
		}
	}
	return false
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
