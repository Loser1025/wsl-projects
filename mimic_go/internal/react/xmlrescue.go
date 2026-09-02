// XML形式ツール呼び出し救済（Python版 orchestrator.py::_parse_xml_tool_calls の移植）。
// 一部の弱いモデルはOpenAIネイティブのtool_calls形式ではなく、応答テキスト内に
// XML風のツール呼び出しを埋め込む（<tool_call>{...}</tool_call>等）。
// tool_callsが空でもテキストにこのパターンが含まれていれば救済的にパースする。
package react

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"mimic/internal/llm"
)

var (
	// Python版 orchestrator.py::_XML_TOOL_PATTERN の移植。検知対象は
	// <invoke>/<function_calls>/[TOOL_CALL]も含むが、実際のパース対応
	// フォーマット（parseXMLToolCalls）はtool_call/function=のみ —
	// これはPython版も同じ非対称（検知はしてもパースできなければXML救済の
	// リトライ要求に倒れる、という設計を踏襲）。
	xmlToolCallPattern = regexp.MustCompile(`(?i)<tool_call\b|<function=|<invoke\b|<function_calls\b|\[TOOL_CALL\]`)
	toolCallBlockRe    = regexp.MustCompile(`(?is)<tool_call\b[^>]*>(.*?)</tool_call>`)
	functionBlockRe    = regexp.MustCompile(`(?is)<function=([^>]+)>(.*?)(?:</function>|$)`)
	parameterRe        = regexp.MustCompile(`(?is)<parameter=([^>]+)>(.*?)</parameter>`)
	parametersJSONRe   = regexp.MustCompile(`(?is)<parameters?>(.*?)</parameters?>`)
)

// hasXMLToolCall はテキストにXML形式ツール呼び出しらしきパターンが含まれるかを判定する。
func hasXMLToolCall(text string) bool {
	return xmlToolCallPattern.MatchString(text)
}

// parseXMLToolCalls はテキスト内のXML形式ツール呼び出しをパースして
// llm.ToolCall のリストに変換する（対応フォーマットA/B/CはPython版と同じ）。
func parseXMLToolCalls(text string) []llm.ToolCall {
	var results []llm.ToolCall

	add := func(name string, args map[string]any) {
		argsJSON, err := json.Marshal(args)
		if err != nil {
			argsJSON = []byte("{}")
		}
		results = append(results, llm.ToolCall{
			ID:   fmt.Sprintf("xml_call_%d", len(results)),
			Type: "function",
			Function: llm.ToolCallFunction{
				Name:      strings.TrimSpace(name),
				Arguments: string(argsJSON),
			},
		})
	}

	// フォーマットA/B: <tool_call>...</tool_call>
	for _, m := range toolCallBlockRe.FindAllStringSubmatch(text, -1) {
		body := strings.TrimSpace(m[1])

		// A: 中身がそのままJSON
		var obj map[string]any
		if err := json.Unmarshal([]byte(body), &obj); err == nil {
			if name, ok := obj["name"].(string); ok {
				rawArgs, _ := firstMap(obj["arguments"], obj["parameters"], obj["args"])
				add(name, rawArgs)
				continue
			}
		}

		// B: <function=NAME>...</function>
		if fm := functionBlockRe.FindStringSubmatch(body); fm != nil {
			add(fm[1], extractParams(fm[2]))
		}
	}

	// フォーマットC: <function=...> 単独 (tool_call なし)
	if len(results) == 0 {
		for _, m := range functionBlockRe.FindAllStringSubmatch(text, -1) {
			add(m[1], extractParams(m[2]))
		}
	}

	return results
}

func firstMap(candidates ...any) (map[string]any, bool) {
	for _, c := range candidates {
		if m, ok := c.(map[string]any); ok {
			return m, true
		}
	}
	return map[string]any{}, false
}

// extractParams は <parameter=NAME>VALUE</parameter> を全て抽出してmapに変換する。
// 見つからなければ <parameters>{JSON}</parameters> 、それも無ければ本文全体をJSONとして試す。
func extractParams(fnBody string) map[string]any {
	params := make(map[string]any)
	for _, pm := range parameterRe.FindAllStringSubmatch(fnBody, -1) {
		params[strings.TrimSpace(pm[1])] = coerce(pm[2])
	}
	if len(params) > 0 {
		return params
	}
	if jm := parametersJSONRe.FindStringSubmatch(fnBody); jm != nil {
		var obj map[string]any
		if err := json.Unmarshal([]byte(strings.TrimSpace(jm[1])), &obj); err == nil {
			return obj
		}
	}
	var obj map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(fnBody)), &obj); err == nil {
		return obj
	}
	return params
}

// coerce は数値文字列をint/floatへ変換する（それ以外は文字列のまま）。
func coerce(val string) any {
	s := strings.TrimSpace(val)
	if n, err := strconv.Atoi(s); err == nil {
		return n
	}
	if f, err := strconv.ParseFloat(s, 64); err == nil {
		return f
	}
	return s
}
