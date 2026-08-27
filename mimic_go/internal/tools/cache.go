package tools

import (
	"container/list"
	"path/filepath"
	"strings"
	"sync"
)

// ツール結果のLRUキャッシュ（Python版 agent.py::_tool_cache の移植）。
// read_file/get_repo_mapのように読み取り専用で結果が決定的なツールに限り、
// 同一引数の再呼び出しをキャッシュヒットさせて実行コストを省く。
// 書き込み系ツール成功時、該当パスに関わるキャッシュエントリを無効化する。

const toolCacheMax = 128

// cacheableTools はキャッシュ対象ツール名の集合（Python版 _CACHEABLE_TOOLS の
// うち、Go版に現存するツール名のみ踏襲。list_directory/search_filesは
// Python側でも既に他名称へ統合済みの旧称のため対象外）。
var cacheableTools = map[string]bool{
	"read_file":    true,
	"get_repo_map": true,
}

type toolCache struct {
	mu    sync.Mutex
	items map[string]*list.Element
	order *list.List
	max   int
}

type cacheEntry struct {
	key   string
	value string
}

var globalToolCache = &toolCache{
	items: make(map[string]*list.Element),
	order: list.New(),
	max:   toolCacheMax,
}

func cacheKey(toolName, argsJSON string) string {
	return toolName + ":" + argsJSON
}

func (c *toolCache) get(key string) (string, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	el, ok := c.items[key]
	if !ok {
		return "", false
	}
	c.order.MoveToFront(el)
	return el.Value.(*cacheEntry).value, true
}

func (c *toolCache) set(key, value string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if el, ok := c.items[key]; ok {
		el.Value.(*cacheEntry).value = value
		c.order.MoveToFront(el)
		return
	}
	el := c.order.PushFront(&cacheEntry{key: key, value: value})
	c.items[key] = el
	for c.order.Len() > c.max {
		oldest := c.order.Back()
		if oldest == nil {
			break
		}
		c.order.Remove(oldest)
		delete(c.items, oldest.Value.(*cacheEntry).key)
	}
}

// invalidatePath はwrite_file/edit_file/patch_file/delete_file成功時に呼ぶ。
// 該当パスを引数に含むread_fileキャッシュと、get_repo_mapの全キャッシュを破棄する
// （Python版 _invalidate_cache_for_path の移植。get_repo_mapはツリー全体を
// 表すため、パス単位の部分無効化ではなく全破棄が安全側の簡略化）。
func (c *toolCache) invalidatePath(path string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	needle := `"` + path + `"`
	for key, el := range c.items {
		if strings.HasPrefix(key, "read_file:") && strings.Contains(key, needle) {
			c.order.Remove(el)
			delete(c.items, key)
			continue
		}
		if strings.HasPrefix(key, "get_repo_map:") {
			c.order.Remove(el)
			delete(c.items, key)
		}
	}
}

// CachedCall はcacheableToolsに含まれるツールについてはLRUキャッシュを
// 参照・更新しながらregistry.Callを実行する。対象外ツールはそのまま実行する。
func CachedCall(r *Registry, toolName, argsJSON string) string {
	if !cacheableTools[toolName] {
		return r.Call(toolName, argsJSON)
	}
	key := cacheKey(toolName, argsJSON)
	if v, ok := globalToolCache.get(key); ok {
		return v
	}
	result := r.Call(toolName, argsJSON)
	if !isCacheableError(result) {
		globalToolCache.set(key, result)
	}
	return result
}

// isCacheableError はエラー結果をキャッシュしないための簡易判定
// （一時的な失敗を誤って恒久化しないため）。
func isCacheableError(output string) bool {
	return strings.HasPrefix(output, "エラー:") || strings.HasPrefix(output, "ツール実行エラー:")
}

// InvalidateCacheForPath は書き込み系ツール成功時に呼ぶ公開関数。
func InvalidateCacheForPath(path string) {
	if path == "" {
		return
	}
	globalToolCache.invalidatePath(filepath.Clean(path))
	globalToolCache.invalidatePath(path)
}
