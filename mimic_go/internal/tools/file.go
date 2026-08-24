package tools

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const largeFileThreshold = 5000 // Python版 _LARGE_FILE_THRESHOLD を踏襲
const readFileChunk = 20000     // maxReadChars と同じ値でチャンク読みの単位とする

func registerFileTools(r *Registry) {
	r.Register("read_file",
		"ローカルファイルの内容を読み取る。大きいファイルはoffsetを指定して続きを読める。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path":   map[string]any{"type": "string", "description": "読み取るファイルパス"},
				"offset": map[string]any{"type": "integer", "description": "読み取り開始文字位置（デフォルト0）", "default": 0},
			},
			"required": []string{"path"},
		},
		toolReadFile)

	r.Register("write_file",
		"ローカルファイルに内容を書き込む（存在しなければ作成、親ディレクトリも自動作成）",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path":    map[string]any{"type": "string", "description": "書き込み先ファイルパス"},
				"content": map[string]any{"type": "string", "description": "書き込む内容"},
			},
			"required": []string{"path", "content"},
		},
		toolWriteFile)

	r.Register("edit_file",
		"ファイルの特定部分を差分編集する。old_stringをnew_stringに置き換える。old_stringはファイル内で一意である必要がある。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path":       map[string]any{"type": "string", "description": "編集するファイルパス"},
				"old_string": map[string]any{"type": "string", "description": "置き換え対象の文字列（ファイル内で一意である必要あり）"},
				"new_string": map[string]any{"type": "string", "description": "置き換え後の文字列"},
			},
			"required": []string{"path", "old_string", "new_string"},
		},
		toolEditFile)

	r.Register("patch_file",
		"ファイルの一部をsearch/replaceで置換する。edit_fileと異なりインデントのズレを許容したファジーマッチも試みる。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path":    map[string]any{"type": "string", "description": "編集するファイルパス"},
				"search":  map[string]any{"type": "string", "description": "検索するブロック文字列"},
				"replace": map[string]any{"type": "string", "description": "置換後のブロック文字列"},
			},
			"required": []string{"path", "search", "replace"},
		},
		toolPatchFile)

	r.Register("file_info",
		"ファイルのサイズ・行数・種類などの基本情報を取得する（内容そのものは読まない）",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path": map[string]any{"type": "string", "description": "対象ファイルパス"},
			},
			"required": []string{"path"},
		},
		toolFileInfo)

	r.Register("smart_read",
		"ファイルを読む。focus指定でgrep絞り込み、大きいファイルは推奨アクションを案内する。read_fileより先に試すこと。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path":          map[string]any{"type": "string", "description": "読み込むファイルのパス"},
				"focus":         map[string]any{"type": "string", "description": "探したいキーワード・関数名など（省略可）"},
				"context_lines": map[string]any{"type": "integer", "description": "focus指定時の前後行数（デフォルト5）", "default": 5},
			},
			"required": []string{"path"},
		},
		toolSmartRead)

	r.Register("list_directory", "ディレクトリ内のファイル・サブディレクトリ一覧を返す",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path": map[string]any{"type": "string", "description": "一覧表示するディレクトリパス"},
			},
			"required": []string{"path"},
		},
		toolListDirectory)
}

func toolReadFile(args map[string]any) (string, error) {
	path := argString(args, "path")
	offset := argInt(args, "offset", 0)

	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	content := string(data)
	total := len(content)

	if total > largeFileThreshold && offset == 0 {
		preview := content
		if len(preview) > 1500 {
			preview = preview[:1500]
		}
		return fmt.Sprintf(
			"[read_file: %s]\n"+
				"⚠ このファイルは %d 文字あります（推奨上限 %d 文字）。\n"+
				"コンテキスト節約のため以下を先に検討してください:\n"+
				"  • grep_codebase(pattern='キーワード', path='%s')  ← 特定箇所だけ取得\n"+
				"  • smart_read(path='%s', focus='関数名')            ← focus指定で絞り込み\n"+
				"それでも全文が必要な場合は read_file(path='%s', offset=0) を続けてください。\n"+
				"%s\n--- 先頭1,500文字（プレビュー）---\n%s\n%s\n続き: read_file(path='%s', offset=1500)\n",
			path, total, largeFileThreshold, path, path, path,
			strings.Repeat("─", 60), preview, strings.Repeat("─", 60), path,
		), nil
	}

	if offset > total {
		offset = total
	}
	end := offset + readFileChunk
	if end > total {
		end = total
	}
	sliced := content[offset:end]
	remaining := total - end

	header := fmt.Sprintf("[%s  文字 %d–%d / 全%d文字]\n%s\n", path, offset, end, total, strings.Repeat("─", 60))
	var footer string
	if remaining > 0 {
		footer = fmt.Sprintf("\n%s\n⚠ 残り %d 文字\n  続きを読む: offset=%d\n%s", strings.Repeat("─", 60), remaining, end, strings.Repeat("─", 60))
	} else {
		footer = fmt.Sprintf("\n%s\n  ✓ ファイル末尾まで読み込み完了\n%s", strings.Repeat("─", 60), strings.Repeat("─", 60))
	}
	return header + sliced + footer, nil
}

func toolWriteFile(args map[string]any) (string, error) {
	path := argString(args, "path")
	content := argString(args, "content")

	if dir := filepath.Dir(path); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return "", err
		}
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return "", err
	}
	return fmt.Sprintf("書き込み完了: %s (%d 文字)", path, len(content)), nil
}

func toolEditFile(args map[string]any) (string, error) {
	path := argString(args, "path")
	oldString := argString(args, "old_string")
	newString := argString(args, "new_string")

	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	content := string(data)
	count := strings.Count(content, oldString)

	if count == 1 {
		newContent := strings.Replace(content, oldString, newString, 1)
		if err := os.WriteFile(path, []byte(newContent), 0o644); err != nil {
			return "", err
		}
		diffLines := strings.Count(newString, "\n") - strings.Count(oldString, "\n")
		sign := ""
		if diffLines >= 0 {
			sign = "+"
		}
		return fmt.Sprintf("編集完了: %s  (%s%d 行差分, 計 %d 行)", path, sign, diffLines, strings.Count(newContent, "\n")+1), nil
	}
	if count > 1 {
		return "", fmt.Errorf("指定した文字列が %d 箇所に存在します（一意に特定できません）。前後の文脈をより多く含めた文字列を指定してください。", count)
	}
	preview := oldString
	if len(preview) > 120 {
		preview = preview[:120]
	}
	preview = strings.ReplaceAll(preview, "\n", "↵")
	return "", fmt.Errorf("指定された 'old_string' がファイル内に見つかりません: %s\n検索対象（先頭120文字）: %s\ngrep_codebase や smart_read で現在のファイル内容を確認し、正確な文字列で再実行してください。", path, preview)
}

// toolPatchFile はedit_fileより緩いマッチを試みる。
// Python版のdifflib.SequenceMatcherによる類似ブロック探索(3段目)は
// フェーズ2の本バッチでは簡略化のため未移植（1: 完全一致、2: インデント
// 正規化ファジーマッチの2段のみ）。
func toolPatchFile(args map[string]any) (string, error) {
	path := argString(args, "path")
	search := argString(args, "search")
	replace := argString(args, "replace")

	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	content := string(data)

	// 1. 完全一致
	if count := strings.Count(content, search); count > 0 {
		if count > 1 {
			return "", fmt.Errorf("検索ブロックが %d 箇所に存在します（一意に特定できません）。より長い範囲の文字列を指定してください。", count)
		}
		newContent := strings.Replace(content, search, replace, 1)
		if err := os.WriteFile(path, []byte(newContent), 0o644); err != nil {
			return "", err
		}
		diffLines := strings.Count(replace, "\n") - strings.Count(search, "\n")
		sign := ""
		if diffLines >= 0 {
			sign = "+"
		}
		return fmt.Sprintf("編集完了（完全一致）: %s  (%s%d 行差分)", path, sign, diffLines), nil
	}

	// 2. インデント正規化後のファジーマッチ（stripしたコンテンツが完全一致する箇所を探す）
	contentLines := strings.Split(content, "\n")
	sStripped, sIndent := stripCommonIndent(search)
	sLines := strings.Split(sStripped, "\n")
	sKeys := trimmedLines(sLines)
	n := len(sLines)

	type match struct {
		i, bIndent int
	}
	var matches []match
	for i := 0; i+n <= len(contentLines); i++ {
		block := strings.Join(contentLines[i:i+n], "\n")
		bStripped, bIndent := stripCommonIndent(block)
		bKeys := trimmedLines(strings.Split(bStripped, "\n"))
		if equalStrings(bKeys, sKeys) {
			matches = append(matches, match{i, bIndent})
		}
	}

	if len(matches) == 1 {
		m := matches[0]
		indentDelta := m.bIndent - sIndent
		rStripped, _ := stripCommonIndent(replace)
		reIndented := reindent(rStripped, indentDelta)
		newLines := append(append(append([]string{}, contentLines[:m.i]...), strings.Split(reIndented, "\n")...), contentLines[m.i+n:]...)
		trailing := ""
		if strings.HasSuffix(content, "\n") {
			trailing = "\n"
		}
		if err := os.WriteFile(path, []byte(strings.Join(newLines, "\n")+trailing), 0o644); err != nil {
			return "", err
		}
		diffLines := strings.Count(reIndented, "\n") - n + 1
		sign := ""
		if diffLines >= 0 {
			sign = "+"
		}
		return fmt.Sprintf("編集完了（インデント許容マッチ）: %s  (%s%d 行差分, indent_delta=%+d)", path, sign, diffLines, indentDelta), nil
	}
	if len(matches) > 1 {
		return "", fmt.Errorf("検索ブロックが %d 箇所にマッチします（一意に特定できません）。", len(matches))
	}

	preview := search
	if len(preview) > 120 {
		preview = preview[:120]
	}
	preview = strings.ReplaceAll(preview, "\n", "↵")
	return "", fmt.Errorf("指定された検索文字列がファイル内に見つかりません: %s\n検索対象: %s...\nread_file で現在の内容を確認し、正確な（特にインデントや改行を含む）文字列を指定してください。", path, preview)
}

func stripCommonIndent(text string) (string, int) {
	lines := strings.Split(text, "\n")
	minIndent := -1
	for _, l := range lines {
		if strings.TrimSpace(l) == "" {
			continue
		}
		indent := len(l) - len(strings.TrimLeft(l, " \t"))
		if minIndent == -1 || indent < minIndent {
			minIndent = indent
		}
	}
	if minIndent <= 0 {
		return text, 0
	}
	out := make([]string, len(lines))
	for i, l := range lines {
		if len(l) >= minIndent {
			out[i] = l[minIndent:]
		} else {
			out[i] = l
		}
	}
	return strings.Join(out, "\n"), minIndent
}

func reindent(text string, delta int) string {
	lines := strings.Split(text, "\n")
	if delta >= 0 {
		pad := strings.Repeat(" ", delta)
		for i, l := range lines {
			if strings.TrimSpace(l) != "" {
				lines[i] = pad + l
			}
		}
		return strings.Join(lines, "\n")
	}
	trim := -delta
	for i, l := range lines {
		if len(l) >= trim {
			lines[i] = l[trim:]
		}
	}
	return strings.Join(lines, "\n")
}

func trimmedLines(lines []string) []string {
	out := make([]string, len(lines))
	for i, l := range lines {
		out[i] = strings.TrimSpace(l)
	}
	return out
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func toolFileInfo(args map[string]any) (string, error) {
	path := argString(args, "path")
	info, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	data, readErr := os.ReadFile(path)
	sizeChars := info.Size()
	lines := "不明"
	advice := ""
	if readErr == nil {
		text := string(data)
		sizeChars = int64(len(text))
		nLines := strings.Count(text, "\n") + 1
		lines = fmt.Sprintf("%d", nLines)
		if sizeChars > largeFileThreshold {
			advice = fmt.Sprintf("\n[推奨] このファイルは大きいです。read_file より先に:\n  → grep_codebase(pattern='キーワード', path='%s') で絞り込む", path)
		}
	}
	ext := filepath.Ext(path)
	if ext == "" {
		ext = "(拡張子なし)"
	}
	return fmt.Sprintf("パス    : %s\nサイズ  : %d bytes / %d 文字\n行数    : %s\n種類    : %s%s",
		path, info.Size(), sizeChars, lines, ext, advice), nil
}

func toolSmartRead(args map[string]any) (string, error) {
	path := argString(args, "path")
	focus := argString(args, "focus")
	contextLines := argInt(args, "context_lines", 5)

	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	text := string(data)

	if focus != "" {
		out, found := grepInFile(text, focus, contextLines, false)
		if found {
			return fmt.Sprintf("[smart_read] %s / focus=%q\n%s", path, focus, out), nil
		}
		return fmt.Sprintf("「%s」は %s に見つかりませんでした。\nファイル全体を読む場合: read_file(path='%s')", focus, path, path), nil
	}

	size := len(text)
	if size <= largeFileThreshold {
		return text, nil
	}
	nLines := strings.Count(text, "\n") + 1
	preview := text
	if len(preview) > 2000 {
		preview = preview[:2000]
	}
	return fmt.Sprintf(
		"[警告] %s は %d 文字 (%d行) あります。\n"+
			"コンテキスト節約のため以下を推奨:\n"+
			"  grep_codebase(pattern='キーワード', path='%s')  ← 特定箇所を探す\n"+
			"  smart_read(path='%s', focus='関数名')             ← キーワード指定で絞り込む\n\n"+
			"--- 先頭2,000文字（プレビュー）---\n%s", path, size, nLines, path, path, preview), nil
}

func toolListDirectory(args map[string]any) (string, error) {
	path := argString(args, "path")
	entries, err := os.ReadDir(path)
	if err != nil {
		return "", err
	}
	var b strings.Builder
	for _, e := range entries {
		if e.IsDir() {
			fmt.Fprintf(&b, "%s/\n", e.Name())
		} else {
			fmt.Fprintf(&b, "%s\n", e.Name())
		}
	}
	if b.Len() == 0 {
		return "(空のディレクトリ)", nil
	}
	return b.String(), nil
}
