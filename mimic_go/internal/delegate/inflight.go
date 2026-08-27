package delegate

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// 中断委任マニフェスト（Python版 team.py::_register_inflight 系の移植）。
// Directorプロセス自体がクラッシュ/killされた場合、進行中の委任タスクの
// Overlay作業ディレクトリ（base）が孤立する。baseを作成する前後でここに
// 登録・解除しておくことで、「マニフェストに残っている＝中断扱い」として
// 後から検出できる（Go版では自動再開UIまでは対象外、検出・警告のみ）。

var inflightMu sync.Mutex

// InflightEntry は1件の進行中委任の記録。
type InflightEntry struct {
	TraceID       string   `json:"trace_id"`
	Base          string   `json:"base"`
	ProjectDir    string   `json:"project_dir"`
	Task          string   `json:"task"`
	Label         string   `json:"label"`
	VerifyCmd     string   `json:"verify_cmd"`
	Kind          string   `json:"kind"`
	RolePrompt    string   `json:"role_prompt,omitempty"`
	ApplyChanges  bool     `json:"apply_changes"`
	StartedAt     string   `json:"started_at"`
	CheckpointAge *float64 `json:"-"`
}

func inflightManifestPath() string {
	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}
	return filepath.Join(cwd, ".mimic", "inflight_delegations.json")
}

func loadInflightManifest() map[string]InflightEntry {
	data, err := os.ReadFile(inflightManifestPath())
	if err != nil {
		return map[string]InflightEntry{}
	}
	var m map[string]InflightEntry
	if err := json.Unmarshal(data, &m); err != nil {
		return map[string]InflightEntry{}
	}
	return m
}

func saveInflightManifest(m map[string]InflightEntry) error {
	p := inflightManifestPath()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(p, data, 0o644)
}

// newTraceID は委任1件を識別する短いランダムIDを生成する。
func newTraceID() string {
	return fmt.Sprintf("%d-%04x", time.Now().UnixNano(), rand.Intn(0x10000))
}

// registerInflight は委任開始時（Overlay作成後・Worker起動前）に呼ぶ。
func registerInflight(traceID, base, projectDir, task, label, verifyCmd, kind string, rolePrompt string, applyChanges bool) {
	inflightMu.Lock()
	defer inflightMu.Unlock()
	m := loadInflightManifest()
	m[traceID] = InflightEntry{
		TraceID: traceID, Base: base, ProjectDir: projectDir, Task: task,
		Label: label, VerifyCmd: verifyCmd, Kind: kind,
		RolePrompt: rolePrompt, ApplyChanges: applyChanges,
		StartedAt: time.Now().Format(time.RFC3339),
	}
	_ = saveInflightManifest(m)
}

// unregisterInflight は委任終了時（適用成功/不要/エラー打ち切りいずれも）に
// deferで必ず呼ぶ。
func unregisterInflight(traceID string) {
	inflightMu.Lock()
	defer inflightMu.Unlock()
	m := loadInflightManifest()
	if _, ok := m[traceID]; ok {
		delete(m, traceID)
		_ = saveInflightManifest(m)
	}
}

// ListOrphanedDelegations はマニフエストのうちbaseが現存するエントリのみ返す
// （消えているものは自動で除去する）。CheckpointAgeにはmerged/.mimic_checkpoint.json
// の最終更新からの経過秒数を入れる（短いほど「まだ実行中かもしれない」目安）。
func ListOrphanedDelegations() []InflightEntry {
	inflightMu.Lock()
	m := loadInflightManifest()
	alive := make(map[string]InflightEntry)
	pruned := false
	for tid, e := range m {
		if _, err := os.Stat(e.Base); err == nil {
			alive[tid] = e
		} else {
			pruned = true
		}
	}
	if pruned {
		_ = saveInflightManifest(alive)
	}
	inflightMu.Unlock()

	out := make([]InflightEntry, 0, len(alive))
	for _, e := range alive {
		cpPath := filepath.Join(e.Base, "merged", ".mimic_checkpoint.json")
		if info, err := os.Stat(cpPath); err == nil {
			age := time.Since(info.ModTime()).Seconds()
			e.CheckpointAge = &age
		}
		out = append(out, e)
	}
	return out
}

// WarnOrphanedDelegations は24時間を超える孤立委任があれば標準エラーに警告を出す
// （Python版 __main__.py の起動時警告の移植）。Directorのみが呼ぶこと。
func WarnOrphanedDelegations() {
	for _, e := range ListOrphanedDelegations() {
		started, err := time.Parse(time.RFC3339, e.StartedAt)
		if err != nil {
			continue
		}
		if time.Since(started) > 24*time.Hour {
			fmt.Fprintf(os.Stderr,
				"[mimic-go] ⚠ 24時間以上前に開始された孤立委任があります: %s（開始: %s, task: %.60s）\n",
				e.TraceID, e.StartedAt, e.Task)
		}
	}
}
