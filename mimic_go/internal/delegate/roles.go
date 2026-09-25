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
	Role      string `json:"role"`
	Uses      int    `json:"uses"`
	PassCount int    `json:"pass_count"`
	FailCount int    `json:"fail_count"`
	Mode      string `json:"mode"`
	LastUsed  string `json:"last_used"`
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

// SaveSpecialistRole は委任のロール定義を保存する（同一ロールは使用回数を加算する）。
// verifyPassedで今回の委任がverify_cmd等の機械検証を通過したかを記録し、
// PassCount/FailCountに積み上げる（internal/tools/skilltrust.goのRecordSkillOutcomeと
// 対称の設計。以前は成功時しか呼ばれずFailCountが常に0だったため、
// LoadSavedRolesSectionの「実績あるロール」判定が使用回数だけに依存していた）。
// ファイルI/O失敗は無視する（Python版と同じくベストエフォート）。
func SaveSpecialistRole(role, mode string, verifyPassed bool) {
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
	if verifyPassed {
		rec.PassCount++
	} else {
		rec.FailCount++
	}
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

	var lines []string
	for _, f := range files {
		if len(lines) >= limit {
			break
		}
		data, err := os.ReadFile(filepath.Join(dir, f.name))
		if err != nil {
			continue
		}
		var rec roleRecord
		if err := json.Unmarshal(data, &rec); err != nil {
			continue
		}
		if rec.FailCount > rec.PassCount {
			// 失敗の方が多いロールは「実績あるロール」として注入しない
			// （腐敗した実績の恒久化防止。以前は使用回数だけで判定していたため、
			// 使われるたびに失敗し続けるロールでも延々と再注入されていた）。
			continue
		}
		role := strings.ReplaceAll(strings.TrimSpace(rec.Role), "\n", " ")
		if role == "" {
			continue
		}
		if len(role) > 180 {
			role = role[:180]
		}
		lines = append(lines, fmt.Sprintf("- %s（使用%d回・検証成功%d/失敗%d）", role, rec.Uses, rec.PassCount, rec.FailCount))
	}
	if len(lines) == 0 {
		return ""
	}
	return "\n\n## 保存済みロール（過去に成功した委任のロール定義）\n" +
		"類似タスクでは以下のロール定義をそのまま、または微修正して再利用すること:\n" +
		strings.Join(lines, "\n") + "\n"
}
