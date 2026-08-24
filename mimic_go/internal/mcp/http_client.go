package mcp

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

// HTTPServerProcess はリモートMCPサーバー（Streamable HTTP transport）との
// 通信を担う（Python版 McpHttpServerProcess の移植）。subprocessは持たず、
// initializeで得た Mcp-Session-Id をヘッダーに付けてPOSTし続ける。
// SSEレスポンスは "data: " 行だけを素朴にパースする最小実装とする。
type HTTPServerProcess struct {
	Name  string
	Tools map[string]ToolInfo

	url     string
	headers map[string]string

	mu           sync.Mutex
	client       *http.Client
	sessionID    string
	started      bool
	failedReason string
	nextID       int
}

func NewHTTPServerProcess(name, url string, headers map[string]string) *HTTPServerProcess {
	return &HTTPServerProcess{
		Name: name, Tools: make(map[string]ToolInfo),
		url: url, headers: headers,
		client: &http.Client{},
	}
}

func (s *HTTPServerProcess) FailedReason() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.failedReason
}

func (s *HTTPServerProcess) nextIDLocked() int {
	s.nextID++
	return s.nextID
}

func (s *HTTPServerProcess) postLocked(msg map[string]any, timeout time.Duration) (rpcResponse, error) {
	body, err := json.Marshal(msg)
	if err != nil {
		return rpcResponse{}, err
	}
	req, err := http.NewRequest(http.MethodPost, s.url, bytes.NewReader(body))
	if err != nil {
		return rpcResponse{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	for k, v := range s.headers {
		req.Header.Set(k, os.ExpandEnv(v))
	}
	if s.sessionID != "" {
		req.Header.Set("Mcp-Session-Id", s.sessionID)
	}

	s.client.Timeout = timeout
	resp, err := s.client.Do(req)
	if err != nil {
		return rpcResponse{}, fmt.Errorf("接続エラー: %w", err)
	}
	defer resp.Body.Close()

	if sid := resp.Header.Get("Mcp-Session-Id"); sid != "" {
		s.sessionID = sid
	}
	contentType := resp.Header.Get("Content-Type")
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return rpcResponse{}, err
	}
	if resp.StatusCode >= 400 {
		return rpcResponse{}, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}

	if strings.Contains(contentType, "text/event-stream") {
		return parseSSEResponse(raw, msg["id"])
	}
	var result rpcResponse
	if err := json.Unmarshal(raw, &result); err != nil {
		return rpcResponse{}, fmt.Errorf("JSON応答のパースに失敗: %w", err)
	}
	return result, nil
}

// parseSSEResponse は素朴なSSEパース: "data: " 行のJSONのうち、このリクエストの
// idと一致する最後のメッセージ（応答）を採用する。
func parseSSEResponse(raw []byte, wantID any) (rpcResponse, error) {
	wantIDNum, _ := json.Marshal(wantID)
	var found *rpcResponse
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		var candidate rpcResponse
		if err := json.Unmarshal([]byte(data), &candidate); err != nil {
			continue
		}
		candIDNum, _ := json.Marshal(candidate.ID)
		if string(candIDNum) == string(wantIDNum) {
			found = &candidate
		}
	}
	if found == nil {
		return rpcResponse{}, fmt.Errorf("SSEレスポンスに対応するJSON-RPC応答が見つかりません")
	}
	return *found, nil
}

func (s *HTTPServerProcess) Start() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.started {
		return true
	}

	initID := s.nextIDLocked()
	resp, err := s.postLocked(map[string]any{
		"jsonrpc": "2.0", "id": initID, "method": "initialize",
		"params": map[string]any{
			"protocolVersion": protocolVersion,
			"capabilities":    map[string]any{},
			"clientInfo":      map[string]any{"name": "mimic-go", "version": "0.1"},
		},
	}, initTimeout)
	if err != nil {
		s.failedReason = err.Error()
		return false
	}
	if len(resp.Error) > 0 {
		s.failedReason = string(resp.Error)
		return false
	}

	listID := s.nextIDLocked()
	resp, err = s.postLocked(map[string]any{"jsonrpc": "2.0", "id": listID, "method": "tools/list", "params": map[string]any{}}, initTimeout)
	if err != nil {
		s.failedReason = err.Error()
		return false
	}
	if len(resp.Error) > 0 {
		s.failedReason = string(resp.Error)
		return false
	}
	var result struct {
		Tools []ToolInfo `json:"tools"`
	}
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		s.failedReason = fmt.Sprintf("予期しないエラー: %v", err)
		return false
	}
	for _, t := range result.Tools {
		if t.Name != "" {
			s.Tools[t.Name] = t
		}
	}
	s.started = true
	s.failedReason = ""
	return true
}

func (s *HTTPServerProcess) CallTool(toolName string, arguments map[string]any) string {
	if !s.started {
		if !s.Start() {
			return fmt.Sprintf("エラー: MCPサーバー '%s' に接続できません (%s)", s.Name, s.failedReason)
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	reqID := s.nextIDLocked()
	resp, err := s.postLocked(map[string]any{
		"jsonrpc": "2.0", "id": reqID, "method": "tools/call",
		"params": map[string]any{"name": toolName, "arguments": arguments},
	}, callTimeout)
	if err != nil {
		s.started = false
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

// Stop はステートレスなHTTPリクエストなので明示的な切断処理は不要。
// セッションIDを破棄し、次回呼び出し時にinitializeからやり直す。
func (s *HTTPServerProcess) Stop() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sessionID = ""
	s.started = false
}
