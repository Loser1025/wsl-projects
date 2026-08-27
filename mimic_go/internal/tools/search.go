package tools

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// grepExcludeDirs はgrep_codebaseの再帰検索から除外するディレクトリ名
// （Python版 tools_linux.py::_GREP_EXCLUDE_DIRS を踏襲）。
var grepExcludeDirs = map[string]bool{
	"node_modules": true, ".git": true, "__pycache__": true, ".venv": true, "venv": true, "env": true,
	"dist": true, "build": true, ".next": true, ".nuxt": true, ".cache": true, "coverage": true,
	".mypy_cache": true, ".pytest_cache": true, ".tox": true, "target": true, "vendor": true,
}

// grepExcludeFilePatterns はgrep_codebaseの再帰検索から除外するファイル名パターン
// （Python版 _GREP_EXCLUDE_FILES を踏襲。filepath.Match形式）。
var grepExcludeFilePatterns = []string{
	"*.min.js", "*.min.css", "*.map", "*.bundle.js", "*.lock", "package-lock.json",
}

func grepFileExcluded(name string) bool {
	for _, pat := range grepExcludeFilePatterns {
		if ok, _ := filepath.Match(pat, name); ok {
			return true
		}
	}
	return false
}

// compileGrepPattern はPythonのgrep(BRE/ERE寄り)相当としてGoのregexpでコンパイルする。
// ignoreCaseがtrueなら大文字小文字を無視するフラグを前置する。
func compileGrepPattern(pattern string, ignoreCase bool) (*regexp.Regexp, error) {
	if ignoreCase {
		pattern = "(?i)" + pattern
	}
	return regexp.Compile(pattern)
}

func registerSearchTools(r *Registry) {
	r.Register("grep_codebase",
		"パターン検索。pathを指定するとそのファイル内検索、directoryを指定するとコードベース全体を再帰検索する。read_fileより先に試すこと。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"pattern":       map[string]any{"type": "string", "description": "検索する正規表現パターン"},
				"path":          map[string]any{"type": "string", "description": "単一ファイル検索時のパス（指定するとファイル内検索モード）"},
				"directory":     map[string]any{"type": "string", "description": "再帰検索対象ディレクトリ（pathが未指定の場合に使用、デフォルト: .）"},
				"file_type":     map[string]any{"type": "string", "description": "拡張子でフィルタ（例: go, py。再帰検索時のみ有効）"},
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

// grepInFile は1ファイルの内容から pattern（正規表現）にマッチする行を
// 前後 contextLines 行つきで探す（Python版 grep -n -C の移植）。
func grepInFile(text, pattern string, contextLines int, ignoreCase bool) (string, bool, error) {
	re, err := compileGrepPattern(pattern, ignoreCase)
	if err != nil {
		return "", false, err
	}
	lines := strings.Split(text, "\n")
	var matchedIdx []int
	for i, l := range lines {
		if re.MatchString(l) {
			matchedIdx = append(matchedIdx, i)
		}
	}
	if len(matchedIdx) == 0 {
		return "", false, nil
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
	return strings.TrimRight(out.String(), "\n"), true, nil
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
	fileType := argString(args, "file_type")

	if path != "" {
		data, err := os.ReadFile(path)
		if err != nil {
			return "", err
		}
		out, found, err := grepInFile(string(data), pattern, contextLines, ignoreCase)
		if err != nil {
			return "", fmt.Errorf("正規表現が不正です: %w", err)
		}
		if !found {
			return fmt.Sprintf("「%s」は %s に見つかりませんでした。", pattern, path), nil
		}
		lines := strings.Count(out, "\n") + 1
		return fmt.Sprintf("[grep_codebase] %s / pattern=%q / %d行マッチ\n%s", path, pattern, lines, out), nil
	}

	re, err := compileGrepPattern(pattern, ignoreCase)
	if err != nil {
		return "", fmt.Errorf("正規表現が不正です: %w", err)
	}

	var results []string
	err = filepath.WalkDir(directory, func(p string, d os.DirEntry, err error) error {
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
		if grepFileExcluded(d.Name()) {
			return nil
		}
		if fileType != "" && !strings.HasSuffix(d.Name(), "."+fileType) {
			return nil
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return nil
		}
		for i, line := range strings.Split(string(data), "\n") {
			if re.MatchString(line) {
				trimmed := strings.TrimSpace(line)
				if len(trimmed) > 300 {
					trimmed = trimmed[:300]
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
	suffix := "\n（各行300文字で打ち切り）"
	if len(results) >= maxResults {
		suffix = fmt.Sprintf("\n（上位%d件を表示、各行300文字で打ち切り）", maxResults)
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
