// Package llm はOpenRouter/Gemini chat-completions APIへの直接HTTP
// アクセスを行う（SDK不使用というPython版agent.pyの方針を踏襲し net/http を
// 直接使う）。両プロバイダともOpenAI互換のchat/completionsエンドポイントを
// 提供するため、リクエスト/レスポンス形式は共通化できる。
package llm

import (
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"time"

	"mimic/internal/config"
)

// randomHex はn文字（n/2バイト）のランダム16進文字列を返す
// （Python版 uuid4().hex[:16] 相当）。
func randomHex(n int) string {
	b := make([]byte, (n+1)/2)
	if _, err := rand.Read(b); err != nil {
		return ""
	}
	return hex.EncodeToString(b)[:n]
}

// ToolCallFunction はOpenAI tool_calls形式の function 部分。
type ToolCallFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// ToolCall は1回のツール呼び出し（アシスタントメッセージに乗せて送り返す形式）。
// ExtraContentはGemini固有の thought_signature を往復させるためのフィールド
// （Python版 agent.py::_build_tool_call_entry の移植。Geminiのfunction calling
// プロトコルはマルチターンでこの署名の保持を要求するため、往復させないと
// 2ターン目以降のtool_callsでプロトコル違反になりうる）。
type ToolCall struct {
	ID           string           `json:"id"`
	Type         string           `json:"type"`
	Function     ToolCallFunction `json:"function"`
	ExtraContent *ExtraContent    `json:"extra_content,omitempty"`
}

// ExtraContent はGemini拡張フィールド（OpenAI互換エンドポイント経由でも
// extra_content.google.thought_signature として往復する）。
type ExtraContent struct {
	Google *GoogleExtra `json:"google,omitempty"`
}

type GoogleExtra struct {
	ThoughtSignature string `json:"thought_signature,omitempty"`
}

// Message はOpenAI chat-completions形式の1メッセージ。
// role: "system" / "user" / "assistant" / "tool"
type Message struct {
	Role       string     `json:"role"`
	Content    string     `json:"content,omitempty"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`

	// SkipSave はこのメッセージがターン内の一時的な誘導（空応答リトライ・
	// XML救済リトライ・最終回答ゲートA/Bの差し戻し等）であり、ターン確定後は
	// 次ターン以降の永続会話履歴から取り除くべきことを示す（Python版
	// orchestrator.py の "_skip_save": True マーカーの移植）。APIへは送らない
	// 内部状態のためJSONへは含めない。
	SkipSave bool `json:"-"`
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
	provider        *config.ProviderConfig
	keyManager      *KeyManager
	model           string
	http            *http.Client
	sessionCacheKey string
	geminiCache     *GeminiCacheManager
}

func NewClient(provider *config.ProviderConfig) *Client {
	return &Client{
		provider:   provider,
		keyManager: NewKeyManager(provider.APIKeys, provider.RPMLimit),
		model:      provider.Model,
		http:       &http.Client{Timeout: 120 * time.Second},
		// セッション単位で固定のランダムキー（Python版 agent.py:669
		// `self._session_cache_key = uuid4().hex[:16]` の移植）。永続ダイジェストの
		// シャドーモード保存でセッション識別子として使う。
		sessionCacheKey: randomHex(16),
		// Gemini向けContext Cache（Python版 agent.py::GeminiContextCacheManager の
		// 移植）。gemini以外のプロバイダでは未使用のままだが、構造体生成コスト自体は
		// 無視できるほど小さいため常に生成しておく。
		geminiCache: newGeminiCacheManager(),
	}
}

func (c *Client) ProviderName() string { return c.provider.Name }
func (c *Client) Model() string        { return c.model }

// SessionCacheKey はセッション単位で固定のランダムキーを返す
// （Python版 self._session_cache_key 相当。永続ダイジェストのシャドーモード保存
// [_persist_digest_shadow]でセッション識別子として使う）。
func (c *Client) SessionCacheKey() string { return c.sessionCacheKey }

// KeyStatus は現在のプロバイダのAPIキー状態一覧を返す（/status コマンド等での
// 表示用。KeyManager.Statusのラッパー）。
func (c *Client) KeyStatus() []KeyStatus { return c.keyManager.Status() }

// NReadyKeys は現在すぐ使えるキー数を返す。
func (c *Client) NReadyKeys() int { return c.keyManager.NReadyKeys() }

// TotalTokensAvailable は全キーのトークン残量合計を返す。
func (c *Client) TotalTokensAvailable() float64 { return c.keyManager.TotalTokensAvailable() }

// ContextLength はモデルのコンテキストウィンドウ（トークン数）を返す。
// 不明な場合は0（selector.SelectInteractivelyで疎通確認できなかった場合等）。
func (c *Client) ContextLength() int { return c.provider.ContextLength }

// SetModel はモデル名を直接切り替える（Python版 /model <名前> 直接指定の移植。
// TUI実行中にライブセレクターを再起動する仕組みは無いため、名前直指定のみ対応）。
// context_lengthは不明（0）に戻る点に注意——動的圧縮しきい値はフォールバック値を使う。
func (c *Client) SetModel(name string) {
	c.model = name
	c.provider.ContextLength = 0
}
