package mcp

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// ServerSpec は.mcp.jsonの1サーバー分の設定。commandを指定するとstdio
// トランスポート、urlを指定するとStreamable HTTP（リモート）トランスポートで
// 接続する。headersはHTTPトランスポート専用（Bearer認証等）、envはstdio
// トランスポート専用（子プロセスの環境変数）— 両者を混同しないこと
// （Python版 mcp_client.py::McpHttpServerProcess.__init__ の headers=spec.get("headers", {}) 相当）。
type ServerSpec struct {
	Command string            `json:"command"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers"`
}

// LoadServerConfigs はClaude Codeと同じ .mcp.json / mcpServers キーを読む。
// ユーザーホーム→プロジェクト直下の順（後者が同名サーバーを上書き）
// （Python版 mcp_client.py::load_server_configs の移植）。
func LoadServerConfigs(projectDir string) map[string]ServerSpec {
	home, _ := os.UserHomeDir()
	paths := []string{filepath.Join(home, ".mcp.json"), filepath.Join(projectDir, ".mcp.json")}

	servers := make(map[string]ServerSpec)
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		var parsed struct {
			McpServers map[string]ServerSpec `json:"mcpServers"`
		}
		if err := json.Unmarshal(data, &parsed); err != nil {
			continue
		}
		for name, spec := range parsed.McpServers {
			if spec.Command != "" || spec.URL != "" {
				servers[name] = spec
			}
		}
	}
	return servers
}

// policyEntry は.mimic/mcp_policy.jsonの1サーバー分のエントリ。
type policyEntry struct {
	Trust string `json:"trust"`
}

func loadPolicy(projectDir string) map[string]policyEntry {
	data, err := os.ReadFile(filepath.Join(projectDir, ".mimic", "mcp_policy.json"))
	if err != nil {
		return nil
	}
	var policy map[string]policyEntry
	json.Unmarshal(data, &policy)
	return policy
}

// SetServerTrust はサーバーの信頼設定を.mimic/mcp_policy.jsonへ永続化する
// （Python版 set_server_trust の移植。呼び出し口となるUIコマンドは未実装だが、
// 将来の/mcpコマンド実装に備えて関数として先行公開しておく）。
func SetServerTrust(projectDir, serverName, trust string) error {
	path := filepath.Join(projectDir, ".mimic", "mcp_policy.json")
	policy := loadPolicy(projectDir)
	if policy == nil {
		policy = make(map[string]policyEntry)
	}
	policy[serverName] = policyEntry{Trust: trust}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(policy, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}
