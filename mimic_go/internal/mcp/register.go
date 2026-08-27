package mcp

import (
	"encoding/json"
	"fmt"
	"sync"

	"mimic/internal/tools"
)

// server はstdio(ServerProcess)/HTTP(HTTPServerProcess)共通のインターフェース。
type server interface {
	CallTool(toolName string, arguments map[string]any) string
	Stop()
	ToolCount() int
}

func (s *ServerProcess) ToolCount() int     { return len(s.Tools) }
func (s *HTTPServerProcess) ToolCount() int { return len(s.Tools) }

var (
	serversMu   sync.Mutex
	servers     = make(map[string]server)
	serverTools = make(map[string][]string) // serverName -> 登録済みツールのフルネーム一覧（reconnect用）
)

// ConnectResult は1サーバーへの接続試行結果。
type ConnectResult struct {
	Name    string
	OK      bool
	Message string
}

// ConnectAll は設定済みMCPサーバーに接続し、ツールを mcp__<server>__<tool> の
// 名前でRegistryへ動的登録する（Python版 connect_all の移植。"command"指定は
// stdio(ServerProcess)、"url"指定はStreamable HTTP(HTTPServerProcess)で接続する）。
//
// readonlyOnly=trueの場合、.mimic/mcp_policy.jsonでtrust="read-only"と明示
// されたサーバーだけを対象にする（Worker向け。Workerには承認ハンドラーが
// 無いため、接続時のフィルタリングだけが安全境界になる — Python版と同じ方針）。
func ConnectAll(r *tools.Registry, projectDir string, readonlyOnly bool) []ConnectResult {
	configs := LoadServerConfigs(projectDir)
	var policy map[string]policyEntry
	if readonlyOnly {
		policy = loadPolicy(projectDir)
	}

	var results []ConnectResult
	for name, spec := range configs {
		if readonlyOnly && policy[name].Trust != "read-only" {
			continue
		}

		var s server
		var toolMap map[string]ToolInfo
		if spec.URL != "" {
			proc := NewHTTPServerProcess(name, spec.URL, spec.Env)
			if !proc.Start() {
				results = append(results, ConnectResult{name, false, proc.FailedReason()})
				continue
			}
			s, toolMap = proc, proc.Tools
		} else {
			proc := NewServerProcess(name, spec.Command, spec.Args, spec.Env)
			if !proc.Start() {
				results = append(results, ConnectResult{name, false, proc.FailedReason()})
				continue
			}
			s, toolMap = proc, proc.Tools
		}

		serversMu.Lock()
		servers[name] = s
		serversMu.Unlock()
		n := registerToolsFor(r, name, toolMap, projectDir)
		results = append(results, ConnectResult{name, true, fmt.Sprintf("%d件のツールを登録", n)})
	}
	return results
}

func registerToolsFor(r *tools.Registry, serverName string, toolMap map[string]ToolInfo, projectDir string) int {
	n := 0
	var registered []string
	for toolName, spec := range toolMap {
		fullName := fmt.Sprintf("mcp__%s__%s", serverName, toolName)
		params := spec.InputSchema
		if params == nil {
			params = map[string]any{"type": "object", "properties": map[string]any{}}
		}
		desc := fmt.Sprintf("[MCP:%s] %s", serverName, spec.Description)
		if len(desc) > 800 {
			desc = desc[:800]
		}
		toolNameCapture := toolName
		r.Register(fullName, desc, params, func(args map[string]any) (string, error) {
			// MCPサーバーの readOnlyHint 自己申告は信用せず、.mimic/mcp_policy.json で
			// trust="read-only" と明示された場合のみ承認を省略する（Python版
			// mcp_client.py::_make_tool_fn と同じ方針。/mcp trust による変更を
			// 即座に反映できるよう呼び出しごとにポリシーを読み直す）。
			trusted := loadPolicy(projectDir)[serverName].Trust == "read-only"
			if !trusted {
				argsJSON, _ := json.Marshal(args)
				preview := fmt.Sprintf("MCPツール呼び出し: %s/%s\n引数: %s", serverName, toolNameCapture, truncateForPreview(string(argsJSON), 500))
				if rejectErr := tools.RequestMCPApproval(fullName, preview); rejectErr != "" {
					return rejectErr, nil
				}
			}

			serversMu.Lock()
			s := servers[serverName]
			serversMu.Unlock()
			if s == nil {
				return fmt.Sprintf("エラー: MCPサーバー '%s' は接続されていません。", serverName), nil
			}
			return s.CallTool(toolNameCapture, args), nil
		})
		registered = append(registered, fullName)
		n++
	}
	serversMu.Lock()
	serverTools[serverName] = registered
	serversMu.Unlock()
	return n
}

// Reconnect は指定サーバーを一度切断してから再接続し直す（Python版
// commands.py::cmd_mcp の "/mcp reconnect <server>" の移植）。projectDirの
// .mcp.json設定を再読み込みするため、設定変更後の再接続にも使える。
func Reconnect(r *tools.Registry, projectDir, name string) ConnectResult {
	serversMu.Lock()
	if s, ok := servers[name]; ok {
		s.Stop()
		delete(servers, name)
	}
	oldTools := serverTools[name]
	delete(serverTools, name)
	serversMu.Unlock()
	for _, toolName := range oldTools {
		r.Unregister(toolName)
	}

	configs := LoadServerConfigs(projectDir)
	spec, ok := configs[name]
	if !ok {
		return ConnectResult{name, false, fmt.Sprintf("設定に見つかりません（.mcp.jsonに'%s'が定義されていません）", name)}
	}

	var s server
	var toolMap map[string]ToolInfo
	if spec.URL != "" {
		proc := NewHTTPServerProcess(name, spec.URL, spec.Env)
		if !proc.Start() {
			return ConnectResult{name, false, proc.FailedReason()}
		}
		s, toolMap = proc, proc.Tools
	} else {
		proc := NewServerProcess(name, spec.Command, spec.Args, spec.Env)
		if !proc.Start() {
			return ConnectResult{name, false, proc.FailedReason()}
		}
		s, toolMap = proc, proc.Tools
	}

	serversMu.Lock()
	servers[name] = s
	serversMu.Unlock()
	n := registerToolsFor(r, name, toolMap, projectDir)
	return ConnectResult{name, true, fmt.Sprintf("%d件のツールを再登録", n)}
}

func truncateForPreview(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max]
}

// ShutdownAll は接続中の全MCPサーバーとの通信を終了する（プロセス終了時用）。
func ShutdownAll() {
	serversMu.Lock()
	defer serversMu.Unlock()
	for _, s := range servers {
		s.Stop()
	}
	servers = make(map[string]server)
}

// ListStatus は接続中サーバーの状態一覧を返す（/mcp コマンド等での利用を想定）。
func ListStatus() []string {
	serversMu.Lock()
	defer serversMu.Unlock()
	var out []string
	for name, s := range servers {
		out = append(out, fmt.Sprintf("%s: %d件のツール", name, s.ToolCount()))
	}
	return out
}
