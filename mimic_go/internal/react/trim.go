package react

import "mimic/internal/llm"

// 送信直前トリム（Python版 agent.py::_trim_messages_smart / _trim_to_fit の移植）。
// compaction（compact.go）とは別軸の保護機構: モデルのコンテキスト窓の90%を
// 超えるペイロードを送ろうとした場合、その場でメッセージの中間ブロックを
// 間引いて送信サイズを削る（compactionは「ターン開始時に古い会話を要約置換」、
// trimは「送信直前に物理的にメッセージを削る最終防衛ライン」という役割分担）。

const (
	charsPerToken   = 4
	trimSendRatio   = 0.90
	trimMaxRounds   = 8
	trimMinMessages = 4
)

// trimToFit はcontextLength(トークン数)が既知であれば、systemPromptを差し引いた
// 送信可能文字数の90%を超えている間、trimMessagesSmartを繰り返し適用する。
// contextLength<=0（不明）の場合は何もしない（Python版と同じフォールバック）。
func trimToFit(messages []llm.Message, systemPrompt string, contextLength int) []llm.Message {
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
		messages = trimMessagesSmart(messages)
		total = 0
		for _, m := range messages {
			total += msgCharCount(m)
		}
		rounds++
	}
	return messages
}

// trimMessagesSmart は先頭2件（システムプロンプト相当のペア想定）を保護し、
// 残りの約1/4を、assistant(tool_calls)+後続toolメッセージのアトミックブロック
// 単位で古い方から間引く。ブロック削除だけで足りなければ非ブロックメッセージも
// 個別に削る（Python版 _trim_messages_smart の移植）。
func trimMessagesSmart(messages []llm.Message) []llm.Message {
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

	out := make([]llm.Message, 0, len(protected)+len(body)-len(toRemove))
	out = append(out, protected...)
	for i, m := range body {
		if !toRemove[i] {
			out = append(out, m)
		}
	}
	return out
}
