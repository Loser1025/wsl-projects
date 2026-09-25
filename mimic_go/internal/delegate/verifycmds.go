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
	Fails    int    `json:"fails"`
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
// 通過はこのverify_cmdへの信頼を回復させるので、蓄積していた失敗カウント(Fails)も
// リセットする（NoteVerifyCmdFailureの閾値判定が古い失敗を引きずらないように）。
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
	data[key] = verifyCmdEntry{Cmd: cmd, Passes: passes, Fails: 0, LastUsed: time.Now().Format(time.RFC3339)}
	saveVerifyCmds(data)
}

// ForgetLearnedVerifyCmd は無効と判明したverify_cmdを実績庫から即座に削除する。
// 単発の環境要因失敗まで即座に忘れてしまうと学習コストがゼロにならないため、
// abort系エラー(worker.go::abortExitCodes)からの呼び出しはNoteVerifyCmdFailure経由の
// 閾値判定に置き換え済み。ForgetLearnedVerifyCmd自体は「即時破棄したい」ことが
// 明確な場面向けに残す。
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

// verifyCmdForgetThreshold は学習済みverify_cmdを破棄するまでに許容する
// 「Passesを上回る累積失敗回数」。1（単発失敗で即破棄）ではなく2にすることで、
// 環境要因等による単発失敗では学習を失わず、慢性的に不安定なverify_cmdだけを
// 淘汰する（腐敗した学習の恒久化と、過剰反応での学習ゼロ化の両極端を避ける）。
const verifyCmdForgetThreshold = 2

// NoteVerifyCmdFailure は学習済みverify_cmdがabort系エラー（bash構文エラー・
// 権限なし・コマンド不明等、Workerの修正リトライでは直りようがない失敗）で
// 終わったことを記録する。projectDir/cmdの組み合わせがそもそも学習実績に
// 存在しない（テンプレート/自動調達直後で未学習）場合は何もしない——
// 学習していないものを「忘れる」必要はないため。
// 累積失敗がverifyCmdForgetThresholdに達した時点で学習を破棄しtrueを返す。
// 破棄しなかった場合はfalseを返す。
func NoteVerifyCmdFailure(projectDir, cmd string) bool {
	if cmd == "" {
		return false
	}
	verifyCmdsMu.Lock()
	defer verifyCmdsMu.Unlock()
	key := verifyCmdKey(projectDir)
	data := loadVerifyCmds()
	entry, ok := data[key]
	if !ok || entry.Cmd != cmd {
		return false
	}
	entry.Fails++
	if entry.Fails-entry.Passes >= verifyCmdForgetThreshold {
		delete(data, key)
		saveVerifyCmds(data)
		return true
	}
	data[key] = entry
	saveVerifyCmds(data)
	return false
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

// staticCheckTemplates は言語別の「軽量静的解析」コマンド（verify_cmdより
// 安価・高速で、ビルド不能・構文エラーのような最低限の破損を検出するための
// もの）。テストフレームワークの有無に関わらず常時実行する前提のため、
// 外部ツールのインストールを前提にできるgo/cargo以外は標準ライブラリのみで
// 動く手段（python: compileall）に限定する。tsc等の外部ツール導入前提の言語は
// 対象外（未インストール環境で常時失敗になるのを避けるため）。
var staticCheckTemplates = []struct {
	manifest string
	cmd      string
}{
	{"go.mod", "go build ./..."},
	{"pyproject.toml", "python -m compileall -q ."},
	{"pytest.ini", "python -m compileall -q ."},
	{"setup.py", "python -m compileall -q ."},
	{"Cargo.toml", "cargo check"},
}

// StaticCheckCmd はプロジェクトルートのマニフェストファイル検出から
// 「軽量静的解析」コマンドを1つ返す（読み取りのみ）。検出できなければ空文字。
// verify_cmd（テスト実行等、コストが高いことが多い）の前段として常時実行し、
// ビルドを壊すタイポ等をWorkerの自己申告に依存せず機械的に検出するために使う。
// 環境変数 MIMIC_STATIC_CHECK=0 で無効化できる。
func StaticCheckCmd(projectDir string) string {
	if os.Getenv("MIMIC_STATIC_CHECK") == "0" {
		return ""
	}
	for _, t := range staticCheckTemplates {
		if info, err := os.Stat(filepath.Join(projectDir, t.manifest)); err == nil && !info.IsDir() {
			return t.cmd
		}
	}
	return ""
}
