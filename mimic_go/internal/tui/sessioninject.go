package tui

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"mimic/internal/llm"
)

// searchSelectionState は/searchのヒット一覧提示後、番号選択/all/nの入力を待つ状態。
type searchSelectionState struct {
	query string
	hits  []searchHit
}

// sessionInjectState は/sessionsの詳細表示後、y/nの確認入力を待つ状態。
type sessionInjectState struct {
	session parsedSession
}

// セッションJSONLのパース・検索・コンテキスト注入テキスト生成
// （Python版 commands.py::_search_sessions/_parse_session_file/resolve_session/
// build_session_inject_text の移植。/search・/sessionsのヒット後コンテキスト
// 注入フローで使う）。

type sessionTurn struct {
	User   string
	TS     string
	Tools  []string
	Answer string
}

type parsedSession struct {
	File     string // 拡張子なしのファイル名（Python版のPath.stem相当）
	Model    string
	Provider string
	Turns    []sessionTurn
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

func stem(path string) string {
	base := filepath.Base(path)
	return strings.TrimSuffix(base, filepath.Ext(base))
}

// parseSessionFile はJSONLセッションファイルをパースしてターン情報を返す
// （Python版 _parse_session_file の移植）。
func parseSessionFile(path string) (parsedSession, bool) {
	entries := loadSessionEntries(path)
	if entries == nil {
		return parsedSession{}, false
	}
	sess := parsedSession{File: stem(path)}
	var current *sessionTurn
	for _, e := range entries {
		t, _ := e["type"].(string)
		switch t {
		case "session_start":
			sess.Model, _ = e["model"].(string)
			sess.Provider, _ = e["provider"].(string)
		case "user_input":
			if current != nil {
				sess.Turns = append(sess.Turns, *current)
			}
			content, _ := e["content"].(string)
			ts, _ := e["ts"].(string)
			current = &sessionTurn{User: content, TS: ts}
		case "action":
			if current != nil {
				toolName, _ := e["tool"].(string)
				if toolName != "" && !containsStr(current.Tools, toolName) {
					current.Tools = append(current.Tools, toolName)
				}
			}
		case "final_answer":
			if current != nil {
				current.Answer, _ = e["content"].(string)
			}
		}
	}
	if current != nil {
		sess.Turns = append(sess.Turns, *current)
	}
	return sess, true
}

func containsStr(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// searchHit は/searchの1件のヒット（ユーザー発言＋直後のfinal_answerのペア）。
type searchHit struct {
	File          string
	TS            string
	UserPreview   string
	ResultPreview string
	FullUser      string
	FullResult    string
}

// searchSessions はsessionsDir内の.jsonlを検索し、ヒットしたターンを返す
// （Python版 _search_sessions の移植）。
func searchSessions(sessionsDir, query string, maxResults int) []searchHit {
	files, _ := filepath.Glob(filepath.Join(sessionsDir, "*.jsonl"))
	sort.Sort(sort.Reverse(sort.StringSlice(files)))
	q := strings.ToLower(query)

	var hits []searchHit
	for _, f := range files {
		entries := loadSessionEntries(f)
		for i := 0; i < len(entries); i++ {
			e := entries[i]
			t, _ := e["type"].(string)
			if t != "user_input" {
				continue
			}
			userText, _ := e["content"].(string)
			answerText := ""
			for j := i + 1; j < len(entries); j++ {
				tj, _ := entries[j]["type"].(string)
				if tj == "user_input" {
					break
				}
				if tj == "final_answer" {
					answerText, _ = entries[j]["content"].(string)
					break
				}
			}
			if strings.Contains(strings.ToLower(userText), q) || strings.Contains(strings.ToLower(answerText), q) {
				ts, _ := e["ts"].(string)
				hits = append(hits, searchHit{
					File:          stem(f),
					TS:            ts,
					UserPreview:   truncateRunes(userText, 200),
					ResultPreview: truncateRunes(answerText, 300),
					FullUser:      userText,
					FullResult:    answerText,
				})
				if len(hits) >= maxResults {
					return hits
				}
			}
		}
	}
	return hits
}

func truncateRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

// resolveSession は番号またはファイル名の一部から、セッションを1件に絞り込む
// （Python版 resolve_session の移植）。戻り値は (該当セッション or nil, 複数ヒット時の候補リスト)。
func resolveSession(sessions []parsedSession, arg string) (*parsedSession, []parsedSession) {
	arg = strings.TrimSpace(arg)
	if n, err := strconv.Atoi(arg); err == nil {
		idx := n - 1
		if idx >= 0 && idx < len(sessions) {
			return &sessions[idx], nil
		}
		return nil, nil
	}
	var matched []parsedSession
	for _, s := range sessions {
		if strings.Contains(s.File, arg) {
			matched = append(matched, s)
		}
	}
	if len(matched) == 1 {
		return &matched[0], nil
	}
	return nil, matched
}

// buildSessionInjectText は選択したセッションの全ターン内容を、コンテキスト
// 注入用のテキストにまとめる（Python版 build_session_inject_text の移植）。
func buildSessionInjectText(s parsedSession) string {
	lines := []string{fmt.Sprintf("[過去セッションの参考情報（/sessions %s）]", s.File)}
	for i, turn := range s.Turns {
		lines = append(lines, fmt.Sprintf("\nTurn %d User: %s", i+1, turn.User))
		if len(turn.Tools) > 0 {
			lines = append(lines, "Tools: "+strings.Join(turn.Tools, ", "))
		}
		if turn.Answer != "" {
			lines = append(lines, "Answer: "+turn.Answer)
		}
	}
	return strings.Join(lines, "\n")
}

// buildSearchInjectText は選択した/search結果をコンテキスト注入用のテキストに
// まとめる（Python版 cmd_search::on_response内のinject_lines組み立ての移植）。
func buildSearchInjectText(query string, hits []searchHit) string {
	lines := []string{fmt.Sprintf("[過去セッションの参考情報（/search %s）]", query)}
	for _, h := range hits {
		lines = append(lines, fmt.Sprintf("\nUser: %s", h.FullUser))
		if h.FullResult != "" {
			lines = append(lines, "Result: "+h.FullResult)
		}
	}
	return strings.Join(lines, "\n")
}

// applySearchSelection は/searchの選択応答（番号カンマ区切り/all/n）を処理し、
// 選択されたヒットを会話履歴へ注入する（Python版 app.py::_cmd_search::on_response
// の移植）。
func (m *Model) applySearchSelection(sel *searchSelectionState, resp string) {
	if resp == "" || resp == "n" {
		return
	}
	var selected []searchHit
	if resp == "all" {
		selected = sel.hits
	} else {
		for _, tok := range strings.Split(resp, ",") {
			tok = strings.TrimSpace(tok)
			if n, err := strconv.Atoi(tok); err == nil {
				idx := n - 1
				if idx >= 0 && idx < len(sel.hits) {
					selected = append(selected, sel.hits[idx])
				}
			}
		}
	}
	if len(selected) == 0 {
		return
	}
	injectText := buildSearchInjectText(sel.query, selected)
	m.history = append(m.history,
		llm.Message{Role: "user", Content: injectText},
		llm.Message{Role: "assistant", Content: "了解しました。参考情報を確認しました。"})
	m.log = append(m.log, fmt.Sprintf("  ✓ %d 件をコンテキストに注入しました。", len(selected)))
	m.openLine = false
	m.viewport.SetContent(m.renderLog())
	m.viewport.GotoBottom()
}

// applySessionInject は/sessionsの注入確認応答（y/n）を処理する
// （Python版 app.py::_cmd_sessions::on_response の移植）。
func (m *Model) applySessionInject(inj *sessionInjectState, resp string) {
	if resp != "y" && resp != "yes" {
		return
	}
	injectText := buildSessionInjectText(inj.session)
	m.history = append(m.history,
		llm.Message{Role: "user", Content: injectText},
		llm.Message{Role: "assistant", Content: "了解しました。参考情報を確認しました。"})
	m.log = append(m.log, "  ✓ コンテキストに注入しました。")
	m.openLine = false
	m.viewport.SetContent(m.renderLog())
	m.viewport.GotoBottom()
}

// cmdSearch は`/search <query>`を処理する（Python版 app.py::_cmd_search の移植）。
// ヒット一覧をログへ出力し、番号選択/all/nの入力待ち状態にする。
func (m Model) cmdSearch(text, query string) Model {
	query = strings.TrimSpace(query)
	if query == "" {
		return m.appendCommandLog(text, "使い方: /search <検索ワード>")
	}
	sessionsDir := filepath.Join(m.cwd, ".mimic", "sessions")
	hits := searchSessions(sessionsDir, query, 5)
	if len(hits) == 0 {
		return m.appendCommandLog(text, fmt.Sprintf("「%s」に一致するログが見つかりませんでした。", query))
	}

	var b strings.Builder
	fmt.Fprintf(&b, "🔍 「%s」 — %d 件ヒット\n", query, len(hits))
	for i, h := range hits {
		fmt.Fprintf(&b, "  [%d] %s  %s\n", i+1, h.File, h.TS)
		fmt.Fprintf(&b, "    Q: %s\n", truncateRunes(h.UserPreview, 100))
		if h.ResultPreview != "" {
			fmt.Fprintf(&b, "    A: %s\n", truncateRunes(h.ResultPreview, 150))
		}
	}
	b.WriteString("コンテキストに注入しますか？ [番号をカンマ区切り / all / n]")
	m = m.appendCommandLog(text, b.String())
	m.pendingSearchSelection = &searchSelectionState{query: query, hits: hits}
	return m
}

// cmdSessions は`/sessions [番号|ファイル名の一部]`を処理する
// （Python版 app.py::_cmd_sessions の移植）。
func (m Model) cmdSessions(text, arg string) Model {
	sessionsDir := filepath.Join(m.cwd, ".mimic", "sessions")
	sessions := loadAllSessions(sessionsDir)
	if len(sessions) == 0 {
		return m.appendCommandLog(text, "セッション履歴はありません。")
	}

	session, ambiguous := resolveSession(sessions, arg)
	if session == nil {
		if len(ambiguous) > 0 {
			var b strings.Builder
			fmt.Fprintf(&b, "%d 件ヒットしました。番号で絞り込んでください:\n", len(ambiguous))
			for i, s := range ambiguous {
				fmt.Fprintf(&b, "  [%d] %s\n", i+1, s.File)
			}
			return m.appendCommandLog(text, b.String())
		}
		if _, err := strconv.Atoi(strings.TrimSpace(arg)); err == nil {
			return m.appendCommandLog(text, fmt.Sprintf("番号 %s のセッションが見つかりません（1〜%d）。", strings.TrimSpace(arg), len(sessions)))
		}
		return m.appendCommandLog(text, fmt.Sprintf("「%s」に一致するセッションが見つかりません。", strings.TrimSpace(arg)))
	}

	var b strings.Builder
	fmt.Fprintf(&b, "セッション詳細  %s\n", session.File)
	fmt.Fprintf(&b, "モデル: %s  /  %d ターン\n", nonEmptyOr(session.Model, "不明"), len(session.Turns))
	for i, turn := range session.Turns {
		fmt.Fprintf(&b, "  [Turn %d] %s\n", i+1, turn.TS)
		fmt.Fprintf(&b, "    User: %s\n", truncateRunes(turn.User, 200))
		if len(turn.Tools) > 0 {
			fmt.Fprintf(&b, "    Tools: %s\n", strings.Join(turn.Tools, ", "))
		}
		if turn.Answer != "" {
			fmt.Fprintf(&b, "    Answer: %s\n", truncateRunes(turn.Answer, 300))
		}
	}
	b.WriteString("この内容をコンテキストに注入しますか？ [y/n]")
	m = m.appendCommandLog(text, b.String())
	m.pendingSessionInject = &sessionInjectState{session: *session}
	return m
}

func nonEmptyOr(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

// loadAllSessions はsessionsDir内の全セッションを新しい順（ファイル名降順）で
// パースして返す（Python版 `sorted(sd.glob("*.jsonl"), reverse=True)` の移植）。
func loadAllSessions(sessionsDir string) []parsedSession {
	files, _ := filepath.Glob(filepath.Join(sessionsDir, "*.jsonl"))
	sort.Sort(sort.Reverse(sort.StringSlice(files)))
	var out []parsedSession
	for _, f := range files {
		if s, ok := parseSessionFile(f); ok {
			out = append(out, s)
		}
	}
	return out
}
