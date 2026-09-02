package tools

import (
	"fmt"
	"strings"
	"sync"
)

// 大容量ツール出力の自動キャッシュ・ページング（Python版 utils.py::cache_obs /
// read_tool_cache の移植）。threshold文字を超える結果は全文をメモリキャッシュし、
// 先頭threshold文字だけを会話へ返す。残りはread_tool_cacheツールで
// offset指定してページング取得できる。

const (
	toolChunkSize        = 10000
	toolOutputCacheMax   = 50
	toolOutputCacheStrip = 60
)

var (
	outputCacheMu      sync.Mutex
	outputCache        = make(map[string]string)
	outputCacheOrder   []string
	outputCacheCounter int
)

func registerOutputCacheTools(r *Registry) {
	r.Register("read_tool_cache",
		"cache_obs/cache_tool_outputでキャッシュされた大容量ツール出力の続きをページング取得する。"+
			"直前のツール出力のフッターに記載されたcache_keyを指定すること。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"cache_key": map[string]any{"type": "string", "description": "キャッシュキー（ツール出力のフッターに記載）"},
				"offset":    map[string]any{"type": "integer", "description": "読み取り開始文字位置", "default": 0},
			},
			"required": []string{"cache_key"},
		},
		toolReadToolCache)
}

func toolReadToolCache(args map[string]any) (string, error) {
	cacheKey := argString(args, "cache_key")
	offset := argInt(args, "offset", 0)

	outputCacheMu.Lock()
	result, ok := outputCache[cacheKey]
	keys := make([]string, len(outputCacheOrder))
	copy(keys, outputCacheOrder)
	outputCacheMu.Unlock()

	if !ok {
		return fmt.Sprintf("エラー: cache_key '%s' が見つかりません。利用可能なキー: %v", cacheKey, keys), nil
	}

	// Python版はcontent[offset:offset+chunk]を文字単位でスライスするため、
	// Go版もrune単位に変換する（read_fileと同じ理由）。
	runes := []rune(result)
	total := len(runes)
	if offset < 0 {
		offset = 0
	}
	if offset > total {
		offset = total
	}
	end := offset + toolChunkSize
	if end > total {
		end = total
	}
	sliced := string(runes[offset:end])
	remaining := total - end

	sep := strings.Repeat("─", toolOutputCacheStrip)
	header := fmt.Sprintf("[%s  文字 %d–%d / 全%d文字]\n%s\n", cacheKey, offset, end, total, sep)
	var footer string
	if remaining > 0 {
		footer = fmt.Sprintf("\n%s\n⚠ 残り %d 文字\n  続きを読む: read_tool_cache(cache_key=\"%s\", offset=%d)\n%s",
			sep, remaining, cacheKey, end, sep)
	} else {
		footer = fmt.Sprintf("\n%s\n  ✓ 末尾まで読み込み完了\n%s", sep, sep)
	}
	return header + sliced + footer, nil
}

// storeOutputCache は結果をキャッシュに登録し、キャッシュキーを返す。
func storeOutputCache(toolName, result string) string {
	outputCacheMu.Lock()
	defer outputCacheMu.Unlock()
	outputCacheCounter++
	cacheKey := fmt.Sprintf("%s_%03d", toolName, outputCacheCounter)
	outputCache[cacheKey] = result
	outputCacheOrder = append(outputCacheOrder, cacheKey)
	for len(outputCacheOrder) > toolOutputCacheMax {
		oldest := outputCacheOrder[0]
		outputCacheOrder = outputCacheOrder[1:]
		delete(outputCache, oldest)
	}
	return cacheKey
}

// CacheObs はobservation短縮用（Python版 cache_obs の移植）: threshold文字を
// 超える結果をキャッシュへ登録し、先頭threshold文字+read_tool_cache案内を返す。
// threshold以下ならそのまま返す。
func CacheObs(toolName, result string, threshold int) string {
	runes := []rune(result)
	total := len(runes)
	if total <= threshold {
		return result
	}
	cacheKey := storeOutputCache(toolName, result)
	sliced := string(runes[:threshold])
	remaining := total - threshold
	header := fmt.Sprintf("[%s 全%d文字  cache_key=\"%s\"]\n", toolName, total, cacheKey)
	footer := fmt.Sprintf("\n…残り%d文字: read_tool_cache(cache_key=\"%s\", offset=%d)", remaining, cacheKey, threshold)
	return header + sliced + footer
}
