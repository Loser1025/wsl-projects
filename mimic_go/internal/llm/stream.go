// ストリーミングchat-completions呼び出し（Python版 _stream_openrouter_api /
// _api_call_with_retry / _handle_api_exception の縮小版）。
// テキストのライブ表示 + tool_calls のインデックス単位蓄積(Python版と同じ方式)、
// リトライ/バックオフ/キーローテーションに対応。
package llm

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"net/http"
	"sort"
	"strings"
	"time"
)

// Python版 config.py の MAX_RETRIES/BASE_BACKOFF/MAX_BACKOFF をそのまま踏襲。
const (
	maxRetries  = 5
	baseBackoff = 2.0
	maxBackoff  = 60.0
)

type streamRequest struct {
	Model      string     `json:"model"`
	Messages   []Message  `json:"messages"`
	Stream     bool       `json:"stream"`
	Tools      []ToolSpec `json:"tools,omitempty"`
	ToolChoice string     `json:"tool_choice,omitempty"`
	MaxTokens  int        `json:"max_tokens,omitempty"`
}

type streamChunk struct {
	Choices []struct {
		Delta struct {
			Content   string `json:"content"`
			ToolCalls []struct {
				Index    int    `json:"index"`
				ID       string `json:"id"`
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
				ExtraContent *ExtraContent `json:"extra_content,omitempty"`
			} `json:"tool_calls"`
		} `json:"delta"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error"`
}

// StreamResult は1回のストリーミング呼び出しの最終結果。
type StreamResult struct {
	Text      string
	ToolCalls []ToolCall
}

// apiError はHTTPステータス付きのAPIエラー。リトライ可否の判定に使う。
type apiError struct {
	status  int
	message string
}

func (e *apiError) Error() string {
	return fmt.Sprintf("APIエラー(status=%d): %s", e.status, e.message)
}

// StreamChat はSSEで応答を受信する。テキストは受信の都度 onText で通知（ライブ表示用）、
// tool_calls はストリーム終了までインデックス単位で蓄積してから StreamResult で返す。
// 429/5xx/接続エラーは指数バックオフでリトライし、401/403はリトライせず即エラーを返す
// （Python版 _handle_api_exception の判定方針を踏襲。コンテキスト超過時の
// メッセージ削減リトライは、observation切り詰めで代替済みのため本バッチでは未移植）。
func (c *Client) StreamChat(ctx context.Context, systemPrompt string, messages []Message,
	tools []ToolSpec, onText func(string)) (StreamResult, error) {

	var lastErr error
	for attempt := 0; attempt < maxRetries; attempt++ {
		if ctx.Err() != nil {
			return StreamResult{}, ctx.Err()
		}

		apiKey, wait := c.keyManager.Acquire()
		if wait > 0 {
			select {
			case <-time.After(time.Duration(wait * float64(time.Second))):
			case <-ctx.Done():
				return StreamResult{}, ctx.Err()
			}
		}

		result, status, err := c.attemptStreamChat(ctx, apiKey, systemPrompt, messages, tools, onText)
		if err == nil {
			c.keyManager.ReportSuccess(apiKey)
			return result, nil
		}
		lastErr = err

		if status == 401 || status == 403 {
			return StreamResult{}, err // 認証・権限エラーはリトライ不可
		}
		if status == 429 {
			c.keyManager.Report429(apiKey)
		}

		backoff := backoffDuration(attempt)
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return StreamResult{}, ctx.Err()
		}
	}
	return StreamResult{}, fmt.Errorf("API最大リトライ数(%d)を超えました: 直前のエラー: %w", maxRetries, lastErr)
}

func backoffDuration(attempt int) time.Duration {
	backoff := baseBackoff*pow2(attempt) + rand.Float64()*2
	if backoff > maxBackoff {
		backoff = maxBackoff
	}
	return time.Duration(backoff * float64(time.Second))
}

func pow2(n int) float64 {
	v := 1.0
	for i := 0; i < n; i++ {
		v *= 2
	}
	return v
}

// attemptStreamChat は1回のHTTPリクエストのみを行う（リトライなし）。
// 戻り値のstatusはエラー時のHTTPステータス（0は接続エラー等ステータス不明を示す）。
func (c *Client) attemptStreamChat(ctx context.Context, apiKey, systemPrompt string, messages []Message,
	tools []ToolSpec, onText func(string)) (StreamResult, int, error) {

	all := make([]Message, 0, len(messages)+1)
	if systemPrompt != "" {
		all = append(all, Message{Role: "system", Content: systemPrompt})
	}
	all = append(all, messages...)

	req := streamRequest{Model: c.model, Messages: all, Stream: true}
	if len(tools) > 0 {
		req.Tools = tools
		req.ToolChoice = "auto"
	}
	if c.provider.MaxTokens > 0 {
		req.MaxTokens = c.provider.MaxTokens
	}

	body, err := json.Marshal(req)
	if err != nil {
		return StreamResult{}, 0, err
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.provider.APIBase+"/chat/completions", bytes.NewReader(body))
	if err != nil {
		return StreamResult{}, 0, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	for k, v := range c.provider.BuildAuthHeaders(apiKey) {
		httpReq.Header.Set(k, v)
	}

	resp, err := c.http.Do(httpReq)
	if err != nil {
		return StreamResult{}, 0, fmt.Errorf("ネットワークエラー: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		var buf bytes.Buffer
		buf.ReadFrom(resp.Body)
		return StreamResult{}, resp.StatusCode, &apiError{status: resp.StatusCode, message: strings.TrimSpace(buf.String())}
	}

	type accCall struct {
		id, name, args, thoughtSig string
	}
	acc := make(map[int]*accCall)
	var textBuf strings.Builder

	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := strings.TrimPrefix(line, "data: ")
		if data == "" || data == "[DONE]" {
			continue
		}
		var chunk streamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue // 壊れた行はスキップ(Python版と同様の寛容な扱い)
		}
		if chunk.Error != nil {
			return StreamResult{}, 0, &apiError{status: 0, message: chunk.Error.Message}
		}
		if len(chunk.Choices) == 0 {
			continue
		}
		delta := chunk.Choices[0].Delta
		if delta.Content != "" {
			textBuf.WriteString(delta.Content)
			onText(delta.Content)
		}
		for _, tc := range delta.ToolCalls {
			cur, ok := acc[tc.Index]
			if !ok {
				cur = &accCall{}
				acc[tc.Index] = cur
			}
			if tc.ID != "" {
				cur.id = tc.ID
			}
			if tc.Function.Name != "" {
				cur.name = tc.Function.Name
			}
			cur.args += tc.Function.Arguments
			if tc.ExtraContent != nil && tc.ExtraContent.Google != nil && tc.ExtraContent.Google.ThoughtSignature != "" {
				cur.thoughtSig = tc.ExtraContent.Google.ThoughtSignature
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return StreamResult{}, 0, err
	}

	result := StreamResult{Text: textBuf.String()}
	if len(acc) > 0 {
		indices := make([]int, 0, len(acc))
		for i := range acc {
			indices = append(indices, i)
		}
		sort.Ints(indices)
		for _, i := range indices {
			c := acc[i]
			tc := ToolCall{
				ID:   c.id,
				Type: "function",
				Function: ToolCallFunction{
					Name:      c.name,
					Arguments: c.args,
				},
			}
			if c.thoughtSig != "" {
				tc.ExtraContent = &ExtraContent{Google: &GoogleExtra{ThoughtSignature: c.thoughtSig}}
			}
			result.ToolCalls = append(result.ToolCalls, tc)
		}
	}
	return result, 0, nil
}
