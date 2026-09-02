package llm

import (
	"bytes"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"
)

// GeminiCacheManager はGeminiのシステムプロンプト+ツール定義をContext Cacheとして
// 保持する（Python版 agent.py::GeminiContextCacheManager の移植）。毎ターンの
// 再送信をなくし、初回以降のTTFT（最初のトークンまでの時間）を削減する。
// 作成失敗時は透過的に空文字を返し、呼び出し側は通常送信にフォールバックする。
type GeminiCacheManager struct {
	mu sync.Mutex

	name        string // "cachedContents/xxxx"
	expires     time.Time
	contentHash string
	cachedModel string
	failUntil   time.Time
	httpClient  *http.Client
}

const (
	geminiCacheTTLSec        = 300 // 5分（Gemini最小TTL = 60秒）
	geminiCacheRefreshMargin = 30 * time.Second
	geminiCacheFailBackoff   = 600 * time.Second
)

func newGeminiCacheManager() *GeminiCacheManager {
	return &GeminiCacheManager{httpClient: &http.Client{Timeout: 10 * time.Second}}
}

// Get は有効なキャッシュ名を返す。期限切れ・内容変化時は再作成する。失敗時は空文字。
func (g *GeminiCacheManager) Get(model, apiKey, systemPrompt string, tools []ToolSpec) string {
	g.mu.Lock()
	h := contentHash(systemPrompt, tools)
	now := time.Now()
	if g.name != "" && g.cachedModel == model && g.contentHash == h && now.Before(g.expires.Add(-geminiCacheRefreshMargin)) {
		name := g.name
		g.mu.Unlock()
		return name
	}
	// モデルが変わった場合はバックオフをリセット
	if g.cachedModel != "" && g.cachedModel != model {
		g.failUntil = time.Time{}
	}
	if now.Before(g.failUntil) {
		g.mu.Unlock()
		return "" // 失敗バックオフ中はスキップ
	}
	g.mu.Unlock()

	name, err := g.create(model, apiKey, systemPrompt, tools)
	g.mu.Lock()
	defer g.mu.Unlock()
	if err == nil && name != "" {
		g.name = name
		g.expires = time.Now().Add(geminiCacheTTLSec * time.Second)
		g.contentHash = h
		g.cachedModel = model
		g.failUntil = time.Time{}
	} else {
		g.name = ""
		g.cachedModel = model
		g.failUntil = time.Now().Add(geminiCacheFailBackoff)
	}
	return g.name
}

// Invalidate はキャッシュを無効化する（システムプロンプト変更時等に呼ぶ）。
func (g *GeminiCacheManager) Invalidate() {
	g.mu.Lock()
	g.name = ""
	g.expires = time.Time{}
	g.mu.Unlock()
}

func contentHash(systemPrompt string, tools []ToolSpec) string {
	toolsJSON, _ := json.Marshal(tools)
	sum := md5.Sum(append([]byte(systemPrompt), toolsJSON...))
	return hex.EncodeToString(sum[:])[:12]
}

type geminiFunctionDecl struct {
	Name        string         `json:"name"`
	Description string         `json:"description,omitempty"`
	Parameters  map[string]any `json:"parameters,omitempty"`
}

type geminiCacheCreateRequest struct {
	Model             string `json:"model"`
	TTL               string `json:"ttl"`
	SystemInstruction *struct {
		Parts []struct {
			Text string `json:"text"`
		} `json:"parts"`
	} `json:"systemInstruction,omitempty"`
	Tools []struct {
		FunctionDeclarations []geminiFunctionDecl `json:"functionDeclarations"`
	} `json:"tools,omitempty"`
}

// create はGemini cachedContents APIを呼び出してキャッシュを作成し名前を返す
// （Python版 GeminiContextCacheManager._create の移植。OpenAI互換レイヤーとは
// 別の、Google生REST APIを直接叩く — この機能自体がOpenAI互換層に存在しない
// Gemini固有APIのため）。
func (g *GeminiCacheManager) create(model, apiKey, systemPrompt string, tools []ToolSpec) (string, error) {
	var fnDecls []geminiFunctionDecl
	for _, s := range tools {
		if s.Function.Name == "" {
			continue
		}
		fnDecls = append(fnDecls, geminiFunctionDecl{
			Name:        s.Function.Name,
			Description: s.Function.Description,
			Parameters:  s.Function.Parameters,
		})
	}

	req := geminiCacheCreateRequest{
		Model: "models/" + model,
		TTL:   fmt.Sprintf("%ds", geminiCacheTTLSec),
	}
	if systemPrompt != "" {
		req.SystemInstruction = &struct {
			Parts []struct {
				Text string `json:"text"`
			} `json:"parts"`
		}{}
		req.SystemInstruction.Parts = append(req.SystemInstruction.Parts, struct {
			Text string `json:"text"`
		}{Text: systemPrompt})
	}
	if len(fnDecls) > 0 {
		req.Tools = []struct {
			FunctionDeclarations []geminiFunctionDecl `json:"functionDeclarations"`
		}{{FunctionDeclarations: fnDecls}}
	}

	body, err := json.Marshal(req)
	if err != nil {
		return "", err
	}
	url := "https://generativelanguage.googleapis.com/v1beta/cachedContents?key=" + apiKey
	httpReq, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := g.httpClient.Do(httpReq)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		// 404/400 = モデルがキャッシュ非対応（preview系など）。呼び出し元がバックオフする。
		return "", fmt.Errorf("gemini cache create failed: HTTP %d: %s", resp.StatusCode, string(respBody))
	}
	var out struct {
		Name string `json:"name"`
	}
	if err := json.Unmarshal(respBody, &out); err != nil {
		return "", err
	}
	return out.Name, nil
}
