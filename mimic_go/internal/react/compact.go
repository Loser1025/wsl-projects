package react

import (
	"encoding/json"
	"fmt"
	"strings"

	"mimic/internal/llm"
)

// 会話圧縮（Python版 agent.py::_compact_if_needed / _build_compaction_digest /
// _update_compaction_threshold / _compaction_keep_recent の移植）。長時間
// セッションで会話履歴が際限なく膨張するのを防ぐため、古いメッセージを
// 機械抽出したダイジェスト（LLM呼び出し無し）に置換する。
//
// しきい値はモデルのcontext_length（selector.SelectInteractivelyが疎通確認時に
// 取得）から動的計算する。0（不明）の場合は固定フォールバック値を使う
// （Python版の_COMPACTION_DEFAULT=3,000,000字フォールバックと同じ方針だが、
// 実用上意味のある値として大幅に小さい値を採用する）。

const (
	compactionRatio          = 0.75   // コンテキスト容量の75%に達したら圧縮する（Python版 _COMPACTION_RATIO）
	compactionThresholdChars = 200000 // context_length不明時のフォールバック
	compactionKeepRecentMin  = 4
	compactionKeepRecentMax  = 20
	digestMaxLines           = 25
	digestMaxChars           = 1600
)

// compactionMinEffectiveChars はオーバーヘッド差し引き後の実効しきい値の下限
// （Python版 _effective_threshold の `max(1000, ...)` を踏襲）。
const compactionMinEffectiveChars = 1000

// compactionThreshold はcontextLength(トークン数)からしきい値(文字数)を計算する
// （Python版 _update_compaction_threshold の移植）。
func compactionThreshold(contextLength int) int {
	if contextLength > 0 {
		return int(float64(contextLength) * charsPerToken * compactionRatio)
	}
	return compactionThresholdChars
}

// effectiveCompactionThreshold はsystem_prompt/context_headerのオーバーヘッドを
// 差し引いた実効しきい値を返す（Python版 _effective_threshold の移植。Go版は
// 呼び出し時点のsystemPrompt長を直接渡す方式のため、Python版の1秒TTLキャッシュは
// 不要——毎ターン1回しか呼ばれないため）。
func effectiveCompactionThreshold(contextLength, systemPromptLen int) int {
	threshold := compactionThreshold(contextLength) - systemPromptLen
	if threshold < compactionMinEffectiveChars {
		return compactionMinEffectiveChars
	}
	return threshold
}

// compactionKeepRecent はしきい値に応じて圧縮後に残す直近メッセージ数を計算する
// （Python版 _compaction_keep_recent の移植。小さいコンテキストのモデルでは
// 少なく、大きければ最大20。平均メッセージサイズ2000文字×2バッファを想定）。
func compactionKeepRecent(threshold int) int {
	n := threshold / 4000
	if n < compactionKeepRecentMin {
		return compactionKeepRecentMin
	}
	if n > compactionKeepRecentMax {
		return compactionKeepRecentMax
	}
	return n
}

func msgCharCount(m llm.Message) int {
	count := len(m.Content)
	for _, tc := range m.ToolCalls {
		count += len(tc.Function.Arguments)
	}
	return count
}

// compactIfNeeded は会話履歴の合計文字数がしきい値を超えていれば、
// 先頭2件（システムプロンプト相当のペア想定）と直近keepRecent件を
// 残し、間の会話を機械ダイジェストに置換する。
func compactIfNeeded(history *[]llm.Message, contextLength, systemPromptLen int) {
	h := *history
	threshold := effectiveCompactionThreshold(contextLength, systemPromptLen)
	total := 0
	for _, m := range h {
		total += msgCharCount(m)
	}
	if total <= threshold {
		return
	}
	if len(h) <= 2 {
		return
	}

	firstPair := h[:min(2, len(h))]
	keepRecent := compactionKeepRecent(threshold)
	var recentPart []llm.Message
	if keepRecent < len(h) {
		recentPart = h[len(h)-keepRecent:]
	}
	removedStart := len(firstPair)
	removedEnd := len(h) - len(recentPart)
	if removedEnd <= removedStart {
		return
	}
	removed := h[removedStart:removedEnd]

	digest := buildCompactionDigest(removed)
	noteText := fmt.Sprintf("[%d件の古い会話を削除しました（コンテキスト節約）]", len(removed))
	if digest != "" {
		noteText += "\n[削除された会話の機械ダイジェスト（ハーネス自動抽出）]\n" + digest
	}

	note := llm.Message{Role: "user", Content: noteText}
	ack := llm.Message{Role: "assistant", Content: "了解しました。"}

	newHistory := make([]llm.Message, 0, len(firstPair)+2+len(recentPart))
	newHistory = append(newHistory, firstPair...)
	newHistory = append(newHistory, note, ack)
	newHistory = append(newHistory, recentPart...)
	*history = newHistory
}

// buildCompactionDigest は削除対象メッセージから「ユーザー指示」「ツール呼び出しと
// 成否」をLLム無しで機械抽出する（Python版 _build_compaction_digest の移植）。
func buildCompactionDigest(removed []llm.Message) string {
	var lines []string
	pendingCalls := make(map[string]int) // tool_call_id -> lines index

	for _, m := range removed {
		switch m.Role {
		case "user":
			content := strings.TrimSpace(m.Content)
			if content != "" && !strings.HasPrefix(content, "[") {
				fields := strings.Fields(content)
				joined := strings.Join(fields, " ")
				if len(joined) > 80 {
					joined = joined[:80]
				}
				lines = append(lines, "指示: "+joined)
			}
		case "assistant":
			for _, tc := range m.ToolCalls {
				name := tc.Function.Name
				if name == "" {
					name = "?"
				}
				var args map[string]any
				_ = json.Unmarshal([]byte(tc.Function.Arguments), &args)
				target := ""
				for _, key := range []string{"path", "command", "task", "pattern"} {
					if v, ok := args[key].(string); ok && v != "" {
						target = v
						break
					}
				}
				target = strings.Join(strings.Fields(target), " ")
				if len(target) > 60 {
					target = target[:60]
				}
				lines = append(lines, fmt.Sprintf("%s(%s)", name, target))
				if tc.ID != "" {
					pendingCalls[tc.ID] = len(lines) - 1
				}
			}
		case "tool":
			if idx, ok := pendingCalls[m.ToolCallID]; ok {
				delete(pendingCalls, m.ToolCallID)
				content := m.Content
				ok := !strings.HasPrefix(content, "ツール実行エラー") &&
					!strings.HasPrefix(content, "エラー") &&
					!strings.HasPrefix(content, "[ループ防止]")
				if ok {
					lines[idx] += " →OK"
				} else {
					lines[idx] += " →失敗"
				}
			}
		}
	}

	if len(lines) == 0 {
		return ""
	}
	if len(lines) > digestMaxLines {
		omitted := len(lines) - digestMaxLines
		lines = append([]string{fmt.Sprintf("…（先頭%d行省略）", omitted)}, lines[len(lines)-digestMaxLines:]...)
	}
	var b strings.Builder
	for _, ln := range lines {
		b.WriteString("- " + ln + "\n")
	}
	text := strings.TrimRight(b.String(), "\n")
	if len(text) > digestMaxChars {
		text = text[:digestMaxChars]
	}
	return text
}
