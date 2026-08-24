package tools

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// skillTrustEntry はスキル1件分の信頼スコア（Python版 skills.py::record_outcome
// が.mimic/skill_trust.jsonに書く形式と互換）。
type skillTrustEntry struct {
	PassCount int    `json:"pass_count"`
	FailCount int    `json:"fail_count"`
	LastUsed  string `json:"last_used"`
}

var skillTrustMu sync.Mutex

// RecordSkillOutcome はSkill使用を伴った委任のverify結果を記録する
// （Python版 skills.py::record_outcome の移植）。失敗しても黙って無視する
// （記録はベストエフォート）。
//
// Python版はmimic_tuiパッケージ設置ディレクトリ直下の.mimic/を固定で使う
// （インストール単位でグローバル）が、Go版は他の.mimic/*（checkpoint,
// sessions等）と同様にprojectDir直下を使う（プロジェクト単位、意図的な適応）。
func RecordSkillOutcome(projectDir, name string, verifyPassed bool) {
	if name == "" {
		return
	}
	skillTrustMu.Lock()
	defer skillTrustMu.Unlock()

	path := filepath.Join(projectDir, ".mimic", "skill_trust.json")
	data := make(map[string]skillTrustEntry)
	if raw, err := os.ReadFile(path); err == nil {
		json.Unmarshal(raw, &data) // パース失敗時は空のまま上書き（ベストエフォート）
	}
	entry := data[name]
	if verifyPassed {
		entry.PassCount++
	} else {
		entry.FailCount++
	}
	entry.LastUsed = time.Now().Format("2006-01-02T15:04:05")
	data[name] = entry

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	if out, err := json.MarshalIndent(data, "", "  "); err == nil {
		os.WriteFile(path, out, 0o644)
	}
}
