package tools

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const largeFileThreshold = 5000 // Python版 _LARGE_FILE_THRESHOLD を踏襲
const readFileChunk = 10000     // Python版 _TOOL_CHUNK_SIZE を踏襲（read_tool_cacheと同じ値）

// checkWorkerWriteBoundary はWorker（OverlayFS隔離サブプロセス）実行時、
// 作業ディレクトリの外への書き込みを拒否する（Python版 tools.py::_check_worker_write_boundary
// の移植）。Overlay隔離は作業ディレクトリ（merged）のマウントにしか効かないため、
// 絶対パスで外部へ書くとホストFSへ直接書き込まれ、差分検出（changed_files）にも
// 掛からず適用もロールバックもできない「見えない書き込み」になる。
// 空文字列以外を返した場合、呼び出し元は書き込みを行わずそれをそのまま返すこと。
func checkWorkerWriteBoundary(path string) string {
	if os.Getenv("MIMIC_NO_AUTOGIT") == "" {
		return ""
	}
	root, err := os.Getwd()
	if err != nil {
		return ""
	}
	root, err = filepath.Abs(root)
	if err != nil {
		return ""
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return ""
	}
	rel, err := filepath.Rel(root, abs)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return fmt.Sprintf(
			"エラー: 作業ディレクトリ（%s）の外への書き込みは禁止されています: %s\n"+
				"この環境はOverlayFS隔離されており、外部への書き込みは差分として検出・適用されません。\n"+
				"作業ディレクトリ内の相対パスで書き込んでください。"+
				"外部ファイルの変更が必要な場合は、その旨を最終回答でDirectorに報告してください。",
			root, path)
	}
	return ""
}

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
	// Python版はcontent[offset:offset+chunk]を文字(Unicode codepoint)単位で
	// スライスするため、Go版もバイト単位ではなくrune単位に変換して扱う
	// （日本語等マルチバイト文字混じりファイルでオフセット・チャンク境界・
	// 文字数表示がPython版とズレるのを防ぐ）。
	runes := []rune(string(data))
	total := len(runes)
	MarkReadThisTurn(path)

	if total > largeFileThreshold && offset == 0 {
		previewLen := 1500
		if previewLen > total {
			previewLen = total
		}
		preview := string(runes[:previewLen])
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

	if offset < 0 {
		offset = 0
	}
	if offset > total {
		offset = total
	}
	end := offset + readFileChunk
	if end > total {
		end = total
	}
	sliced := string(runes[offset:end])
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

// firstNLines は文字列の先頭n行を返す（承認プロンプトのプレビュー生成用）。
func firstNLines(s string, n int) string {
	lines := strings.Split(s, "\n")
	if len(lines) > n {
		lines = lines[:n]
	}
	return strings.Join(lines, "\n")
}

func toolWriteFile(args map[string]any) (string, error) {
	path := argString(args, "path")
	content := argString(args, "content")

	if boundaryErr := checkWorkerWriteBoundary(path); boundaryErr != "" {
		return boundaryErr, nil
	}
	preview := "  書き込み内容（先頭30行）:\n" + firstNLines(content, 30)
	if rejectErr := requestWriteApproval("write_file", path, preview); rejectErr != "" {
		return rejectErr, nil
	}

	warning := checkReadWarning(path)
	oldContent, hadOld := "", false
	if data, err := os.ReadFile(path); err == nil {
		oldContent = string(data)
		hadOld = true
	}

	if dir := filepath.Dir(path); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return "", err
		}
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return "", err
	}
	result := fmt.Sprintf("書き込み完了: %s (%d 文字)", path, len(content))
	if hadOld {
		result += "\n" + generateDiff(oldContent, content)
	}
	if note := syntaxCheckNote(path); note != "" {
		result += "\n" + note
	}
	return warning + result, nil
}

func toolEditFile(args map[string]any) (string, error) {
	path := argString(args, "path")
	oldString := argString(args, "old_string")
	newString := argString(args, "new_string")

	if boundaryErr := checkWorkerWriteBoundary(path); boundaryErr != "" {
		return boundaryErr, nil
	}
	preview := "  変更前（先頭15行）:\n" + firstNLines(oldString, 15) + "\n  変更後（先頭15行）:\n" + firstNLines(newString, 15)
	if rejectErr := requestWriteApproval("edit_file", path, preview); rejectErr != "" {
		return rejectErr, nil
	}

	warning := checkReadWarning(path)
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
		result := fmt.Sprintf("編集完了: %s  (%s%d 行差分, 計 %d 行)", path, sign, diffLines, strings.Count(newContent, "\n")+1)
		result += "\n" + generateDiff(content, newContent)
		if note := syntaxCheckNote(path); note != "" {
			result += "\n" + note
		}
		return warning + result, nil
	}
	if count > 1 {
		return "", fmt.Errorf("指定した文字列が %d 箇所に存在します（一意に特定できません）。前後の文脈をより多く含めた文字列を指定してください。", count)
	}
	notFoundPreview := oldString
	if len(notFoundPreview) > 120 {
		notFoundPreview = notFoundPreview[:120]
	}
	notFoundPreview = strings.ReplaceAll(notFoundPreview, "\n", "↵")
	return "", fmt.Errorf("指定された 'old_string' がファイル内に見つかりません: %s\n検索対象（先頭120文字）: %s\ngrep_codebase や smart_read で現在のファイル内容を確認し、正確な文字列で再実行してください。", path, notFoundPreview)
}

// toolPatchFile はedit_fileより緩いマッチを試みる。
// Python版のdifflib.SequenceMatcherによる類似ブロック探索(3段目)は
// フェーズ2の本バッチでは簡略化のため未移植（1: 完全一致、2: インデント
// 正規化ファジーマッチの2段のみ）。
func toolPatchFile(args map[string]any) (string, error) {
	path := argString(args, "path")
	search := argString(args, "search")
	replace := argString(args, "replace")

	if boundaryErr := checkWorkerWriteBoundary(path); boundaryErr != "" {
		return boundaryErr, nil
	}
	preview := "  検索文字列（先頭15行）:\n" + firstNLines(search, 15) + "\n  置換文字列（先頭15行）:\n" + firstNLines(replace, 15)
	if rejectErr := requestWriteApproval("patch_file", path, preview); rejectErr != "" {
		return rejectErr, nil
	}

	warning := checkReadWarning(path)
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
		result := fmt.Sprintf("編集完了（完全一致）: %s  (%s%d 行差分)", path, sign, diffLines)
		result += "\n" + generateDiff(content, newContent)
		if note := syntaxCheckNote(path); note != "" {
			result += "\n" + note
		}
		return warning + result, nil
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
		newContent := strings.Join(newLines, "\n") + trailing
		if err := os.WriteFile(path, []byte(newContent), 0o644); err != nil {
			return "", err
		}
		diffLines := strings.Count(reIndented, "\n") - n + 1
		sign := ""
		if diffLines >= 0 {
			sign = "+"
		}
		result := fmt.Sprintf("編集完了（インデント許容マッチ）: %s  (%s%d 行差分, indent_delta=%+d)", path, sign, diffLines, indentDelta)
		result += "\n" + generateDiff(content, newContent)
		if note := syntaxCheckNote(path); note != "" {
			result += "\n" + note
		}
		return warning + result, nil
	}
	if len(matches) > 1 {
		return "", fmt.Errorf("検索ブロックが %d 箇所にマッチします（一意に特定できません）。", len(matches))
	}

	// 3. 類似ブロック探索（Python版 difflib.SequenceMatcher の移植）。
	// 一致度が高い箇所を見つけても自動修正はしない（誤書き込み防止）。
	// あくまでエラーメッセージに近似箇所のヒントを添えるだけ。
	sKey := nonEmptyTrimmedLines(sLines)
	bestRatio := 0.0
	bestI := -1
	bestN := n
	const fuzzyThreshold = 0.85
	minWin := n - 2
	if minWin < 1 {
		minWin = 1
	}
	for win := minWin; win <= n+2; win++ {
		for i := 0; i+win <= len(contentLines); i++ {
			bKey := nonEmptyTrimmedLines(contentLines[i : i+win])
			ratio := sequenceRatio(sKey, bKey)
			if ratio > bestRatio {
				bestRatio = ratio
				bestI = i
				bestN = win
			}
		}
	}

	if bestRatio >= fuzzyThreshold && bestI >= 0 {
		previewLines := bestN
		if previewLines > 10 {
			previewLines = 10
		}
		blockPreview := strings.Join(contentLines[bestI:bestI+previewLines], "\n")
		return "", fmt.Errorf(
			"完全一致が見つかりません（類似度 %.2f、行 %d–%d）。\n"+
				"誤書き込みを防ぐため自動修正しません。\n"+
				"read_file で内容を確認し、正確な文字列を指定してください。\n"+
				"近似箇所（先頭10行）:\n%s",
			bestRatio, bestI+1, bestI+bestN, blockPreview)
	}

	notFoundPreview := search
	if len(notFoundPreview) > 120 {
		notFoundPreview = notFoundPreview[:120]
	}
	notFoundPreview = strings.ReplaceAll(notFoundPreview, "\n", "↵")
	hint := ""
	if bestRatio > 0 {
		hint = fmt.Sprintf("\n最近似ブロック類似度: %.2f（行 %d–%d）", bestRatio, bestI+1, bestI+bestN)
	}
	return "", fmt.Errorf("指定された検索文字列がファイル内に見つかりません: %s\n検索対象: %s...%s\nread_file で現在の内容を確認し、正確な（特にインデントや改行を含む）文字列を指定してください。", path, notFoundPreview, hint)
}

// nonEmptyTrimmedLines は各行をtrimし、空行を除いたスライスを返す
// （Python版 `[l.strip() for l in lines if l.strip()]` の移植）。
func nonEmptyTrimmedLines(lines []string) []string {
	out := make([]string, 0, len(lines))
	for _, l := range lines {
		t := strings.TrimSpace(l)
		if t != "" {
			out = append(out, t)
		}
	}
	return out
}

// sequenceRatio はdifflib.SequenceMatcher.ratio()の簡易近似を返す
// （2*M/T、M=LCSによる一致要素数、T=両者の要素数合計）。difflibの実際の
// アルゴリズム（junk検出込みの再帰的最長一致ブロック探索）とは厳密には
// 異なるが、あいまい検索の「近さの目安」としては十分機能する。
func sequenceRatio(a, b []string) float64 {
	t := len(a) + len(b)
	if t == 0 {
		return 1.0
	}
	m := lcsLength(a, b)
	return 2.0 * float64(m) / float64(t)
}

// lcsLength は2つの文字列スライスの最長共通部分列(LCS)の長さを返す。
func lcsLength(a, b []string) int {
	n, m := len(a), len(b)
	if n == 0 || m == 0 {
		return 0
	}
	prev := make([]int, m+1)
	cur := make([]int, m+1)
	for i := 1; i <= n; i++ {
		for j := 1; j <= m; j++ {
			if a[i-1] == b[j-1] {
				cur[j] = prev[j-1] + 1
			} else if prev[j] >= cur[j-1] {
				cur[j] = prev[j]
			} else {
				cur[j] = cur[j-1]
			}
		}
		prev, cur = cur, prev
	}
	return prev[m]
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
		// focusは自由入力なので正規表現メタ文字はエスケープし、リテラル部分一致として扱う。
		out, found, _ := grepInFile(text, regexp.QuoteMeta(focus), contextLines, false)
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
