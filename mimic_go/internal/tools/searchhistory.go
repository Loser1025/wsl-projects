package tools

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// search_historyツール（Python版 tools.py::search_history /
// commands.py::_search_sessions,_parse_session_file の移植）。過去セッションの
// JSONLログを検索し、ユーザー入力と回答のペアを返す。query=""なら最新順に
// 全ターンのサマリを返す（作業再開時の一次情報源）。

var sessionsDirForTool string

// SetSessionsDirForTool はDirector（TUI/非対話モード）起動時に一度だけ呼び出す。
func SetSessionsDirForTool(dir string) {
	sessionsDirForTool = dir
}

func registerSearchHistoryTools(r *Registry) {
	r.Register("search_history",
		"過去のセッションログを検索し、ユーザー入力と回答を返す。以前のタスクの結果・知見を参照したいときや、"+
			"作業を再開したいときに使う。query=''（空文字）にすると最新セッションから順に全件サマリを返す"+
			"（作業再開時はまずこれを使うこと）。キーワードを指定すると内容で絞り込む。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"query":       map[string]any{"type": "string", "description": "検索キーワード（空文字で最新N件をすべて返す）", "default": ""},
				"max_results": map[string]any{"type": "integer", "description": "最大件数（デフォルト10）", "default": 10},
			},
		},
		toolSearchHistory)
}

type sessionTurn struct {
	User   string
	Answer string
}

func loadSessionEntries(path string) []map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var entries []map[string]any
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var e map[string]any
		if err := json.Unmarshal([]byte(line), &e); err == nil {
			entries = append(entries, e)
		}
	}
	return entries
}

func entryStr(e map[string]any, key string) string {
	if v, ok := e[key].(string); ok {
		return v
	}
	return ""
}

// parseSessionTurns はセッションJSONLをuser_input/final_answerのペア単位に分解する
// （Python版 _parse_session_file の移植。tool_call等の中間イベントは無視する）。
func parseSessionTurns(entries []map[string]any) (model string, turns []sessionTurn) {
	var current *sessionTurn
	for _, e := range entries {
		switch entryStr(e, "type") {
		case "session_start":
			model = entryStr(e, "model")
		case "user_input":
			if current != nil {
				turns = append(turns, *current)
			}
			current = &sessionTurn{User: entryStr(e, "content")}
		case "final_answer":
			if current != nil {
				current.Answer = entryStr(e, "content")
			}
		}
	}
	if current != nil {
		turns = append(turns, *current)
	}
	return model, turns
}

func truncateRunes(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func toolSearchHistory(args map[string]any) (string, error) {
	query := strings.TrimSpace(argString(args, "query"))
	maxResults := argInt(args, "max_results", 10)
	if maxResults <= 0 {
		maxResults = 10
	}

	if sessionsDirForTool == "" {
		return "セッションログがまだありません。", nil
	}
	files, _ := filepath.Glob(filepath.Join(sessionsDirForTool, "*.jsonl"))
	if len(files) == 0 {
		return "セッションログがまだありません。", nil
	}
	sort.Sort(sort.Reverse(sort.StringSlice(files)))

	if query == "" {
		var lines []string
		lines = append(lines, fmt.Sprintf("[search_history: 最新セッション一覧  %d ファイル]\n", len(files)))
		shown := 0
		for _, f := range files {
			entries := loadSessionEntries(f)
			if len(entries) == 0 {
				continue
			}
			model, turns := parseSessionTurns(entries)
			lines = append(lines, fmt.Sprintf("=== %s  (%d ターン  %s) ===", strings.TrimSuffix(filepath.Base(f), ".jsonl"), len(turns), model))
			for _, t := range turns {
				userPreview := strings.ReplaceAll(truncateRunes(t.User, 120), "\n", " ")
				ansPreview := strings.ReplaceAll(truncateRunes(t.Answer, 120), "\n", " ")
				lines = append(lines, "  Q: "+userPreview)
				if ansPreview != "" {
					lines = append(lines, "  A: "+ansPreview)
				}
				shown++
				if shown >= maxResults {
					lines = append(lines, fmt.Sprintf("\n…（%d件表示済み。さらに必要なら max_results を増やすか query で絞り込む）", maxResults))
					return strings.Join(lines, "\n"), nil
				}
			}
			lines = append(lines, "")
		}
		return strings.Join(lines, "\n"), nil
	}

	// キーワード検索
	type hit struct {
		file, user, result string
	}
	var hits []hit
	q := strings.ToLower(query)
	for _, f := range files {
		if len(hits) >= maxResults {
			break
		}
		_, turns := parseSessionTurns(loadSessionEntries(f))
		for _, t := range turns {
			if strings.Contains(strings.ToLower(t.User), q) || strings.Contains(strings.ToLower(t.Answer), q) {
				hits = append(hits, hit{file: strings.TrimSuffix(filepath.Base(f), ".jsonl"), user: t.User, result: t.Answer})
				if len(hits) >= maxResults {
					break
				}
			}
		}
	}
	if len(hits) == 0 {
		return fmt.Sprintf("「%s」に一致するログが見つかりませんでした。\nヒント: query=''で最新セッションの全ターンを確認できます。", query), nil
	}
	var lines []string
	lines = append(lines, fmt.Sprintf("[search_history: %s] %d件ヒット\n", query, len(hits)))
	for i, h := range hits {
		lines = append(lines, fmt.Sprintf("--- [%d] %s", i+1, h.file))
		lines = append(lines, "User: "+h.user)
		if h.result != "" {
			lines = append(lines, "Result: "+h.result)
		}
		lines = append(lines, "")
	}
	return strings.Join(lines, "\n"), nil
}
