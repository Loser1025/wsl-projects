package viewer

import (
	"fmt"
	"path/filepath"
	"sort"
	"strings"
)

// GetSessionTraceText はsessionsDir内からsession_start.trace_idが一致する
// セッションを探し、そのThought/Action/Observation/最終回答を読みやすく整形して
// 返す（Python版 viewer.py::get_session_trace_text の移植）。
// delegate_to_team/delegate_to_worker が起動するWorkerは、起動時にMIMIC_TRACE_ID
// 経由でこのtrace_idを自身のsession_startイベントに記録している。
func GetSessionTraceText(sessionsDir, traceID string, maxSteps int) string {
	if maxSteps <= 0 {
		maxSteps = 20
	}
	files, _ := filepath.Glob(filepath.Join(sessionsDir, "*.jsonl"))
	sort.Sort(sort.Reverse(sort.StringSlice(files)))

	var targetFile string
	var targetMeta map[string]any
	for _, f := range files {
		entries := loadEntries(f)
		for _, e := range entries {
			if t, _ := e["type"].(string); t == "session_start" {
				if tid, _ := e["trace_id"].(string); tid == traceID {
					targetFile = f
					targetMeta = e
					break
				}
			}
		}
		if targetFile != "" {
			break
		}
	}

	if targetFile == "" {
		return fmt.Sprintf(
			"trace_id=%s に対応するWorker実行ログが見つかりませんでした"+
				"（Researcherの実行はトレース対象外です）。", traceID)
	}

	provider, _ := targetMeta["provider"].(string)
	model, _ := targetMeta["model"].(string)
	lines := []string{
		fmt.Sprintf("[trace_id=%s のWorker実行トレース]", traceID),
		fmt.Sprintf("モデル: %s/%s", provider, model),
		"",
	}

	seenSteps := make(map[float64]bool)
	truncated := false
	for _, e := range loadEntries(targetFile) {
		t, _ := e["type"].(string)
		step, hasStep := e["step"].(float64)

		if (t == "thought" || t == "action" || t == "observation") && hasStep {
			seenSteps[step] = true
			if len(seenSteps) > maxSteps {
				if !truncated {
					lines = append(lines, fmt.Sprintf("…（%dステップを超えたため以降省略。最終回答のみ末尾に表示）", maxSteps))
					truncated = true
				}
				continue
			}
		}

		switch t {
		case "thought":
			content, _ := e["content"].(string)
			lines = append(lines, fmt.Sprintf("── ステップ%v ──\nThought: %s", step, content))
		case "action":
			tool, _ := e["tool"].(string)
			if tool == "" {
				tool = "?"
			}
			args := fmt.Sprintf("%v", e["args"])
			if len(args) > 200 {
				args = args[:200]
			}
			lines = append(lines, fmt.Sprintf("Action: %s(%s)", tool, args))
		case "observation":
			result, _ := e["result"].(string)
			if len(result) > 500 {
				result = result[:500]
			}
			lines = append(lines, "Observation: "+result)
		case "final_answer":
			content, _ := e["content"].(string)
			lines = append(lines, "\n[最終回答]\n"+content)
		}
	}
	return strings.Join(lines, "\n")
}
