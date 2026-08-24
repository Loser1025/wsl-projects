// Package llm はOpenRouter/Gemini/Mistral chat-completions APIへの直接HTTP
// アクセスを行う（SDK不使用というPython版agent.pyの方針を踏襲し net/http を
// 直接使う）。3プロバイダともOpenAI互換のchat/completionsエンドポイントを
// 提供するため、リクエスト/レスポンス形式は共通化できる。
package llm

import (
	"net/http"
	"time"

	"mimic/internal/config"
)

// ToolCallFunction はOpenAI tool_calls形式の function 部分。
type ToolCallFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// ToolCall は1回のツール呼び出し（アシスタントメッセージに乗せて送り返す形式）。
type ToolCall struct {
	ID       string           `json:"id"`
	Type     string           `json:"type"`
	Function ToolCallFunction `json:"function"`
}

// Message はOpenAI chat-completions形式の1メッセージ。
// role: "system" / "user" / "assistant" / "tool"
type Message struct {
	Role       string     `json:"role"`
	Content    string     `json:"content,omitempty"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
}

// ToolSpec はモデルへ渡すツール定義（OpenAI function calling形式）。
type ToolSpec struct {
	Type     string       `json:"type"`
	Function ToolFuncSpec `json:"function"`
}

type ToolFuncSpec struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

// Client は現在アクティブな1プロバイダに対するHTTPクライアント。
// マルチプロバイダの動的切り替え(Python版のMULTI-PROVIDER MODEL SELECTOR)は
// 未移植 — 起動時に選ばれたプロバイダに固定される簡略方式とする。
type Client struct {
	provider   *config.ProviderConfig
	keyManager *KeyManager
	model      string
	http       *http.Client
}

func NewClient(provider *config.ProviderConfig) *Client {
	return &Client{
		provider:   provider,
		keyManager: NewKeyManager(provider.APIKeys, provider.RPMLimit),
		model:      provider.Model,
		http:       &http.Client{Timeout: 120 * time.Second},
	}
}

func (c *Client) ProviderName() string { return c.provider.Name }
func (c *Client) Model() string        { return c.model }
