package tui

import (
	"encoding/json"
	"fmt"
	"strings"

	"charm.land/lipgloss/v2"
)

// 委任系ツール呼び出しの表示（renderLog経由でチャットログに流れる）。
// internal/react/loop.go::delegationTools と対になるツール名一覧。
// tuiパッケージはreactパッケージに依存させたくない（表示専用の関心事のため）
// ので、ここで独立して保持する。

type delegationMeta struct {
	icon  string
	label string
}

var delegationMetaByTool = map[string]delegationMeta{
	"delegate_to_specialist":    {"🎭", "Specialist"},
	"delegate_to_team":          {"👥", "Team"},
	"delegate_to_worker":        {"🛠", "Worker"},
	"delegate_to_team_parallel": {"⚡", "Team(並列)"},
	"delegate_research":         {"🔎", "Research"},
	"continue_specialist":       {"↻", "Continue"},
}

const delegationFieldMax = 90

// delegationPendingStyle は委任カードの下に一時的に出す「実行中...」表示のスタイル
// （renderLog側でpendingDelegationIdxが未解決の間だけ付与する）。
var delegationPendingStyle = lipgloss.NewStyle().Foreground(colAmber)

// renderDelegationCall は委任系ツール呼び出しを、生JSONの切り詰めプレビューではなく
// role/task/権限レベルなどを抜き出した読みやすいカード状の表示に整形する。
// 委任系ツールでなければ空文字を返す（呼び出し側は従来のツール行にフォールバックする）。
func renderDelegationCall(name, argsJSON string) string {
	meta, ok := delegationMetaByTool[name]
	if !ok {
		return ""
	}
	var args map[string]any
	_ = json.Unmarshal([]byte(argsJSON), &args)

	badge, badgeStyle := delegationBadge(name, args)
	headerStyle := lipgloss.NewStyle().Bold(true).Foreground(colTitle)

	header := "  " + headerStyle.Render(fmt.Sprintf("⇒ %s %s委任", meta.icon, meta.label))
	if badge != "" {
		header += "  " + badgeStyle.Render("["+badge+"]")
	}
	lines := []string{header}

	labelStyle := lipgloss.NewStyle().Foreground(colMuted)
	valueStyle := lipgloss.NewStyle().Foreground(colText)
	field := func(label, value string) {
		value = truncateField(value, delegationFieldMax)
		if value == "" {
			return
		}
		lines = append(lines, "      "+labelStyle.Render(label+": ")+valueStyle.Render(value))
	}

	switch name {
	case "delegate_to_specialist":
		field("role", dArgString(args, "role"))
		field("task", dArgString(args, "task"))
		if files := dArgStringSlice(args, "expected_files"); len(files) > 0 {
			field("files", strings.Join(files, ", "))
		}
		field("verify", dArgString(args, "verify_cmd"))
	case "delegate_to_worker", "delegate_to_team":
		field("task", dArgString(args, "task"))
		field("verify", dArgString(args, "verify_cmd"))
	case "delegate_to_team_parallel":
		tasks := dArgStringSlice(args, "tasks")
		lines = append(lines, "      "+labelStyle.Render(fmt.Sprintf("tasks (%d件):", len(tasks))))
		for i, t := range tasks {
			lines = append(lines, "        "+valueStyle.Render(fmt.Sprintf("%d. %s", i+1, truncateField(t, delegationFieldMax))))
		}
		field("verify", dArgString(args, "verify_cmd"))
	case "delegate_research":
		field("question", dArgString(args, "question"))
	case "continue_specialist":
		field("task", dArgString(args, "task"))
		field("verify", dArgString(args, "verify_cmd"))
	}
	return strings.Join(lines, "\n")
}

// delegationBadge はツールの権限レベル（読み取り専用/実行可/書き込み可）を
// バッジ文字列とその強調色として返す。delegate_to_specialist以外は
// ツールの性質上、権限が固定（説明文参照）のためargsを見ずに決め打ちする。
func delegationBadge(name string, args map[string]any) (string, lipgloss.Style) {
	write := lipgloss.NewStyle().Bold(true).Foreground(colAmber)
	exec := lipgloss.NewStyle().Bold(true).Foreground(colTitle)
	readOnly := lipgloss.NewStyle().Bold(true).Foreground(colMuted)

	switch name {
	case "delegate_to_specialist":
		switch {
		case dArgBool(args, "can_write"):
			return "書き込み可", write
		case dArgBool(args, "can_execute"):
			return "実行可", exec
		default:
			return "読み取り専用", readOnly
		}
	case "delegate_to_worker", "delegate_to_team", "delegate_to_team_parallel":
		return "書き込み可", write
	case "continue_specialist":
		return "書き込み継続", write
	case "delegate_research":
		return "調査のみ", readOnly
	default:
		return "", lipgloss.NewStyle()
	}
}

// truncateField はJSON引数から取り出した1フィールドの表示用トリム（前後空白
// 除去＋長すぎる場合は省略記号）を行う。
func truncateField(s string, max int) string {
	s = strings.TrimSpace(s)
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max]) + "…"
}

func dArgString(args map[string]any, key string) string {
	if args == nil {
		return ""
	}
	s, _ := args[key].(string)
	return s
}

func dArgBool(args map[string]any, key string) bool {
	if args == nil {
		return false
	}
	b, _ := args[key].(bool)
	return b
}

func dArgStringSlice(args map[string]any, key string) []string {
	if args == nil {
		return nil
	}
	raw, ok := args[key].([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, v := range raw {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}
