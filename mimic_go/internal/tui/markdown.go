package tui

import (
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"charm.land/lipgloss/v2"
)

// チャットログの簡易Markdownレンダリング（Python版 utils.py::render_markdown /
// _render_inline の移植）。対応: 見出し(1-4段階)／太字／斜体／インラインコード／
// フェンスコードブロック／箇条書き（インデント別記号）／番号リスト／水平線。
// テーブル・リンクはPython版自体にも実装が無いため対象外。

var (
	mdHeaderRe = regexp.MustCompile(`^(#{1,4})\s+(.*)$`)
	// アスタリスクは単語内でも強調記号として扱ってよい（CommonMark準拠）ため単純な正規表現のまま。
	mdBoldStarRe   = regexp.MustCompile(`\*\*([^*]+)\*\*`)
	mdItalicStarRe = regexp.MustCompile(`\*([^*]+)\*`)
	// アンダースコアは単語内(intraword)では強調記号として発火しない（CommonMarkの
	// intraword emphasisルール）。read_tool_cacheのようなsnake_caseやJSON値を誤って
	// 斜体化しないよう、replaceUnderscoreEmphasis側で前後の文字を見て判定する。
	mdBoldUnderRe   = regexp.MustCompile(`__([^_]+)__`)
	mdItalicUnderRe = regexp.MustCompile(`_([^_]+)_`)
	mdInlineCode    = regexp.MustCompile("`([^`]+)`")
	mdBulletRe      = regexp.MustCompile(`^(\s*)[-*+]\s+(.*)$`)
	mdNumberedRe    = regexp.MustCompile(`^(\s*)(\d+)\.\s+(.*)$`)
	mdHRRe          = regexp.MustCompile(`^[-*_]{3,}$`)
	mdFenceMarker   = "```"

	mdH1Style     = lipgloss.NewStyle().Bold(true).Foreground(colAccent)
	mdH2Style     = lipgloss.NewStyle().Bold(true).Foreground(colAccent)
	mdH3Style     = lipgloss.NewStyle().Foreground(colAccent)
	mdH4Style     = lipgloss.NewStyle().Foreground(colMuted)
	mdBoldStyle   = lipgloss.NewStyle().Bold(true)
	mdItalicStyle = lipgloss.NewStyle().Italic(true).Foreground(colPink)
	mdCodeStyle   = lipgloss.NewStyle().Foreground(colAccent)
	mdCodeBlock   = lipgloss.NewStyle().Foreground(colMuted)
	mdBulletStyle = lipgloss.NewStyle().Foreground(colAccent)
	mdNumStyle    = lipgloss.NewStyle().Foreground(colAccent)
	mdHRStyle     = lipgloss.NewStyle().Foreground(colAccent)
)

var mdBulletGlyphs = []string{"•", "◦", "▸"}

// renderMarkdown は複数行のテキストに簡易Markdown装飾を適用する。
// フェンスコードブロック内は装飾せずそのまま（等幅想定）出力する。
func renderMarkdown(text string) string {
	lines := strings.Split(text, "\n")
	var out []string
	inFence := false
	for _, line := range lines {
		trimmed := strings.TrimRight(line, " \t")
		if strings.HasPrefix(strings.TrimSpace(trimmed), mdFenceMarker) {
			inFence = !inFence
			out = append(out, mdCodeBlock.Render(trimmed))
			continue
		}
		if inFence {
			out = append(out, mdCodeBlock.Render(line))
			continue
		}
		out = append(out, renderMarkdownLine(line))
	}
	return strings.Join(out, "\n")
}

func renderMarkdownLine(line string) string {
	if mdHRRe.MatchString(strings.TrimSpace(line)) {
		return mdHRStyle.Render(strings.Repeat("─", 40))
	}
	if m := mdHeaderRe.FindStringSubmatch(line); m != nil {
		level := len(m[1])
		title := renderInline(m[2])
		switch level {
		case 1:
			return mdH1Style.Render(title) + "\n" + mdH1Style.Render(strings.Repeat("─", min(len(m[2])+2, 50)))
		case 2:
			return mdH2Style.Render(title)
		case 3:
			return mdH3Style.Render(title)
		default:
			return mdH4Style.Render(title)
		}
	}
	if m := mdBulletRe.FindStringSubmatch(line); m != nil {
		indent := len(m[1]) / 2
		glyph := mdBulletGlyphs[min(indent, len(mdBulletGlyphs)-1)]
		return m[1] + mdBulletStyle.Render(glyph) + " " + renderInline(m[2])
	}
	if m := mdNumberedRe.FindStringSubmatch(line); m != nil {
		return m[1] + mdNumStyle.Render(m[2]+".") + " " + renderInline(m[3])
	}
	return renderInline(line)
}

func renderInline(s string) string {
	s = mdInlineCode.ReplaceAllStringFunc(s, func(match string) string {
		inner := mdInlineCode.FindStringSubmatch(match)[1]
		return mdCodeStyle.Render(inner)
	})
	s = mdBoldStarRe.ReplaceAllStringFunc(s, func(match string) string {
		inner := mdBoldStarRe.FindStringSubmatch(match)[1]
		return mdBoldStyle.Render(inner)
	})
	s = replaceUnderscoreEmphasis(s, mdBoldUnderRe, mdBoldStyle)
	s = mdItalicStarRe.ReplaceAllStringFunc(s, func(match string) string {
		inner := mdItalicStarRe.FindStringSubmatch(match)[1]
		return mdItalicStyle.Render(inner)
	})
	s = replaceUnderscoreEmphasis(s, mdItalicUnderRe, mdItalicStyle)
	return s
}

// isEmphasisWordRune はアンダースコア強調の「単語内(intraword)」判定に使う文字種。
// アンダースコア自体は含めない（"_word_"のように前後が"_"の場合は境界として扱う）。
func isEmphasisWordRune(r rune) bool {
	return unicode.IsLetter(r) || unicode.IsDigit(r)
}

// replaceUnderscoreEmphasis はre（mdBoldUnderRe/mdItalicUnderRe）にマッチした
// _text_ / __text__ をstyleで装飾するが、CommonMarkのintraword emphasisルールに
// 従い、区切りの前後が英数字（read_tool_cacheのようなsnake_case識別子やJSON値）に
// 直接接している場合はマークダウンとして解釈せず元のテキストのまま残す。
func replaceUnderscoreEmphasis(s string, re *regexp.Regexp, style lipgloss.Style) string {
	locs := re.FindAllStringSubmatchIndex(s, -1)
	if locs == nil {
		return s
	}
	var b strings.Builder
	last := 0
	for _, loc := range locs {
		start, end := loc[0], loc[1]
		innerStart, innerEnd := loc[2], loc[3]
		before, _ := utf8.DecodeLastRuneInString(s[:start])
		after, _ := utf8.DecodeRuneInString(s[end:])
		if isEmphasisWordRune(before) && isEmphasisWordRune(after) {
			continue // 単語内: リテラルのまま残す
		}
		b.WriteString(s[last:start])
		b.WriteString(style.Render(s[innerStart:innerEnd]))
		last = end
	}
	b.WriteString(s[last:])
	return b.String()
}
