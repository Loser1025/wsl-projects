package llm

import "strings"

// 送信直前トリム＋孤立tool_calls修復（Python版 agent.py::_trim_messages_smart /
// _trim_to_fit / _repair_message_sequence の移植）。Python版がagent.py（API層）に
// これらを置いているのに合わせ、Go版もinternal/reactではなくinternal/llmに置く
// （internal/llmはinternal/reactに依存できないため、コンテキスト超過時の
// 緊急トリム再送[StreamChat内]からも直接呼べるようにする狙いもある）。

const (
	charsPerToken   = 4
	trimSendRatio   = 0.90
	trimMaxRounds   = 8
	trimMinMessages = 4
)

// RepairMessageSequence は孤立したtool_calls/toolロールメッセージを除去する
// （Python版 agent.py::_repair_message_sequence の移植）。compaction/trimで
// assistant(tool_calls)⇔tool応答のペアが分断された場合、そのままAPIへ送ると
// OpenAI互換エンドポイントがプロトコル違反として拒否するため、送信直前に
// 必ず適用して整合性を保証する。
func RepairMessageSequence(messages []Message) []Message {
	repaired := make([]Message, 0, len(messages))
	i := 0
	for i < len(messages) {
		m := messages[i]
		if m.Role == "assistant" && len(m.ToolCalls) > 0 {
			j := i + 1
			var toolMsgs []Message
			for j < len(messages) && messages[j].Role == "tool" {
				toolMsgs = append(toolMsgs, messages[j])
				j++
			}
			expected := make(map[string]bool)
			for _, tc := range m.ToolCalls {
				if tc.ID != "" {
					expected[tc.ID] = true
				}
			}
			found := make(map[string]bool, len(toolMsgs))
			for _, tm := range toolMsgs {
				found[tm.ToolCallID] = true
			}
			complete := true
			for id := range expected {
				if !found[id] {
					complete = false
					break
				}
			}
			if len(expected) > 0 && !complete {
				// 対応するtool応答が揃っていない → ブロックごとスキップ
				i = j
				continue
			}
			repaired = append(repaired, m)
			repaired = append(repaired, toolMsgs...)
			i = j
			continue
		}
		if m.Role == "tool" {
			// 直前がtool_callsを持つassistantでなければ孤立
			if len(repaired) > 0 {
				prev := repaired[len(repaired)-1]
				if prev.Role == "assistant" && len(prev.ToolCalls) > 0 {
					repaired = append(repaired, m)
				}
			}
			i++
			continue
		}
		repaired = append(repaired, m)
		i++
	}
	return repaired
}

// TrimToFit はcontextLength(トークン数)が既知であれば、systemPromptを差し引いた
// 送信可能文字数の90%を超えている間、TrimMessagesSmartを繰り返し適用する。
// contextLength<=0（不明）の場合は何もしない（Python版と同じフォールバック）。
func TrimToFit(messages []Message, systemPrompt string, contextLength int) []Message {
	if contextLength <= 0 {
		return messages
	}
	maxChars := int(float64(contextLength) * charsPerToken * trimSendRatio)
	available := maxChars - len(systemPrompt)
	if available < 2000 {
		available = 2000
	}
	total := 0
	for _, m := range messages {
		total += msgCharCount(m)
	}
	rounds := 0
	for total > available && len(messages) > trimMinMessages && rounds < trimMaxRounds {
		messages = TrimMessagesSmart(messages)
		total = 0
		for _, m := range messages {
			total += msgCharCount(m)
		}
		rounds++
	}
	return messages
}

// TrimMessagesSmart は先頭2件（システムプロンプト相当のペア想定）を保護し、
// 残りの約1/4を、assistant(tool_calls)+後続toolメッセージのアトミックブロック
// 単位で古い方から間引く。ブロック削除だけで足りなければ非ブロックメッセージも
// 個別に削る（Python版 _trim_messages_smart の移植）。
func TrimMessagesSmart(messages []Message) []Message {
	if len(messages) <= 2 {
		return messages
	}
	protected := messages[:2]
	body := messages[2:]
	if len(body) == 0 {
		return messages
	}
	targetRemove := len(body) / 4
	if targetRemove < 2 {
		targetRemove = 2
	}

	type block struct{ start, count int }
	var blocks []block
	i := 0
	for i < len(body) {
		m := body[i]
		if m.Role == "assistant" && len(m.ToolCalls) > 0 {
			j := i + 1
			for j < len(body) && body[j].Role == "tool" {
				j++
			}
			blocks = append(blocks, block{i, j - i})
			i = j
		} else {
			i++
		}
	}

	toRemove := make(map[int]bool)
	removed := 0
	for _, b := range blocks {
		if removed >= targetRemove {
			break
		}
		for k := b.start; k < b.start+b.count; k++ {
			toRemove[k] = true
		}
		removed += b.count
	}
	if removed < targetRemove {
		for i := 0; i < len(body) && removed < targetRemove; i++ {
			if !toRemove[i] {
				toRemove[i] = true
				removed++
			}
		}
	}

	out := make([]Message, 0, len(protected)+len(body)-len(toRemove))
	out = append(out, protected...)
	for i, m := range body {
		if !toRemove[i] {
			out = append(out, m)
		}
	}
	return out
}

func msgCharCount(m Message) int {
	count := len(m.Content)
	for _, tc := range m.ToolCalls {
		count += len(tc.Function.Arguments)
	}
	return count
}

// ctxExceededKeywords はコンテキスト超過エラーを示すキーワード（プロバイダーに
// よって表現が異なる。Python版 config.py::_CTX_EXCEEDED_KEYWORDS の移植）。
var ctxExceededKeywords = []string{
	"context_length", "context length", "context window",
	"token", "too long", "maximum context", "exceeds", "input too large",
	"prompt is too long", "content too large",
}

// isContextExceeded はエラーメッセージがコンテキスト超過を示しているか判定する
// （Python版 agent.py::_is_context_exceeded の移植）。
func isContextExceeded(message string) bool {
	lower := strings.ToLower(message)
	for _, kw := range ctxExceededKeywords {
		if strings.Contains(lower, kw) {
			return true
		}
	}
	return false
}
