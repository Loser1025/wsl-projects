package tui

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"charm.land/lipgloss/v2"
)

// 通常ツール呼び出しの表示（renderLog経由でチャットログに流れる）。
// 委任系ツールはdelegation.goのrenderDelegationCallがカード状に整形するが、
// read_file/grep_codebase等の頻繁に呼ばれるツールは1行のまま、生JSONの
// 垂れ流しではなく主要な引数だけを読みやすく抜き出して表示する。

// alwaysApprovedTools はTUI内で必ず承認ダイアログ（renderApprovalBox/
// renderHostExecApprovalBox）が表示されるツール名の集合
// （NewModelがtools.SetWriteApprovalHandler/SetHostExecApprovalHandlerを
// 無条件で登録しており、auto承認でスキップされる分岐が無いため）。
// 承認ボックス自体にツール名・パス（またはコマンド）・変更内容プレビューが
// 含まれるため、この直前に出すツール呼び出し行は完全に重複する。
// そのため、これらのツールはmodel.go側でツール呼び出し行自体を省略する。
var alwaysApprovedTools = map[string]bool{
	"write_file":       true,
	"edit_file":        true,
	"patch_file":       true,
	"run_host_command": true,
}

// toolCallMeta はツールごとの表示ルール。
//   - primary: 見出しに出す主要引数キー（先頭から順に、値がある最初のもの)
//     を優先的に採用するのではなく、指定された全キーを順に連結して表示する。
//   - secondary: 値がデフォルト値/ゼロ値でなければ "key=value" として補足表示する。
//   - contentOnly: 生の内容は表示せず、文字数だけを示す（content/old_string等、
//     長文になり得るうえ表示しても一目では読めないフィールド用）。
type toolCallMeta struct {
	icon        string
	primary     []string
	secondary   []string
	contentOnly []string
}

var toolCallMetaByName = map[string]toolCallMeta{
	"read_file":            {icon: "📖", primary: []string{"path"}, secondary: []string{"offset"}},
	"write_file":           {icon: "✏️", primary: []string{"path"}, contentOnly: []string{"content"}},
	"edit_file":            {icon: "✏️", primary: []string{"path"}, contentOnly: []string{"old_string", "new_string"}},
	"patch_file":           {icon: "✏️", primary: []string{"path"}, contentOnly: []string{"search", "replace"}},
	"file_info":            {icon: "ℹ️", primary: []string{"path"}},
	"smart_read":           {icon: "🔍", primary: []string{"path"}, secondary: []string{"focus", "context_lines"}},
	"list_directory":       {icon: "📁", primary: []string{"path"}},
	"grep_codebase":        {icon: "🔎", primary: []string{"pattern"}, secondary: []string{"path", "directory", "file_type", "ignore_case", "context_lines", "max_results"}},
	"get_repo_map":         {icon: "🗺️", primary: []string{"path"}},
	"run_bash":             {icon: "💻", primary: []string{"command"}, secondary: []string{"working_directory", "timeout", "shell"}},
	"run_pipeline":         {icon: "💻", primary: []string{"command"}, secondary: []string{"working_directory", "timeout", "max_lines"}},
	"run_host_command":     {icon: "⚠️", primary: []string{"command"}, secondary: []string{"reason", "working_directory", "timeout"}},
	"read_tool_cache":      {icon: "📄", primary: []string{"cache_key"}, secondary: []string{"offset"}},
	"search_history":       {icon: "🕘", primary: []string{"query"}, secondary: []string{"max_results"}},
	"load_skill":           {icon: "🧩", primary: []string{"name"}},
	"list_skills":          {icon: "🧩"},
	"update_scratchpad":    {icon: "📝", contentOnly: []string{"content"}},
	"web_search":           {icon: "🌐", primary: []string{"query"}, secondary: []string{"max_results"}},
	"fetch_webpage":        {icon: "🌐", primary: []string{"url"}, secondary: []string{"max_chars"}},
	"browser_navigate":     {icon: "🖥️", primary: []string{"url"}, secondary: []string{"wait_ms"}},
	"browser_click":        {icon: "🖱️", primary: []string{"selector"}, secondary: []string{"wait_ms"}},
	"browser_type":         {icon: "⌨️", primary: []string{"selector"}, secondary: []string{"clear_first"}, contentOnly: []string{"text"}},
	"browser_get_text":     {icon: "🖥️", primary: []string{"selector"}, secondary: []string{"max_chars"}},
	"browser_screenshot":   {icon: "📸", primary: []string{"path"}},
	"browser_close":        {icon: "🖥️"},
	"get_delegation_trace": {icon: "🔗", primary: []string{"trace_id"}, secondary: []string{"max_steps"}},
}

// toolCallFallbackKeys はtoolCallMetaByNameに無い（MCP経由等の未知の）ツール向けに
// 見出しへ採用を試みる、よくある識別子キー名。
var toolCallFallbackKeys = []string{"path", "query", "url", "pattern", "name", "command", "selector", "cache_key", "trace_id"}

const toolCallFieldMax = 70

// renderToolCallLine は通常ツール呼び出しを、生JSONの垂れ流しではなく
// 主要引数を抜き出した1行に整形する（委任系ツールはrenderDelegationCallが別途扱う）。
func renderToolCallLine(name, argsJSON string) string {
	var args map[string]any
	_ = json.Unmarshal([]byte(argsJSON), &args)

	meta, known := toolCallMetaByName[name]
	icon := "🔧"
	if known && meta.icon != "" {
		icon = meta.icon
	}

	primaryKeys := meta.primary
	if len(primaryKeys) == 0 {
		for _, k := range toolCallFallbackKeys {
			if dArgString(args, k) != "" {
				primaryKeys = []string{k}
				break
			}
		}
	}
	var primaryVals []string
	for _, k := range primaryKeys {
		if v := dArgString(args, k); v != "" {
			primaryVals = append(primaryVals, truncateField(v, toolCallFieldMax))
		}
	}
	// 未知ツールかつ既知の識別子キーにも一致しない場合、最後の手段として
	// 最初に見つかった短い文字列値を "key: value" 形式で採用する。
	if len(primaryVals) == 0 && len(args) > 0 {
		keys := make([]string, 0, len(args))
		for k := range args {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			if s, ok := args[k].(string); ok && s != "" && len(s) <= toolCallFieldMax {
				primaryVals = append(primaryVals, k+": "+s)
				break
			}
		}
	}

	nameColor := colCyan
	if name == "run_host_command" {
		nameColor = colAmber // ユーザー承認が必須の操作なので注意色にする
	}
	headline := icon + " " + name
	if len(primaryVals) > 0 {
		headline += "  " + strings.Join(primaryVals, " ")
	}
	line := "  → " + lipgloss.NewStyle().Foreground(nameColor).Render(headline)

	var trailer []string
	for _, k := range meta.secondary {
		v, present := args[k]
		if !present || isZeroish(v) {
			continue
		}
		trailer = append(trailer, fmt.Sprintf("%s=%v", k, v))
	}
	for _, k := range meta.contentOnly {
		if v := dArgString(args, k); v != "" {
			trailer = append(trailer, fmt.Sprintf("%s: %d字", k, len([]rune(v))))
		}
	}
	if len(trailer) > 0 {
		line += "  " + lipgloss.NewStyle().Foreground(colMuted).Render("("+strings.Join(trailer, ", ")+")")
	}
	return line
}

// isZeroish はfalse/0/空文字など、わざわざ表示するまでもないデフォルト値らしき
// 値かどうかを判定する（secondary引数を「LLMがデフォルトから変えた時だけ」表示するため）。
func isZeroish(v any) bool {
	switch x := v.(type) {
	case bool:
		return !x
	case float64:
		return x == 0
	case string:
		return x == ""
	default:
		return v == nil
	}
}
