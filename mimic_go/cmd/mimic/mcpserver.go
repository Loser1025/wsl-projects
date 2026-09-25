package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"mimic/internal/config"
	"mimic/internal/delegate"
	"mimic/internal/llm"
	"mimic/internal/mcpserver"
	"mimic/internal/tools"
	"mimic/internal/vcs"
)

// exposedDelegateTools はMCP経由でClaude Code等に公開するツール名の一覧。
// mimic自身が使うread_file/run_bash等の低レベルツールはClaude Code側に既に
// 同等以上のものがあるため公開しない——MCPのtools/listはどのクライアントでも
// 接続のたびにコンテキストを消費するので、公開範囲を絞ること自体が
// 「Claude Codeのコンテキスト節約」という目的に直接効く。
var exposedDelegateTools = []string{
	"delegate_to_worker",
	"delegate_to_team",
	"delegate_to_team_parallel",
	"delegate_research",
	"delegate_to_specialist",
	"continue_specialist",
	"get_delegation_trace",
}

// asyncCapableTools はdelegate_asyncのtool引数として許可するツール名。
// get_delegation_traceは元々即座に返るため非同期化の対象外。
var asyncCapableTools = []string{
	"delegate_to_worker",
	"delegate_to_team",
	"delegate_to_team_parallel",
	"delegate_research",
	"delegate_to_specialist",
	"continue_specialist",
}

// runMCPServer はmimicの委任ツール群(delegate_to_worker/delegate_to_specialist/
// get_delegation_trace等)をMCPサーバーとして標準入出力越しに公開する。
// Claude Code等のMCPクライアントから`.mcp.json`経由で接続される想定。
// レジストリ構築はcmd/mimic/noninteractive.go::runNonInteractiveと同じ手順を
// 踏襲するが、react.RunTurnによる会話ループは持たず、ツール呼び出しの中継に徹する。
func runMCPServer(cfg *config.Config, envPath string) {
	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}
	absEnvPath, absErr := filepath.Abs(envPath)
	if absErr != nil {
		absEnvPath = envPath
	}

	client := llm.NewClient(cfg.Active)
	delegate.SetLaunchContext(absEnvPath, cfg.Active.Name, cfg.Active.Model)

	// 内部実行用にはフルレジストリを使う（delegate_to_team等が使うResearcher役は
	// web_search等の一般ツールにもアクセスする必要があるため）。
	// 外部（MCPクライアント）へ公開する分だけexposedDelegateToolsで絞る
	// （下部のmcpRegistry参照）。
	registry := tools.NewDefaultRegistry()
	delegate.RegisterTools(registry, client)
	// 外部MCPサーバーへの接続(mcp.ConnectAll)はここでは行わない。
	// delegate_to_worker等が起動するWorkerサブプロセスは自分自身の
	// runNonInteractive経由で独立に外部MCPサーバーへ接続するため
	// （cmd/mimic/noninteractive.go）、この長命なMCPサーバープロセス自身が
	// 接続しても誰にも使われず、無駄な常駐接続になるだけだった。

	sessionsDir := filepath.Join(cwd, ".mimic", "sessions")
	delegate.SetSessionsDir(sessionsDir)
	tools.SetSessionsDirForTool(sessionsDir)

	// Directorの他起動経路（TUI/-prompt/-auto-prompt）と同じくAutoGitを配線する。
	// これが無いと委任結果がsandbox.ApplyChangesで実プロジェクトへ反映されても
	// git上のチェックポイント（ロールバック用の安全網）が一切残らない
	// （Checkpoint()はBackup()を呼ばなくても単独で機能するため、MCPサーバーの
	// 「ターン」概念が無い1コールずつの呼び出しモデルにもそのまま馴染む）。
	autoGit := vcs.New()
	delegate.SetTeamAutoGit(autoGit)
	delegate.WarnOrphanedDelegations()

	// 承認ハンドラ類(tools.SetWriteApprovalHandler等)は意図的に登録しない。
	// MCPサーバーはstdioをJSON-RPC専用に使っており対話的承認UIを持てないため。
	// 安全性はサンドボックス(OverlayFS)+verify_cmd機械検証+上記AutoGitに委ねる
	// （-auto-promptのWorkerと同じ既定挙動）。

	mimicBin, err := os.Executable()
	if err != nil {
		mimicBin = "mimic"
	}
	delegate.SetOnDelegationStart(func(traceID, projectDir, _ string) {
		launchWatchTerminal(mimicBin, traceID, projectDir)
	})

	// MCPクライアントへはexposedDelegateToolsだけを公開する。
	// delegate_async/get_delegation_resultはこの公開用レジストリにだけ追加し、
	// 内部用のフルregistryには影響させない。
	mcpRegistry := registry.Subset(exposedDelegateTools)
	registerAsyncTools(mcpRegistry, registry, mcpserver.NewJobRegistry())

	fmt.Fprintf(os.Stderr, "[mimic-mcp-server] provider=%s model=%s cwd=%s\n", client.ProviderName(), client.Model(), cwd)
	if err := mcpserver.Serve(mcpRegistry, os.Stdin, os.Stdout); err != nil {
		fmt.Fprintf(os.Stderr, "[mimic-mcp-server] エラー: %v\n", err)
		os.Exit(1)
	}
}

// registerAsyncTools はexposed(MCP公開用レジストリ)へdelegate_async/
// get_delegation_resultを追加する。delegate_asyncはfull(内部用フルレジストリ)の
// ツールをjobsで非同期実行し、即座にjob_idを返す
// （delegate_to_worker等が1回のtools/callで数分〜数十分ブロックし、
// internal/delegate/worker.goのMaxDelegationConcurrency=3による並列実行の
// 恩恵を「投げて待つだけ」の同期呼び出しでは活かせない問題への対策）。
func registerAsyncTools(exposed, full *tools.Registry, jobs *mcpserver.JobRegistry) {
	allowed := make(map[string]bool, len(asyncCapableTools))
	for _, n := range asyncCapableTools {
		allowed[n] = true
	}

	exposed.Register("delegate_async",
		"delegate_to_worker等の重い委任ツールをバックグラウンドで開始し、即座にjob_idを返す。"+
			"呼び出し元はブロックされない。結果はget_delegation_resultで後から取得すること。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"tool":      map[string]any{"type": "string", "enum": asyncCapableTools, "description": "非同期実行したい委任ツール名"},
				"arguments": map[string]any{"type": "object", "description": "そのツールへ渡す引数（同期版のdelegate_to_worker等と同じ形）"},
			},
			"required": []string{"tool", "arguments"},
		},
		func(args map[string]any) (string, error) {
			toolName, _ := args["tool"].(string)
			if !allowed[toolName] {
				return fmt.Sprintf("エラー: delegate_asyncで指定できないツールです: %s", toolName), nil
			}
			arguments, _ := args["arguments"].(map[string]any)
			argsJSON, err := json.Marshal(arguments)
			if err != nil {
				argsJSON = []byte("{}")
			}
			jobID := jobs.Start(full, toolName, string(argsJSON))
			return fmt.Sprintf("job_id=%s を開始しました。get_delegation_result(job_id=\"%s\")で状態を確認してください。", jobID, jobID), nil
		})

	exposed.Register("get_delegation_result",
		"delegate_asyncで開始したジョブの状態・結果を取得する。まだ完了していなければstatus=runningを返す。",
		map[string]any{
			"type":       "object",
			"properties": map[string]any{"job_id": map[string]any{"type": "string", "description": "delegate_asyncが返したjob_id"}},
			"required":   []string{"job_id"},
		},
		func(args map[string]any) (string, error) {
			jobID, _ := args["job_id"].(string)
			done, result, found := jobs.Result(jobID)
			if !found {
				return fmt.Sprintf("エラー: job_id '%s' が見つかりません。", jobID), nil
			}
			if !done {
				return "status=running（まだ完了していません。しばらくしてから再度確認してください）", nil
			}
			return result, nil
		})
}

// launchWatchTerminal は委任開始時にWindows Terminalの新タブで
// `mimic watch <trace_id> <project_dir>` を起動し、実況をライブ表示させる
// （非同期・fire-and-forget。失敗しても委任自体は継続する——監視は付加機能のため）。
// wt.exeが無い環境（純粋なLinux等）では警告を出すだけに留める。
func launchWatchTerminal(mimicBin, traceID, projectDir string) {
	if _, err := exec.LookPath("wt.exe"); err != nil {
		fmt.Fprintln(os.Stderr, "[mimic-mcp-server] wt.exeが見つからないため監視ターミナルは開けません（委任は継続します）")
		return
	}
	args := []string{"new-tab", "wsl.exe"}
	if distro := os.Getenv("WSL_DISTRO_NAME"); distro != "" {
		args = append(args, "-d", distro)
	}
	args = append(args, "--", mimicBin, "watch", traceID, projectDir)
	if err := exec.Command("wt.exe", args...).Start(); err != nil {
		fmt.Fprintf(os.Stderr, "[mimic-mcp-server] 監視ターミナルの起動に失敗しました: %v\n", err)
	}
}
