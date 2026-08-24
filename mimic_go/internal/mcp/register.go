package mcp

import (
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
	serversMu sync.Mutex
	servers   = make(map[string]server)
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
		n := registerToolsFor(r, name, toolMap)
		results = append(results, ConnectResult{name, true, fmt.Sprintf("%d件のツールを登録", n)})
	}
	return results
}

func registerToolsFor(r *tools.Registry, serverName string, toolMap map[string]ToolInfo) int {
	n := 0
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
			serversMu.Lock()
			s := servers[serverName]
			serversMu.Unlock()
			if s == nil {
				return fmt.Sprintf("エラー: MCPサーバー '%s' は接続されていません。", serverName), nil
			}
			return s.CallTool(toolNameCapture, args), nil
		})
		n++
	}
	return n
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
