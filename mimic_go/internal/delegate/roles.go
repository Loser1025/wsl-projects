package delegate

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// Specialistロール定義の永続化（Python版 team.py::_save_specialist_role /
// load_saved_roles_section の移植）。成功した委任のロール定義を保存し、
// 実績あるロール文の再利用で品質を安定させる。

const (
	rolesKeep        = 30 // 保存するロール定義の上限（最終使用が古いものから削除）
	rolesInjectLimit = 10 // システムプロンプトに注入する件数
)

var rolesMu sync.Mutex

type roleRecord struct {
	Role     string `json:"role"`
	Uses     int    `json:"uses"`
	Mode     string `json:"mode"`
	LastUsed string `json:"last_used"`
}

func rolesDir() string {
	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}
	p := filepath.Join(cwd, ".mimic", "roles")
	_ = os.MkdirAll(p, 0o755)
	return p
}

// SaveSpecialistRole は成功した委任のロール定義を保存する（同一ロールは
// 使用回数を加算する）。失敗は無視する（Python版と同じくベストエフォート）。
func SaveSpecialistRole(role, mode string) {
	rolesMu.Lock()
	defer rolesMu.Unlock()

	role = strings.TrimSpace(role)
	if role == "" {
		return
	}
	sum := md5.Sum([]byte(role))
	slug := hex.EncodeToString(sum[:])[:10]
	dir := rolesDir()
	p := filepath.Join(dir, slug+".json")

	rec := roleRecord{Role: role, Uses: 0}
	if data, err := os.ReadFile(p); err == nil {
		_ = json.Unmarshal(data, &rec)
	}
	rec.Uses++
	rec.Mode = mode
	rec.LastUsed = time.Now().Format(time.RFC3339)

	data, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return
	}
	if err := os.WriteFile(p, data, 0o644); err != nil {
		return
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	type fileMTime struct {
		name  string
		mtime time.Time
	}
	files := make([]fileMTime, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		files = append(files, fileMTime{e.Name(), info.ModTime()})
	}
	sort.Slice(files, func(i, j int) bool { return files[i].mtime.Before(files[j].mtime) })
	if len(files) > rolesKeep {
		for _, f := range files[:len(files)-rolesKeep] {
			_ = os.Remove(filepath.Join(dir, f.name))
		}
	}
}

// LoadSavedRolesSection は保存済みロール定義をSpecialistモードのシステム
// プロンプト追記用に整形して返す。保存済みロールがなければ空文字
// （Python版 load_saved_roles_section の移植）。
func LoadSavedRolesSection(limit int) string {
	if limit <= 0 {
		limit = rolesInjectLimit
	}
	dir := rolesDir()
	entries, err := os.ReadDir(dir)
	if err != nil {
		return ""
	}
	type fileMTime struct {
		name  string
		mtime time.Time
	}
	files := make([]fileMTime, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		files = append(files, fileMTime{e.Name(), info.ModTime()})
	}
	sort.Slice(files, func(i, j int) bool { return files[i].mtime.After(files[j].mtime) })
	if len(files) > limit {
		files = files[:limit]
	}

	var lines []string
	for _, f := range files {
		data, err := os.ReadFile(filepath.Join(dir, f.name))
		if err != nil {
			continue
		}
		var rec roleRecord
		if err := json.Unmarshal(data, &rec); err != nil {
			continue
		}
		role := strings.ReplaceAll(strings.TrimSpace(rec.Role), "\n", " ")
		if role == "" {
			continue
		}
		if len(role) > 180 {
			role = role[:180]
		}
		lines = append(lines, fmt.Sprintf("- %s（使用%d回）", role, rec.Uses))
	}
	if len(lines) == 0 {
		return ""
	}
	return "\n\n## 保存済みロール（過去に成功した委任のロール定義）\n" +
		"類似タスクでは以下のロール定義をそのまま、または微修正して再利用すること:\n" +
		strings.Join(lines, "\n") + "\n"
}
