package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"mimic/internal/delegate"
	"mimic/internal/llm"
	"mimic/internal/mcp"
	"mimic/internal/react"
	"mimic/internal/tools"
	"mimic/internal/vcs"
)

// finalMarker はauto-promptモードの出力に付与するマーカー行
// （Python版 orchestrator.py::_FINAL_MARKER = "===MIMIC_FINAL===" を踏襲）。
// 親プロセス（将来のWorker起動元）が標準出力から最終回答を切り出す際の目印。
const finalMarker = "===MIMIC_FINAL==="

// runNonInteractive は --prompt / --auto-prompt 共通の非対話1ターン実行。
// TUIを起動せず、結果を標準出力に書いて終了する
// （Python版 main.py::pipe_mode / auto_mode の移植。実行内容自体は同じで、
// auto版のみ完了マーカーを付与する点だけが異なる）。
//
// MIMIC_NO_AUTOGIT環境変数が設定されている場合はWorkerとして起動されたとみなし、
// AutoGitのbackup/checkpoint/squashを行わない（Python版 NullAutoGit 相当。
// サンドボックスのupperdirに.gitの変更が混入し差分サマリが汚染されるのを防ぐ）。
// MIMIC_CWD等の他のWorker連携用環境変数は現時点では未対応。
func runNonInteractive(client *llm.Client, systemPrompt, prompt string, auto bool) {
	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}

	registry := tools.NewDefaultRegistry()
	isWorker := os.Getenv("MIMIC_NO_AUTOGIT") != ""
	if !isWorker {
		// Worker（孫Workerの無限増殖防止のため）には委任ツールを与えない
		// （Python版 __main__.py の _DELEGATE_TOOLS 除外ロジックを踏襲）。
		delegate.RegisterTools(registry, client)
	}
	// Workerには承認ハンドラーが無いため「承認必須」がノーガードになる。
	// 接続時のフィルタリング（read-only信頼済みサーバーのみ）だけが安全境界になる
	// （Python版 connect_all(readonly_only=...) の方針を踏襲）。
	mcp.ConnectAll(registry, cwd, isWorker)
	var autoGit *vcs.AutoGit
	if !isWorker {
		autoGit = vcs.New()
	}
	reactLog := vcs.NewReactLog()
	sessionsDir := filepath.Join(cwd, ".mimic", "sessions")
	jsonlPath := filepath.Join(sessionsDir, "auto-"+fmt.Sprint(os.Getpid())+".jsonl")
	if err := reactLog.SetJSONLPath(jsonlPath); err == nil {
		vcs.PruneOldSessions(sessionsDir, 200)
	}
	reactLog.Add("session_start", map[string]any{"model": client.Model(), "provider": client.ProviderName()})

	// delegate_to_specialist経由で起動されたWorkerには、Directorが指定した
	// ロール説明がMIMIC_ROLE_PROMPT環境変数で渡される（Python版と同じ仕組み）。
	if rolePrompt := os.Getenv("MIMIC_ROLE_PROMPT"); rolePrompt != "" {
		systemPrompt = rolePrompt + "\n\n" + systemPrompt
	}

	// continue_specialist経由の再起動時はMIMIC_KEEP_CHECKPOINTが立っており、
	// このWorker専用チェックポイント（サンドボックス内なのでDirector側とは無関係）に
	// 既存の会話履歴があれば読み込んで続きの指示として追記する
	// （Python版 run_specialist_continue のresume_note注入に相当）。
	const workerCheckpointPath = ".mimic/checkpoint.json"
	keepCheckpoint := os.Getenv("MIMIC_KEEP_CHECKPOINT") != ""
	checkpointPath := ""
	var history []llm.Message
	if keepCheckpoint {
		checkpointPath = workerCheckpointPath
		if loaded, err := react.LoadCheckpoint(checkpointPath); err == nil && len(loaded) > 0 {
			history = loaded
		}
	}
	history = append(history, llm.Message{Role: "user", Content: prompt})

	result, err := react.RunTurn(context.Background(), client, systemPrompt, registry, &history,
		func(string) {}, nil, checkpointPath, autoGit, cwd, reactLog, vcs.NewToolCallLog(), keepCheckpoint)

	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
		os.Exit(1)
	}

	if auto {
		fmt.Println(finalMarker)
	}
	fmt.Println(result)
	os.Exit(0)
}

// runStatusMode は現在の設定（プロバイダ/モデル/キー数）を表示して終了する
// （Python版 __main__.py の --status 処理を踏襲）。
func runStatusMode(provider, model string, numKeys int) {
	fmt.Printf("  プロバイダー: %s\n", provider)
	fmt.Printf("  モデル: %s\n", model)
	fmt.Printf("  APIキー: %d 個\n", numKeys)
	os.Exit(0)
}
