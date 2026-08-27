package tools

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/chromedp/chromedp"
)

// browser_*系ツール（Python版 tools.py::_browser_registry / Playwright実装の
// chromedp移植）。ブラウザは遅延起動（lazy init）: 初回のbrowser_navigate等の
// 呼び出しで初めてChrome/Chromiumプロセスを起動する。Chrome/Chromiumが
// インストールされていない環境ではエラーメッセージを返すだけで、
// 登録自体は常に行う（Python版がplaywright未インストール時もツール登録は
// 行い、実行時にImportErrorをエラーメッセージへ変換するのと同じ設計）。

var (
	browserMu     sync.Mutex
	browserAllocC context.Context
	browserAllocX context.CancelFunc
	browserCtx    context.Context
	browserCancel context.CancelFunc
)

const browserActionTimeout = 30 * time.Second

// getBrowserContext はchromedpのブラウザコンテキストをlazy initで返す。
func getBrowserContext() (context.Context, error) {
	browserMu.Lock()
	defer browserMu.Unlock()
	if browserCtx != nil {
		if browserCtx.Err() == nil {
			return browserCtx, nil
		}
		// 前回のコンテキストが失効している（ブラウザがクラッシュ・閉じられた等）
		browserCtx, browserCancel = nil, nil
		if browserAllocX != nil {
			browserAllocX()
			browserAllocC, browserAllocX = nil, nil
		}
	}

	opts := append(chromedp.DefaultExecAllocatorOptions[:], chromedp.Flag("headless", false))
	allocCtx, allocCancel := chromedp.NewExecAllocator(context.Background(), opts...)
	ctx, cancel := chromedp.NewContext(allocCtx)
	// 実際にブラウザプロセスを起動して疎通確認する（未インストール環境を
	// この時点で検出し、呼び出し元へエラーとして返せるようにする）。
	if err := chromedp.Run(ctx, chromedp.Navigate("about:blank")); err != nil {
		cancel()
		allocCancel()
		return nil, fmt.Errorf(
			"ブラウザの起動に失敗しました（Chrome/Chromiumが見つからない可能性があります）: %w", err)
	}

	browserAllocC, browserAllocX = allocCtx, allocCancel
	browserCtx, browserCancel = ctx, cancel
	return browserCtx, nil
}

func registerBrowserTools(r *Registry) {
	r.Register("browser_navigate",
		"ブラウザで指定URLに遷移する。ログインページや動的サイトの操作に使用。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"url":     map[string]any{"type": "string", "description": "遷移先のURL"},
				"wait_ms": map[string]any{"type": "integer", "description": "遷移後の待機ミリ秒（デフォルト1000）", "default": 1000},
			},
			"required": []string{"url"},
		},
		toolBrowserNavigate)

	r.Register("browser_click",
		"CSSセレクタで要素をクリックする。ボタン・リンク・メニュー操作に使用。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"selector": map[string]any{"type": "string", "description": "CSSセレクタ...またはテキスト（例: text=ログイン）"},
				"wait_ms":  map[string]any{"type": "integer", "description": "クリック後の待機ミリ秒（デフォルト500）", "default": 500},
			},
			"required": []string{"selector"},
		},
		toolBrowserClick)

	r.Register("browser_type",
		"入力フィールドにテキストを入力する。フォーム記入・検索ボックス入力に使用。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"selector":    map[string]any{"type": "string", "description": "入力先のCSSセレクタ（例: input[name=email]）"},
				"text":        map[string]any{"type": "string", "description": "入力するテキスト"},
				"clear_first": map[string]any{"type": "boolean", "description": "入力前に既存テキストを消去するか（デフォルトtrue）", "default": true},
			},
			"required": []string{"selector", "text"},
		},
		toolBrowserType)

	r.Register("browser_get_text",
		"ページ全体またはセレクタで指定した要素のテキストを取得する。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"selector":  map[string]any{"type": "string", "description": "取得対象のCSSセレクタ（省略時はページ全体）"},
				"max_chars": map[string]any{"type": "integer", "description": "最大取得文字数（デフォルト5000）", "default": 5000},
			},
		},
		toolBrowserGetText)

	r.Register("browser_screenshot",
		"現在のブラウザ画面のスクリーンショットをファイルに保存する。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"path": map[string]any{"type": "string", "description": "保存先ファイルパス（省略時は ./screenshot.png）"},
			},
		},
		toolBrowserScreenshot)

	r.Register("browser_close",
		"ブラウザを閉じてリソースを解放する。セッション終了時に呼ぶ。",
		map[string]any{"type": "object", "properties": map[string]any{}},
		toolBrowserClose)
}

func toolBrowserNavigate(args map[string]any) (string, error) {
	url := argString(args, "url")
	waitMs := argInt(args, "wait_ms", 1000)
	ctx, err := getBrowserContext()
	if err != nil {
		return fmt.Sprintf("browser_navigate エラー: %v", err), nil
	}
	actx, cancel := context.WithTimeout(ctx, browserActionTimeout)
	defer cancel()

	var title, curURL string
	err = chromedp.Run(actx,
		chromedp.Navigate(url),
		chromedp.Sleep(time.Duration(waitMs)*time.Millisecond),
		chromedp.Title(&title),
		chromedp.Location(&curURL),
	)
	if err != nil {
		return fmt.Sprintf("browser_navigate エラー: %v", err), nil
	}
	return fmt.Sprintf("遷移完了: %s\nタイトル: %s", curURL, title), nil
}

// resolveSelector はPlaywright流の `text=...` 擬似セレクタをXPathのテキスト
// マッチ式へ変換する（Python版はPlaywright自体が `text=` エンジンをネイティブ
// サポートするため特別な変換コードは無いが、chromedpにはその機構が無いため
// Go版ではXPathへの変換で同等の挙動を再現する）。それ以外はCSSセレクタとして
// 扱う（chromedp.ByQuery）。
func resolveSelector(selector string) (string, chromedp.QueryOption) {
	if text, ok := strings.CutPrefix(selector, "text="); ok {
		text = strings.Trim(text, `"'`)
		escaped := strings.ReplaceAll(text, `"`, `\"`)
		xpath := fmt.Sprintf(`//*[contains(normalize-space(string(.)), "%s")]`, escaped)
		return xpath, chromedp.BySearch
	}
	return selector, chromedp.ByQuery
}

func toolBrowserClick(args map[string]any) (string, error) {
	rawSelector := argString(args, "selector")
	waitMs := argInt(args, "wait_ms", 500)
	ctx, err := getBrowserContext()
	if err != nil {
		return fmt.Sprintf("browser_click エラー: %v", err), nil
	}
	actx, cancel := context.WithTimeout(ctx, browserActionTimeout)
	defer cancel()

	selector, queryOpt := resolveSelector(rawSelector)
	var curURL string
	err = chromedp.Run(actx,
		chromedp.Click(selector, queryOpt),
		chromedp.Sleep(time.Duration(waitMs)*time.Millisecond),
		chromedp.Location(&curURL),
	)
	if err != nil {
		return fmt.Sprintf("browser_click エラー: %v", err), nil
	}
	return fmt.Sprintf("クリック完了: %s\n現在のURL: %s", rawSelector, curURL), nil
}

func toolBrowserType(args map[string]any) (string, error) {
	selector := argString(args, "selector")
	text := argString(args, "text")
	clearFirst := argBool(args, "clear_first", true)
	ctx, err := getBrowserContext()
	if err != nil {
		return fmt.Sprintf("browser_type エラー: %v", err), nil
	}
	actx, cancel := context.WithTimeout(ctx, browserActionTimeout)
	defer cancel()

	var actions []chromedp.Action
	if clearFirst {
		actions = append(actions, chromedp.Clear(selector, chromedp.ByQuery))
	}
	actions = append(actions, chromedp.SendKeys(selector, text, chromedp.ByQuery))
	if err := chromedp.Run(actx, actions...); err != nil {
		return fmt.Sprintf("browser_type エラー: %v", err), nil
	}
	preview := text
	if len(preview) > 50 {
		preview = preview[:50]
	}
	return fmt.Sprintf("入力完了: %s ← %q", selector, preview), nil
}

func toolBrowserGetText(args map[string]any) (string, error) {
	selector := argString(args, "selector")
	maxChars := argInt(args, "max_chars", 5000)
	if selector == "" {
		selector = "body"
	}
	ctx, err := getBrowserContext()
	if err != nil {
		return fmt.Sprintf("browser_get_text エラー: %v", err), nil
	}
	actx, cancel := context.WithTimeout(ctx, browserActionTimeout)
	defer cancel()

	var text, curURL string
	err = chromedp.Run(actx,
		chromedp.Text(selector, &text, chromedp.ByQuery),
		chromedp.Location(&curURL),
	)
	if err != nil {
		return fmt.Sprintf("browser_get_text エラー: %v", err), nil
	}
	truncated := text
	suffix := ""
	if len(text) > maxChars {
		truncated = text[:maxChars]
		suffix = fmt.Sprintf("\n... (全%d文字中%d文字を表示)", len(text), maxChars)
	}
	return fmt.Sprintf("[URL: %s]\n%s%s", curURL, truncated, suffix), nil
}

func toolBrowserScreenshot(args map[string]any) (string, error) {
	path := argString(args, "path")
	if path == "" {
		path = "./screenshot.png"
	}
	ctx, err := getBrowserContext()
	if err != nil {
		return fmt.Sprintf("browser_screenshot エラー: %v", err), nil
	}
	actx, cancel := context.WithTimeout(ctx, browserActionTimeout)
	defer cancel()

	var buf []byte
	var curURL string
	err = chromedp.Run(actx,
		chromedp.FullScreenshot(&buf, 90),
		chromedp.Location(&curURL),
	)
	if err != nil {
		return fmt.Sprintf("browser_screenshot エラー: %v", err), nil
	}
	if err := os.WriteFile(path, buf, 0o644); err != nil {
		return fmt.Sprintf("browser_screenshot エラー: %v", err), nil
	}
	return fmt.Sprintf("スクリーンショット保存: %s\nURL: %s", path, curURL), nil
}

func toolBrowserClose(args map[string]any) (string, error) {
	browserMu.Lock()
	defer browserMu.Unlock()
	if browserCancel != nil {
		browserCancel()
		browserCtx, browserCancel = nil, nil
	}
	if browserAllocX != nil {
		browserAllocX()
		browserAllocC, browserAllocX = nil, nil
	}
	return "ブラウザを閉じました。", nil
}
