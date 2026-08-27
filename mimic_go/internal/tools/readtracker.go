package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// readThisTurn はターン内でread_file済みのパス集合（Python版 _tls / _get_registry
// の移植）。internal/tools は internal/react をimportできないため、パッケージ
// レベルのミューテックス保護状態＋公開関数として実装する。
var (
	readThisTurnMu sync.Mutex
	readThisTurn   = map[string]bool{}
)

// MarkReadThisTurn はread_file成功時に呼ぶ（tools.py read_fileの登録箇所の移植）。
func MarkReadThisTurn(path string) {
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = path
	}
	readThisTurnMu.Lock()
	readThisTurn[abs] = true
	readThisTurnMu.Unlock()
}

// WasReadThisTurn はwrite/edit/patch_fileの直前チェックに使う。
func WasReadThisTurn(path string) bool {
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = path
	}
	readThisTurnMu.Lock()
	defer readThisTurnMu.Unlock()
	return readThisTurn[abs]
}

// ClearReadThisTurnRegistry はターン開始時に呼ぶ（Python版 clear_read_files_registry
// の移植。orchestrator.py内での呼び出し箇所に対応するのはinternal/react/loop.go）。
func ClearReadThisTurnRegistry() {
	readThisTurnMu.Lock()
	readThisTurn = map[string]bool{}
	readThisTurnMu.Unlock()
}

// checkReadWarning は既読チェックの警告文を返す（Python版 _check_read_warning の移植）。
// 既読の場合は空文字列。
func checkReadWarning(path string) string {
	if WasReadThisTurn(path) {
		return ""
	}
	return "⚠ 警告: このファイルは現在のターンで read_file されていません。内容を確認せずに編集しています。\n"
}

// generateDiff はold/newの統一diff風スニペットを返す（Python版 _generate_diff の移植。
// Goには標準ライブラリにdifflib.unified_diff相当が無いため、最長共通部分列(LCS)による
// 行単位diffを自前実装する）。30行を超える場合は+N/-Mの要約に切り詰める。
func generateDiff(oldText, newText string) string {
	oldLines := strings.Split(oldText, "\n")
	newLines := strings.Split(newText, "\n")
	diffLines := lineDiff(oldLines, newLines)

	added, removed := 0, 0
	for _, l := range diffLines {
		switch {
		case strings.HasPrefix(l, "+"):
			added++
		case strings.HasPrefix(l, "-"):
			removed++
		}
	}

	var body string
	if len(diffLines) > 30 {
		body = fmt.Sprintf("（差分が大きいため省略: +%d/-%d 行）", added, removed)
	} else {
		body = strings.Join(diffLines, "\n")
	}
	return "─── 差分 ───\n" + body + "\n────────────"
}

// lineDiff はLCSベースの簡易unified diff行リストを返す（"+"/"-"/" "プレフィックス付き）。
func lineDiff(a, b []string) []string {
	n, m := len(a), len(b)
	dp := make([][]int, n+1)
	for i := range dp {
		dp[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if a[i] == b[j] {
				dp[i][j] = dp[i+1][j+1] + 1
			} else if dp[i+1][j] >= dp[i][j+1] {
				dp[i][j] = dp[i+1][j]
			} else {
				dp[i][j] = dp[i][j+1]
			}
		}
	}
	var out []string
	i, j := 0, 0
	for i < n && j < m {
		switch {
		case a[i] == b[j]:
			out = append(out, "  "+a[i])
			i++
			j++
		case dp[i+1][j] >= dp[i][j+1]:
			out = append(out, "- "+a[i])
			i++
		default:
			out = append(out, "+ "+b[j])
			j++
		}
	}
	for ; i < n; i++ {
		out = append(out, "- "+a[i])
	}
	for ; j < m; j++ {
		out = append(out, "+ "+b[j])
	}
	return out
}

// syntaxCheckNote はMIMIC_SYNTAX_CHECK環境変数（既定on）で有効になる書き込み後の
// 非ブロッキング構文チェック（Python版 _syntax_check_note の移植）。
// .py→python3 -m py_compile、.json→encoding/json、.ts/.tsx→tsc --noEmit（有れば）。
func syntaxCheckNote(path string) string {
	if v := os.Getenv("MIMIC_SYNTAX_CHECK"); v == "0" || strings.EqualFold(v, "false") {
		return ""
	}
	ext := strings.ToLower(filepath.Ext(path))
	switch ext {
	case ".py":
		if _, err := exec.LookPath("python3"); err != nil {
			return ""
		}
		cmd := exec.Command("python3", "-m", "py_compile", path)
		out, err := cmd.CombinedOutput()
		if err != nil {
			return "✗構文チェックNG: " + strings.TrimSpace(string(out))
		}
		return "✓構文チェックOK"
	case ".json":
		data, err := os.ReadFile(path)
		if err != nil {
			return ""
		}
		var v any
		if err := json.Unmarshal(data, &v); err != nil {
			return "✗構文チェックNG: " + err.Error()
		}
		return "✓構文チェックOK"
	case ".ts", ".tsx":
		if _, err := exec.LookPath("tsc"); err != nil {
			return ""
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, "tsc", "--noEmit", path)
		out, err := cmd.CombinedOutput()
		if err != nil {
			return "✗構文チェックNG: " + strings.TrimSpace(string(out))
		}
		return "✓構文チェックOK"
	}
	return ""
}
