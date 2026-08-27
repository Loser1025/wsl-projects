package tui

import "strings"

// ThinkAwareBuffer はストリームチャンクから<think>/<thought>ブロックを検出して
// 分割する（Python版 utils.py::ThinkAwareBuffer の移植）。タグが複数チャンクに
// またがっても安全に処理できるよう、タグ長未満の末尾はバッファに保持し続ける。
type ThinkAwareBuffer struct {
	buf     string
	inThink bool
}

var (
	thinkOpenTags  = []string{"<think>", "<thought>"}
	thinkCloseTags = []string{"</think>", "</thought>"}
)

const (
	thinkMaxOpenLen  = 9  // len("<thought>")
	thinkMaxCloseLen = 10 // len("</thought>")
)

type thinkSegment struct {
	IsThink bool
	Text    string
}

func findFirstTag(buf string, tags []string) (idx, tagLen int) {
	idx, tagLen = -1, 0
	for _, tag := range tags {
		i := strings.Index(buf, tag)
		if i != -1 && (idx == -1 || i < idx) {
			idx, tagLen = i, len(tag)
		}
	}
	return
}

// Push はチャンクを受け取り、タグ自体を除去したセグメント列を返す。
// タグ境界付近の安全マージンはバッファに残し、次回Push/Flushで処理する。
func (b *ThinkAwareBuffer) Push(chunk string) []thinkSegment {
	b.buf += chunk
	var results []thinkSegment
	for len(b.buf) > 0 {
		if b.inThink {
			idx, tlen := findFirstTag(b.buf, thinkCloseTags)
			if idx == -1 {
				safe := len(b.buf) - thinkMaxCloseLen
				if safe > 0 {
					results = append(results, thinkSegment{true, b.buf[:safe]})
					b.buf = b.buf[safe:]
				}
				break
			}
			results = append(results, thinkSegment{true, b.buf[:idx]})
			b.buf = b.buf[idx+tlen:]
			b.inThink = false
		} else {
			idx, tlen := findFirstTag(b.buf, thinkOpenTags)
			if idx == -1 {
				safe := len(b.buf) - thinkMaxOpenLen
				if safe > 0 {
					results = append(results, thinkSegment{false, b.buf[:safe]})
					b.buf = b.buf[safe:]
				}
				break
			}
			if idx > 0 {
				results = append(results, thinkSegment{false, b.buf[:idx]})
			}
			b.buf = b.buf[idx+tlen:]
			b.inThink = true
		}
	}
	return filterEmptySegments(results)
}

func stripPartialTags(text string, tags []string) string {
	for _, tag := range tags {
		maxN := len(tag) - 1
		if maxN > len(text) {
			maxN = len(text)
		}
		for n := maxN; n > 0; n-- {
			if strings.HasPrefix(tag, text[len(text)-n:]) {
				return text[:len(text)-n]
			}
		}
	}
	return text
}

// Flush は残バッファを強制的に吐き出す（ターン終了時に1回呼ぶ）。
func (b *ThinkAwareBuffer) Flush() []thinkSegment {
	if len(b.buf) == 0 {
		return nil
	}
	var results []thinkSegment
	for len(b.buf) > 0 {
		if b.inThink {
			idx, tlen := findFirstTag(b.buf, thinkCloseTags)
			if idx == -1 {
				content := stripPartialTags(b.buf, thinkCloseTags)
				if content != "" {
					results = append(results, thinkSegment{true, content})
				}
				b.buf = ""
				break
			}
			results = append(results, thinkSegment{true, b.buf[:idx]})
			b.buf = b.buf[idx+tlen:]
			b.inThink = false
		} else {
			idx, tlen := findFirstTag(b.buf, thinkOpenTags)
			if idx == -1 {
				content := stripPartialTags(b.buf, thinkOpenTags)
				if content != "" {
					results = append(results, thinkSegment{false, content})
				}
				b.buf = ""
				break
			}
			if idx > 0 {
				results = append(results, thinkSegment{false, b.buf[:idx]})
			}
			b.buf = b.buf[idx+tlen:]
			b.inThink = true
		}
	}
	return filterEmptySegments(results)
}

func filterEmptySegments(segs []thinkSegment) []thinkSegment {
	out := segs[:0]
	for _, s := range segs {
		if s.Text != "" {
			out = append(out, s)
		}
	}
	return out
}
