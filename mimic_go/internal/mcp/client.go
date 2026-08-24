// Package mcp はMCP(Model Context Protocol)サーバーとの通信を実装する
// （Python版 mcp_client.py の縮小移植）。
//
// このバッチではstdioトランスポート（subprocess + JSON-RPC, newline-delimited
// JSON）のみを対象とし、Streamable HTTP（url指定のリモートサーバー）は
// 対象外とする（次のステップ候補）。
//
// 書き込み承認フック（Python版は全MCPツール呼び出しをデフォルトで
// _request_write_approval経由にする）もGo版には承認UI自体が無いため未実装
// （write_file等の既存の書き込みツールと同じギャップ）。
package mcp

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

const (
	protocolVersion = "2024-11-05"
	initTimeout     = 10 * time.Second
	callTimeout     = 60 * time.Second
)

// ToolInfo はMCPサーバーが tools/list で返す1ツールの定義。
type ToolInfo struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"inputSchema"`
}

type rpcRequest struct {
	JSONRPC string `json:"jsonrpc"`
	ID      int    `json:"id,omitempty"`
	Method  string `json:"method"`
	Params  any    `json:"params,omitempty"`
}

type rpcResponse struct {
	ID     json.Number     `json:"id"`
	Result json.RawMessage `json:"result"`
	Error  json.RawMessage `json:"error"`
}

// ServerProcess は1台のMCPサーバー(subprocess)とのJSON-RPC通信を担う。
// 呼び出しはサーバー単位で直列化する（Python版 McpServerProcess の移植）。
type ServerProcess struct {
	Name  string
	Tools map[string]ToolInfo

	command string
	args    []string
	env     map[string]string

	mu           sync.Mutex
	cmd          *exec.Cmd
	stdin        io.WriteCloser
	stdout       *bufio.Reader
	started      bool
	failedReason string
	nextID       int
}

func NewServerProcess(name, command string, args []string, env map[string]string) *ServerProcess {
	return &ServerProcess{Name: name, command: command, args: args, env: env, Tools: make(map[string]ToolInfo)}
}

func (s *ServerProcess) FailedReason() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.failedReason
}

// Start は初回ツール呼び出し時（またはconnect時）に起動する。二重起動しない。
func (s *ServerProcess) Start() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.startLocked()
}

func (s *ServerProcess) startLocked() bool {
	if s.cmd != nil && s.cmd.ProcessState == nil {
		return true // 既に起動済み
	}

	cmd := exec.Command(s.command, s.args...)
	cmd.Env = os.Environ()
	for k, v := range s.env {
		cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%s", k, os.ExpandEnv(v)))
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		s.failedReason = fmt.Sprintf("起動失敗: %v", err)
		return false
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		s.failedReason = fmt.Sprintf("起動失敗: %v", err)
		return false
	}
	cmd.Stderr = nil // Python版同様 devnull 相当（破棄）

	if err := cmd.Start(); err != nil {
		s.failedReason = fmt.Sprintf("起動失敗: %v", err)
		return false
	}

	s.cmd = cmd
	s.stdin = stdin
	s.stdout = bufio.NewReader(stdout)

	if err := s.handshakeLocked(); err != nil {
		s.failedReason = fmt.Sprintf("ハンドシェイク失敗: %v", err)
		s.stopLocked()
		return false
	}
	s.started = true
	s.failedReason = ""
	return true
}

func (s *ServerProcess) nextIDLocked() int {
	s.nextID++
	return s.nextID
}

func (s *ServerProcess) sendLocked(msg rpcRequest) error {
	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	_, err = s.stdin.Write(append(data, '\n'))
	return err
}

func (s *ServerProcess) recvLocked(expectID int, timeout time.Duration) (rpcResponse, error) {
	deadline := time.Now().Add(timeout)
	type lineResult struct {
		line string
		err  error
	}
	lineCh := make(chan lineResult, 1)

	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return rpcResponse{}, fmt.Errorf("応答タイムアウト")
		}
		go func() {
			line, err := s.stdout.ReadString('\n')
			lineCh <- lineResult{line, err}
		}()
		select {
		case res := <-lineCh:
			if res.err != nil {
				return rpcResponse{}, fmt.Errorf("サーバーが接続を切断しました: %w", res.err)
			}
			line := strings.TrimSpace(res.line)
			if line == "" {
				continue
			}
			var resp rpcResponse
			if err := json.Unmarshal([]byte(line), &resp); err != nil {
				continue // 壊れた行は無視して次を待つ
			}
			if idNum, err := resp.ID.Int64(); err == nil && int(idNum) == expectID {
				return resp, nil
			}
			// idが一致しない通知等は無視して読み続ける
		case <-time.After(remaining):
			return rpcResponse{}, fmt.Errorf("応答タイムアウト")
		}
	}
}

func (s *ServerProcess) handshakeLocked() error {
	initID := s.nextIDLocked()
	if err := s.sendLocked(rpcRequest{
		JSONRPC: "2.0", ID: initID, Method: "initialize",
		Params: map[string]any{
			"protocolVersion": protocolVersion,
			"capabilities":    map[string]any{},
			"clientInfo":      map[string]any{"name": "mimic-go", "version": "0.1"},
		},
	}); err != nil {
		return err
	}
	resp, err := s.recvLocked(initID, initTimeout)
	if err != nil {
		return err
	}
	if len(resp.Error) > 0 {
		return fmt.Errorf("%s", string(resp.Error))
	}

	if err := s.sendLocked(rpcRequest{JSONRPC: "2.0", Method: "notifications/initialized", Params: map[string]any{}}); err != nil {
		return err
	}

	listID := s.nextIDLocked()
	if err := s.sendLocked(rpcRequest{JSONRPC: "2.0", ID: listID, Method: "tools/list", Params: map[string]any{}}); err != nil {
		return err
	}
	resp, err = s.recvLocked(listID, initTimeout)
	if err != nil {
		return err
	}
	if len(resp.Error) > 0 {
		return fmt.Errorf("%s", string(resp.Error))
	}
	var result struct {
		Tools []ToolInfo `json:"tools"`
	}
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		return err
	}
	for _, t := range result.Tools {
		if t.Name != "" {
			s.Tools[t.Name] = t
		}
	}
	return nil
}

// CallTool はツールを呼び出し、テキスト結果を返す（Python版 call_tool の移植）。
func (s *ServerProcess) CallTool(toolName string, arguments map[string]any) string {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.cmd == nil || s.cmd.ProcessState != nil {
		s.started = false
	}
	if !s.started {
		if !s.startLocked() {
			return fmt.Sprintf("エラー: MCPサーバー '%s' に接続できません (%s)", s.Name, s.failedReason)
		}
	}

	reqID := s.nextIDLocked()
	if err := s.sendLocked(rpcRequest{
		JSONRPC: "2.0", ID: reqID, Method: "tools/call",
		Params: map[string]any{"name": toolName, "arguments": arguments},
	}); err != nil {
		s.stopLocked()
		return fmt.Sprintf("エラー: MCPツール呼び出し失敗 (%v)。次回呼び出し時に再接続を試みます。", err)
	}
	resp, err := s.recvLocked(reqID, callTimeout)
	if err != nil {
		s.stopLocked()
		return fmt.Sprintf("エラー: MCPツール呼び出し失敗 (%v)。次回呼び出し時に再接続を試みます。", err)
	}
	if len(resp.Error) > 0 {
		return fmt.Sprintf("エラー: %s", string(resp.Error))
	}

	var result struct {
		Content []map[string]any `json:"content"`
		IsError bool             `json:"isError"`
	}
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		return string(resp.Result)
	}
	var texts []string
	for _, block := range result.Content {
		if t, _ := block["type"].(string); t == "text" {
			if txt, ok := block["text"].(string); ok {
				texts = append(texts, txt)
				continue
			}
		}
		b, _ := json.Marshal(block)
		texts = append(texts, string(b))
	}
	text := strings.Join(texts, "\n")
	if text == "" {
		text = string(resp.Result)
	}
	if result.IsError {
		return fmt.Sprintf("[MCPツールエラー: %s/%s] %s", s.Name, toolName, text)
	}
	return text
}

func (s *ServerProcess) stopLocked() {
	if s.cmd != nil {
		if s.stdin != nil {
			s.stdin.Close()
		}
		if s.cmd.Process != nil {
			done := make(chan error, 1)
			go func() { done <- s.cmd.Wait() }()
			select {
			case <-done:
			case <-time.After(3 * time.Second):
				s.cmd.Process.Kill()
				<-done
			}
		}
	}
	s.cmd = nil
	s.started = false
}

func (s *ServerProcess) Stop() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stopLocked()
}
