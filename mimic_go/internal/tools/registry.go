// Package tools はエージェントが呼び出せるツールのレジストリを実装する
// （フェーズ2: ファイル書き込み・検索系の主要ツールに対応。委任系
// (delegate_*) とブラウザ系 (browser_*) は、それぞれサンドボックス・
// chromedp移植を伴うフェーズ3/4の範囲として本フェーズでは対象外）。
package tools

import (
	"encoding/json"
	"fmt"

	"mimic/internal/llm"
)

const maxReadChars = 20000 // Python版のチャンク読みは後続フェーズで移植、まずは単純上限

type Handler func(args map[string]any) (string, error)

type entry struct {
	spec    llm.ToolSpec
	handler Handler
}

type Registry struct {
	tools map[string]entry
	order []string
}

func NewRegistry() *Registry {
	return &Registry{tools: make(map[string]entry)}
}

func (r *Registry) Register(name, description string, parameters map[string]any, handler Handler) {
	r.tools[name] = entry{
		spec: llm.ToolSpec{
			Type: "function",
			Function: llm.ToolFuncSpec{
				Name:        name,
				Description: description,
				Parameters:  parameters,
			},
		},
		handler: handler,
	}
	r.order = append(r.order, name)
}

// Subset は指定した名前のツールだけを持つ新しいRegistryを返す
// （Python版 ToolRegistry.copy_tool の移植。Researcher等、読み取り専用+一部の
// ツールしか持たせたくない役割向けにレジストリを制限するために使う）。
func (r *Registry) Subset(names []string) *Registry {
	sub := NewRegistry()
	for _, name := range names {
		if e, ok := r.tools[name]; ok {
			sub.tools[name] = e
			sub.order = append(sub.order, name)
		}
	}
	return sub
}

func (r *Registry) Specs() []llm.ToolSpec {
	specs := make([]llm.ToolSpec, 0, len(r.order))
	for _, name := range r.order {
		specs = append(specs, r.tools[name].spec)
	}
	return specs
}

// Call は tool_calls の1件を実行する。引数JSONのパース失敗やツール未登録も
// エラー文字列として返す（ReActループ側でそのままtool結果として渡せるように）。
// エラー整形は "エラー: ..." / "ツール実行エラー: ..." の形式に統一する
// （internal/react のループブレーカーがこのprefixで失敗判定するため）。
func (r *Registry) Call(name, argsJSON string) string {
	e, ok := r.tools[name]
	if !ok {
		return fmt.Sprintf("エラー: 未登録のツールです: %s", name)
	}
	var args map[string]any
	if argsJSON != "" {
		if err := json.Unmarshal([]byte(argsJSON), &args); err != nil {
			return fmt.Sprintf("エラー: 引数のJSONパースに失敗しました: %v", err)
		}
	}
	out, err := e.handler(args)
	if err != nil {
		return fmt.Sprintf("ツール実行エラー: %v", err)
	}
	return out
}

func argString(args map[string]any, key string) string {
	if v, ok := args[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}

func argInt(args map[string]any, key string, def int) int {
	if v, ok := args[key]; ok {
		if f, ok := v.(float64); ok { // JSON数値はfloat64として来る
			return int(f)
		}
	}
	return def
}

func argBool(args map[string]any, key string, def bool) bool {
	if v, ok := args[key]; ok {
		if b, ok := v.(bool); ok {
			return b
		}
	}
	return def
}

// NewDefaultRegistry はファイル/検索/シェル/Web/Skills系ツールを登録する。
// delegate_*(委任)ツールはinternal/delegate.RegisterToolsが呼び出し側
// （cmd/mimic, internal/tui）から別途このRegistryへ追加する
// （tools→delegate→toolsの依存循環を避けるための構成）。
// browser_*(フェーズ4=chromedp移植後)は未対応。
func NewDefaultRegistry() *Registry {
	r := NewRegistry()
	registerFileTools(r)
	registerSearchTools(r)
	registerShellTools(r)
	registerWebTools(r)
	registerSkillTools(r)
	return r
}
