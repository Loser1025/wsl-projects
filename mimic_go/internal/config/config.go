// Package config は .env の読み込みを担当する
// （Python版 config.py::load_config の移植。マルチプロバイダ(OpenRouter/Gemini)
// 対応済み。モデル一覧取得・対話的セレクターUI(config.py内の
// MULTI-PROVIDER MODEL SELECTOR)は未移植 — アクティブプロバイダは
// OpenRouter→Geminiの優先順位で自動選択する簡略方式とする）。
package config

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// ProviderConfig は1プロバイダ分の設定（Python版 OpenRouterConfig/
// GoogleAIConfig を統一表現にしたもの）。
type ProviderConfig struct {
	Name          string // "openrouter" / "gemini"
	APIBase       string
	APIKeys       []string
	Model         string
	RPMLimit      int
	MaxTokens     int
	ContextLength int // モデルのコンテキストウィンドウ（トークン数）、0=不明。selector.SelectInteractivelyが設定する
}

// BuildAuthHeaders はプロバイダごとの認証ヘッダーを返す。
// OpenRouterのみ HTTP-Referer/X-Title を追加する（Python版と同じ）。
func (p *ProviderConfig) BuildAuthHeaders(apiKey string) map[string]string {
	h := map[string]string{"Authorization": "Bearer " + apiKey}
	if p.Name == "openrouter" {
		h["HTTP-Referer"] = "https://github.com/Loser1025/mimic"
		h["X-Title"] = "Mimic Go"
	}
	return h
}

const (
	openRouterAPIBase = "https://openrouter.ai/api/v1"
	geminiAPIBase     = "https://generativelanguage.googleapis.com/v1beta/openai"
)

// OpenRouterAPIBase/GeminiAPIBase はinternal/selector等の
// 外部パッケージからAPIエンドポイントを参照するための公開アクセサ。
func OpenRouterAPIBase() string { return openRouterAPIBase }
func GeminiAPIBase() string     { return geminiAPIBase }

type Config struct {
	Providers    map[string]*ProviderConfig // 利用可能な全プロバイダ（未設定なら空）
	Active       *ProviderConfig            // 起動時に自動選択されたプロバイダ
	MaxTokens    int
	SystemPrompt string
}

// ErrEnvTemplateGenerated はLoadが.envの不在を検出し、テンプレートを新規生成して
// 案内した際に返す番兵エラー。呼び出し元（cmd/mimic）はこれを通常のエラーと区別し、
// 「設定してから再実行してください」という案内で正常終了(exit 0)すべきことを示す
// （Python版 config.py::load_config の_generate_env_template呼び出し箇所の移植）。
var ErrEnvTemplateGenerated = errors.New("env template generated")

// envTemplate は.envが存在しない場合に生成する雛形（Python版 config.py::
// _generate_env_template の移植）。
const envTemplate = `# =====================================================
# Mimic Go 設定ファイル
# =====================================================

# ── Actor: OpenRouter (https://openrouter.ai/keys)
# OPENROUTER_KEY_1=YOUR_OPENROUTER_KEY_1
# OPENROUTER_KEY_2=YOUR_OPENROUTER_KEY_2
# OPENROUTER_KEY_3=YOUR_OPENROUTER_KEY_3
# OPENROUTER_MODEL=openrouter/auto

# ── Actor: Google AI Studio (https://aistudio.google.com/apikey)
# GEMINI_KEY_1=YOUR_GEMINI_KEY_1
# GEMINI_KEY_2=YOUR_GEMINI_KEY_2
# GEMINI_KEY_3=YOUR_GEMINI_KEY_3
# GEMINI_MODEL=gemini-2.0-flash
# RPM_LIMIT_GEMINI=15

# ── 共通設定 ──
# どちらか一方（または両方）のキーを設定してください
RPM_LIMIT=20

# システムプロンプト
SYSTEM_PROMPT=あなたは有能なAIアシスタントです。日本語で丁寧に回答してください。
`

// Load は指定パスの .env ファイルを読み、Config を返す。
// Python版と同じキー名規則（<PROVIDER>_KEY_1..9 / <PROVIDER>_MODEL / RPM_LIMIT_*）を使う。
// .envが存在しない場合はテンプレートを新規生成し、ErrEnvTemplateGeneratedを返す
// （Python版 load_config の_generate_env_template呼び出しの移植）。
func Load(envPath string) (*Config, error) {
	if _, statErr := os.Stat(envPath); statErr != nil {
		if os.IsNotExist(statErr) {
			if err := os.WriteFile(envPath, []byte(envTemplate), 0o644); err != nil {
				return nil, fmt.Errorf(".env テンプレートの生成に失敗しました: %w", err)
			}
			return nil, ErrEnvTemplateGenerated
		}
		return nil, statErr
	}

	raw, err := parseEnvFile(envPath)
	if err != nil {
		return nil, err
	}

	systemPrompt := raw["SYSTEM_PROMPT"]
	maxTokens := 0
	if mt := raw["MAX_TOKENS"]; mt != "" {
		if n, err := strconv.Atoi(mt); err == nil {
			maxTokens = n
		}
	}
	defaultRPM := 3
	if v := raw["RPM_LIMIT"]; v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			defaultRPM = n
		}
	}

	providers := make(map[string]*ProviderConfig)

	if keys := collectKeys(raw, "OPENROUTER_KEY"); len(keys) > 0 {
		model := raw["OPENROUTER_MODEL"]
		if model == "" {
			model = "openrouter/auto"
		}
		providers["openrouter"] = &ProviderConfig{
			Name: "openrouter", APIBase: openRouterAPIBase, APIKeys: keys,
			Model: model, RPMLimit: defaultRPM, MaxTokens: maxTokens,
		}
	}

	if keys := collectKeys(raw, "GEMINI_KEY"); len(keys) > 0 {
		model := raw["GEMINI_MODEL"]
		if model == "" {
			model = "gemini-2.0-flash"
		}
		rpm := defaultRPM
		if v := raw["RPM_LIMIT_GEMINI"]; v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				rpm = n
			}
		}
		providers["gemini"] = &ProviderConfig{
			Name: "gemini", APIBase: geminiAPIBase, APIKeys: keys,
			Model: model, RPMLimit: rpm, MaxTokens: maxTokens,
		}
	}

	if len(providers) == 0 {
		return nil, fmt.Errorf(".env に有効な OPENROUTER_KEY / GEMINI_KEY が見つかりません: %s", envPath)
	}

	var active *ProviderConfig
	for _, name := range []string{"openrouter", "gemini"} {
		if p, ok := providers[name]; ok {
			active = p
			break
		}
	}

	return &Config{
		Providers:    providers,
		Active:       active,
		MaxTokens:    maxTokens,
		SystemPrompt: systemPrompt,
	}, nil
}

// collectKeys は <PREFIX>_1 .. <PREFIX>_9、無ければ <PREFIX> 単体を集める
// （"YOUR_"始まりのプレースホルダーは除外、Python版と同じ扱い）。
func collectKeys(raw map[string]string, prefix string) []string {
	var keys []string
	for i := 1; i <= 9; i++ {
		k := raw[fmt.Sprintf("%s_%d", prefix, i)]
		if k != "" && !strings.HasPrefix(k, "YOUR_") {
			keys = append(keys, k)
		}
	}
	if len(keys) == 0 {
		if k := raw[prefix]; k != "" && !strings.HasPrefix(k, "YOUR_") {
			keys = append(keys, k)
		}
	}
	return keys
}

func parseEnvFile(path string) (map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf(".env を開けません: %w", err)
	}
	defer f.Close()

	out := make(map[string]string)
	scanner := bufio.NewScanner(f)
	first := true
	for scanner.Scan() {
		line := scanner.Text()
		if first {
			// UTF-8 BOM付きファイルだと先頭キーの前にBOMが混入してパースが壊れるため除去する。
			line = strings.TrimPrefix(line, "\uFEFF")
			first = false
		}
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		idx := strings.Index(line, "=")
		if idx < 0 {
			continue
		}
		key := strings.TrimSpace(line[:idx])
		val := strings.TrimSpace(line[idx+1:])
		val = strings.Trim(val, `"'`)
		out[key] = val
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return out, nil
}
