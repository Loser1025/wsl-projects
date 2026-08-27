package tools

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"golang.org/x/text/encoding/htmlindex"
)

const userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

var (
	resultTitlePat   = regexp.MustCompile(`(?s)class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>`)
	resultSnippetPat = regexp.MustCompile(`(?s)class="result__snippet"[^>]*>(.*?)</a>`)
	uddgPat          = regexp.MustCompile(`uddg=([^&"]+)`)
	tagStripPat      = regexp.MustCompile(`<[^>]+>`)
	scriptStylePat   = regexp.MustCompile(`(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</(script|style|nav|footer|header|aside)>`)
	commentPat       = regexp.MustCompile(`(?s)<!--.*?-->`)
	titlePat         = regexp.MustCompile(`(?is)<title[^>]*>(.*?)</title>`)
	numEntityPat     = regexp.MustCompile(`&#(\d+);`)
	spacePat         = regexp.MustCompile(`[ \t]+`)
	blankLinesPat    = regexp.MustCompile(`\n{3,}`)
)

func registerWebTools(r *Registry) {
	r.Register("web_search",
		"キーワードでWebを検索して結果（タイトル・URL・概要）を返す。DuckDuckGo使用、APIキー不要。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"query":       map[string]any{"type": "string", "description": "検索クエリ"},
				"max_results": map[string]any{"type": "integer", "description": "最大件数（デフォルト5）", "default": 5},
			},
			"required": []string{"query"},
		},
		toolWebSearch)

	r.Register("fetch_webpage",
		"URLのWebページを取得してテキストを抽出する。web_searchで得たURLの内容を詳しく読む・ドキュメントを参照する・記事全文を確認するのに使う。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"url":       map[string]any{"type": "string", "description": "取得するURL"},
				"max_chars": map[string]any{"type": "integer", "description": "最大文字数（デフォルト10000）", "default": 10000},
			},
			"required": []string{"url"},
		},
		toolFetchWebpage)
}

func httpGet(rawURL string, timeout time.Duration) ([]byte, string, error) {
	req, err := http.NewRequest(http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, "", err
	}
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Accept-Language", "ja,en-US;q=0.9,en;q=0.8")

	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(req)
	if err != nil {
		return nil, "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, "", err
	}
	return body, resp.Header.Get("Content-Type"), nil
}

// decodeByCharset はContent-Typeヘッダのcharsetを検出しHTMLをUTF-8文字列に
// デコードする（Python版 fetch_webpage の charset 検出処理の移植。charset未指定
// またはutf-8ならそのまま、他エンコーディングはhtmlindexで対応するデコーダを
// 探しベストエフォートで変換、失敗時はutf-8のまま返す＝Python版の
// `except (LookupError, UnicodeDecodeError): html = raw.decode("utf-8", errors="replace")`
// と同等のフォールバック）。
func decodeByCharset(body []byte, contentType string) string {
	charset := "utf-8"
	if idx := strings.Index(contentType, "charset="); idx != -1 {
		charset = strings.TrimSpace(contentType[idx+len("charset="):])
		if semi := strings.Index(charset, ";"); semi != -1 {
			charset = strings.TrimSpace(charset[:semi])
		}
	}
	if strings.EqualFold(charset, "utf-8") || strings.EqualFold(charset, "utf8") {
		return string(body)
	}
	enc, err := htmlindex.Get(charset)
	if err != nil {
		return string(body)
	}
	decoded, err := enc.NewDecoder().Bytes(body)
	if err != nil {
		return string(body)
	}
	return string(decoded)
}

func stripHTML(s string) string {
	s = tagStripPat.ReplaceAllString(s, "")
	s = strings.ReplaceAll(s, "&amp;", "&")
	s = strings.ReplaceAll(s, "&#x2F;", "/")
	return strings.TrimSpace(s)
}

func toolWebSearch(args map[string]any) (string, error) {
	query := argString(args, "query")
	maxResults := argInt(args, "max_results", 5)

	searchURL := "https://html.duckduckgo.com/html/?q=" + url.QueryEscape(query)
	body, _, err := httpGet(searchURL, 15*time.Second)
	if err != nil {
		return fmt.Sprintf("Web検索エラー: %v", err), nil
	}
	html := string(body)

	titleMatches := resultTitlePat.FindAllStringSubmatch(html, -1)
	snippetMatches := resultSnippetPat.FindAllStringSubmatch(html, -1)

	var results []string
	for i, m := range titleMatches {
		if i >= maxResults {
			break
		}
		href, title := m[1], m[2]
		titleClean := stripHTML(title)
		actualURL := href
		if uddg := uddgPat.FindStringSubmatch(href); uddg != nil {
			if decoded, err := url.QueryUnescape(uddg[1]); err == nil {
				actualURL = decoded
			}
		}
		snippet := ""
		if i < len(snippetMatches) {
			snippet = stripHTML(snippetMatches[i][1])
		}
		results = append(results, fmt.Sprintf("[%d] %s\n    %s\n    %s", i+1, titleClean, actualURL, snippet))
	}

	if len(results) == 0 {
		return fmt.Sprintf("「%s」の検索結果が見つかりませんでした。", query), nil
	}
	return fmt.Sprintf("Web検索: 「%s」\n\n%s", query, strings.Join(results, "\n\n")), nil
}

func toolFetchWebpage(args map[string]any) (string, error) {
	rawURL := argString(args, "url")
	maxChars := argInt(args, "max_chars", 10000)

	body, contentType, err := httpGet(rawURL, 20*time.Second)
	if err != nil {
		return fmt.Sprintf("ページ取得エラー: %v", err), nil
	}
	html := decodeByCharset(body, contentType)

	html = scriptStylePat.ReplaceAllString(html, " ")
	html = commentPat.ReplaceAllString(html, " ")

	title := ""
	if m := titlePat.FindStringSubmatch(html); m != nil {
		title = strings.TrimSpace(tagStripPat.ReplaceAllString(m[1], ""))
	}

	text := tagStripPat.ReplaceAllString(html, " ")

	entities := map[string]string{
		"&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ",
		"&#39;": "'", "&quot;": `"`, "&#x2F;": "/", "&apos;": "'",
	}
	for ent, ch := range entities {
		text = strings.ReplaceAll(text, ent, ch)
	}
	text = numEntityPat.ReplaceAllStringFunc(text, func(m string) string {
		sub := numEntityPat.FindStringSubmatch(m)
		n, err := strconv.Atoi(sub[1])
		if err != nil || n >= 0x110000 {
			return ""
		}
		return string(rune(n))
	})

	text = spacePat.ReplaceAllString(text, " ")
	text = blankLinesPat.ReplaceAllString(text, "\n\n")
	text = strings.TrimSpace(text)

	header := fmt.Sprintf("URL: %s\n", rawURL)
	if title != "" {
		header += fmt.Sprintf("タイトル: %s\n", title)
	}
	header += "\n"

	body2 := text
	suffix := ""
	if len(text) > maxChars {
		body2 = text[:maxChars]
		suffix = fmt.Sprintf("\n\n... (全 %d 文字中 %d 文字を表示)", len(text), maxChars)
	}
	return header + body2 + suffix, nil
}
