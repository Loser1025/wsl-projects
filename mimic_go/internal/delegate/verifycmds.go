package delegate

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// verify_cmd のプロジェクト学習（検証コマンドの実績庫。Python版
// team.py::get_learned_verify_cmd 系の移植）。検証を通過したverify_cmdを
// プロジェクト単位で永続化し、2回目以降の自動調達コストをゼロにする。
// 無効と判明したコマンド（bash構文エラー等）は削除する。

var verifyCmdsMu sync.Mutex

type verifyCmdEntry struct {
	Cmd      string `json:"cmd"`
	Passes   int    `json:"passes"`
	LastUsed string `json:"last_used"`
}

func verifyCmdsPath() string {
	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}
	return filepath.Join(cwd, ".mimic", "verify_cmds.json")
}

func loadVerifyCmds() map[string]verifyCmdEntry {
	data, err := os.ReadFile(verifyCmdsPath())
	if err != nil {
		return map[string]verifyCmdEntry{}
	}
	var m map[string]verifyCmdEntry
	if err := json.Unmarshal(data, &m); err != nil {
		return map[string]verifyCmdEntry{}
	}
	return m
}

func saveVerifyCmds(m map[string]verifyCmdEntry) {
	p := verifyCmdsPath()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return
	}
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(p, data, 0o644)
}

func verifyCmdKey(projectDir string) string {
	abs, err := filepath.Abs(projectDir)
	if err != nil {
		return projectDir
	}
	return abs
}

// GetLearnedVerifyCmd はこのプロジェクトで過去に検証通過したverify_cmdを返す
// （なければ空文字）。
func GetLearnedVerifyCmd(projectDir string) string {
	verifyCmdsMu.Lock()
	defer verifyCmdsMu.Unlock()
	entry, ok := loadVerifyCmds()[verifyCmdKey(projectDir)]
	if !ok {
		return ""
	}
	return entry.Cmd
}

// SaveLearnedVerifyCmd は検証通過したverify_cmdを保存する（同一なら通過回数を加算）。
func SaveLearnedVerifyCmd(projectDir, cmd string) {
	if cmd == "" {
		return
	}
	verifyCmdsMu.Lock()
	defer verifyCmdsMu.Unlock()
	key := verifyCmdKey(projectDir)
	data := loadVerifyCmds()
	passes := 1
	if entry, ok := data[key]; ok && entry.Cmd == cmd {
		passes = entry.Passes + 1
	}
	data[key] = verifyCmdEntry{Cmd: cmd, Passes: passes, LastUsed: time.Now().Format(time.RFC3339)}
	saveVerifyCmds(data)
}

// ForgetLearnedVerifyCmd は無効と判明したverify_cmdを実績庫から削除する。
func ForgetLearnedVerifyCmd(projectDir, cmd string) {
	verifyCmdsMu.Lock()
	defer verifyCmdsMu.Unlock()
	key := verifyCmdKey(projectDir)
	data := loadVerifyCmds()
	if entry, ok := data[key]; ok && entry.Cmd == cmd {
		delete(data, key)
		saveVerifyCmds(data)
	}
}

// verifyCmdTemplates は言語別verify_cmdテンプレート（Python版
// _VERIFY_CMD_TEMPLATES を踏襲）。プロジェクトルートのマニフェストファイルから
// テンプレートコマンドを推定し、コストゼロで候補を用意する。
var verifyCmdTemplates = []struct {
	manifest string
	cmd      string
}{
	{"pyproject.toml", "python -m pytest -q"},
	{"pytest.ini", "python -m pytest -q"},
	{"setup.py", "python -m pytest -q"},
	{"package.json", "npm test --silent"},
	{"Cargo.toml", "cargo test"},
	{"go.mod", "go test ./..."},
	{"Gemfile", "bundle exec rspec"},
	{"composer.json", "composer test"},
}

// TemplateVerifyCmd はプロジェクトルートのマニフェストファイル検出から
// verify_cmd候補を1つ返す（読み取りのみ）。検出できなければ空文字を返す。
// 環境変数 MIMIC_VERIFY_TEMPLATES=0 で無効化できる。
func TemplateVerifyCmd(projectDir string) string {
	if os.Getenv("MIMIC_VERIFY_TEMPLATES") == "0" {
		return ""
	}
	for _, t := range verifyCmdTemplates {
		if info, err := os.Stat(filepath.Join(projectDir, t.manifest)); err == nil && !info.IsDir() {
			return t.cmd
		}
	}
	return ""
}
