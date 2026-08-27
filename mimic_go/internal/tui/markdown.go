package tui

import (
	"regexp"
	"strings"

	"charm.land/lipgloss/v2"
)

// チャットログの簡易Markdownレンダリング（Python版 utils.py::render_markdown /
// _render_inline の移植）。対応: 見出し(1-4段階)／太字／斜体／インラインコード／
// フェンスコードブロック／箇条書き（インデント別記号）／番号リスト／水平線。
// テーブル・リンクはPython版自体にも実装が無いため対象外。

var (
	mdHeaderRe    = regexp.MustCompile(`^(#{1,4})\s+(.*)$`)
	mdBoldRe      = regexp.MustCompile(`\*\*([^*]+)\*\*|__([^_]+)__`)
	mdItalicRe    = regexp.MustCompile(`\*([^*]+)\*|_([^_]+)_`)
	mdInlineCode  = regexp.MustCompile("`([^`]+)`")
	mdBulletRe    = regexp.MustCompile(`^(\s*)[-*+]\s+(.*)$`)
	mdNumberedRe  = regexp.MustCompile(`^(\s*)(\d+)\.\s+(.*)$`)
	mdHRRe        = regexp.MustCompile(`^[-*_]{3,}$`)
	mdFenceMarker = "```"

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
	s = mdBoldRe.ReplaceAllStringFunc(s, func(match string) string {
		g := mdBoldRe.FindStringSubmatch(match)
		inner := g[1]
		if inner == "" {
			inner = g[2]
		}
		return mdBoldStyle.Render(inner)
	})
	s = mdItalicRe.ReplaceAllStringFunc(s, func(match string) string {
		g := mdItalicRe.FindStringSubmatch(match)
		inner := g[1]
		if inner == "" {
			inner = g[2]
		}
		return mdItalicStyle.Render(inner)
	})
	return s
}
