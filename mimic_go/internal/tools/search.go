package tools

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
)

var grepExcludeDirs = map[string]bool{
	".git": true, "node_modules": true, ".venv": true, "venv": true,
	"__pycache__": true, ".idea": true, ".vscode": true,
}

func registerSearchTools(r *Registry) {
	r.Register("grep_codebase",
		"パターン検索。pathを指定するとそのファイル内検索、directoryを指定するとコードベース全体を再帰検索する。read_fileより先に試すこと。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"pattern":       map[string]any{"type": "string", "description": "検索する文字列"},
				"path":          map[string]any{"type": "string", "description": "単一ファイル検索時のパス（指定するとファイル内検索モード）"},
				"directory":     map[string]any{"type": "string", "description": "再帰検索対象ディレクトリ（pathが未指定の場合に使用、デフォルト: .）"},
				"ignore_case":   map[string]any{"type": "boolean", "description": "大文字小文字を無視する（デフォルトfalse）", "default": false},
				"context_lines": map[string]any{"type": "integer", "description": "マッチ行の前後に表示する行数（ファイル内検索時のみ有効、デフォルト3）", "default": 3},
				"max_results":   map[string]any{"type": "integer", "description": "最大表示件数（再帰検索時のみ有効、デフォルト50）", "default": 50},
			},
			"required": []string{"pattern"},
		},
		toolGrepCodebase)

	r.Register("get_repo_map",
		"プロジェクトのディレクトリ構造と.goファイルの関数・型構成をツリー状に取得する。不明なプロジェクト構造を把握するのに最適。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path": map[string]any{"type": "string", "description": "構造を取得するルートディレクトリ（デフォルト: .）", "default": "."},
			},
		},
		toolGetRepoMap)
}

// grepInFile は1ファイルの内容から pattern を含む行を前後 contextLines 行つきで探す。
func grepInFile(text, pattern string, contextLines int, ignoreCase bool) (string, bool) {
	lines := strings.Split(text, "\n")
	needle := pattern
	if ignoreCase {
		needle = strings.ToLower(needle)
	}
	var matchedIdx []int
	for i, l := range lines {
		hay := l
		if ignoreCase {
			hay = strings.ToLower(hay)
		}
		if strings.Contains(hay, needle) {
			matchedIdx = append(matchedIdx, i)
		}
	}
	if len(matchedIdx) == 0 {
		return "", false
	}
	shown := make(map[int]bool)
	var out strings.Builder
	lastPrinted := -1
	for _, idx := range matchedIdx {
		start := idx - contextLines
		if start < 0 {
			start = 0
		}
		end := idx + contextLines
		if end >= len(lines) {
			end = len(lines) - 1
		}
		if lastPrinted >= 0 && start > lastPrinted+1 {
			out.WriteString("--\n")
		}
		for i := start; i <= end; i++ {
			if shown[i] {
				continue
			}
			shown[i] = true
			marker := "-"
			if i == idx {
				marker = ":"
			}
			fmt.Fprintf(&out, "%d%s%s\n", i+1, marker, lines[i])
			lastPrinted = i
		}
	}
	return strings.TrimRight(out.String(), "\n"), true
}

func toolGrepCodebase(args map[string]any) (string, error) {
	pattern := argString(args, "pattern")
	path := argString(args, "path")
	directory := argString(args, "directory")
	if directory == "" {
		directory = "."
	}
	ignoreCase := argBool(args, "ignore_case", false)
	contextLines := argInt(args, "context_lines", 3)
	maxResults := argInt(args, "max_results", 50)

	if path != "" {
		data, err := os.ReadFile(path)
		if err != nil {
			return "", err
		}
		out, found := grepInFile(string(data), pattern, contextLines, ignoreCase)
		if !found {
			return fmt.Sprintf("「%s」は %s に見つかりませんでした。", pattern, path), nil
		}
		lines := strings.Count(out, "\n") + 1
		return fmt.Sprintf("[grep_codebase] %s / pattern=%q / %d行マッチ\n%s", path, pattern, lines, out), nil
	}

	var results []string
	needle := pattern
	err := filepath.WalkDir(directory, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if grepExcludeDirs[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		if len(results) >= maxResults {
			return nil
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return nil
		}
		for i, line := range strings.Split(string(data), "\n") {
			hay := line
			hayNeedle := needle
			if ignoreCase {
				hay = strings.ToLower(hay)
				hayNeedle = strings.ToLower(hayNeedle)
			}
			if strings.Contains(hay, hayNeedle) {
				trimmed := strings.TrimSpace(line)
				if len(trimmed) > 200 {
					trimmed = trimmed[:200]
				}
				results = append(results, fmt.Sprintf("%s:%d: %s", p, i+1, trimmed))
				if len(results) >= maxResults {
					break
				}
			}
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	if len(results) == 0 {
		return fmt.Sprintf("「%s」は %s 内に見つかりませんでした。", pattern, directory), nil
	}
	out := strings.Join(results, "\n")
	suffix := "\n（各行200文字で打ち切り）"
	if len(results) >= maxResults {
		suffix = fmt.Sprintf("\n（上位%d件を表示、各行200文字で打ち切り）", maxResults)
	}
	return fmt.Sprintf("[grep_codebase] pattern=%q / %d件ヒット\n%s%s", pattern, len(results), out, suffix), nil
}

// toolGetRepoMap はPython版のast解析相当をgo/parserで行う。
// Pythonのクラス+メソッド構造とは異なりGoにはクラスがないため、
// トップレベルのfunc/type宣言を列挙する形に置き換えている。
func toolGetRepoMap(args map[string]any) (string, error) {
	root := argString(args, "path")
	if root == "" {
		root = "."
	}
	if _, err := os.Stat(root); err != nil {
		return "", err
	}

	var lines []string
	absRoot, _ := filepath.Abs(root)
	lines = append(lines, fmt.Sprintf("RepoMap: %s", absRoot))

	totalLen := len(lines[0])
	err := filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err != nil || p == root {
			return nil
		}
		if d.IsDir() && grepExcludeDirs[d.Name()] {
			return filepath.SkipDir
		}
		rel, _ := filepath.Rel(root, p)
		depth := len(strings.Split(rel, string(filepath.Separator)))
		indent := strings.Repeat("  ", depth-1)
		prefix := indent + "└── "

		info := ""
		if !d.IsDir() && strings.HasSuffix(d.Name(), ".go") {
			info = goFileSymbols(p)
		}
		suffix := ""
		if d.IsDir() {
			suffix = "/"
		}
		line := fmt.Sprintf("%s%s%s%s", prefix, d.Name(), suffix, info)
		lines = append(lines, line)
		totalLen += len(line) + 1
		if totalLen > 20000 {
			lines = append(lines, "... (出力制限のため省略)")
			return filepath.SkipAll
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	return strings.Join(lines, "\n"), nil
}

func goFileSymbols(path string) string {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, path, nil, parser.SkipObjectResolution)
	if err != nil {
		return ""
	}
	var defs []string
	for _, decl := range f.Decls {
		switch d := decl.(type) {
		case *ast.FuncDecl:
			defs = append(defs, fmt.Sprintf("func %s(...)", d.Name.Name))
		case *ast.GenDecl:
			for _, spec := range d.Specs {
				if ts, ok := spec.(*ast.TypeSpec); ok {
					defs = append(defs, fmt.Sprintf("type %s", ts.Name.Name))
				}
			}
		}
		if len(defs) >= 10 {
			break
		}
	}
	if len(defs) == 0 {
		return ""
	}
	suffix := ""
	if len(defs) > 10 {
		defs = defs[:10]
		suffix = ", ..."
	}
	return " [" + strings.Join(defs, ", ") + suffix + "]"
}
