// Package mcpserver はmimic自身の委任ツール群をMCP(Model Context Protocol)
// サーバーとして公開する。internal/mcpがMCP*クライアント*(他サーバーへ接続する側)を
// 実装しているのに対し、本パッケージはその逆——mimicがサーバー側になる。
// メッセージ形式(rpcRequest/rpcResponse、tools/callの結果封筒
// {"content":[{"type":"text","text":...}],"isError":bool})はinternal/mcp/client.goが
// クライアントとして期待する形とプロトコル上一致させてある（自分自身をクライアントに
// 見立てて検証可能にするため）。
package mcpserver

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"sync"

	"mimic/internal/tools"
)

const protocolVersion = "2024-11-05"

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Result  any             `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// Serve はin(標準入力相当)から改行区切りJSON-RPCリクエストを読み、
// out(標準出力相当)へ改行区切りJSON-RPCレスポンスを書き続ける。
// registryが持つツールをtools/list・tools/callで公開する。
// 呼び出し元はoutに本関数以外の出力を混ぜないこと（stdoutはプロトコル専用）。
// inがEOFになるかctx相当のエラーが出るまでブロックする。
//
// リクエストは受信ごとに個別goroutineで処理する（tools/callはdelegate_to_worker
// 等で数分〜数十分ブロックしうるため、直列処理だとinternal/delegate/worker.goの
// MaxDelegationConcurrency=3による並列委任の余地が全く活かせない）。
// 応答の書き込みだけmutexで直列化し、JSON行が途中で混ざらないようにする。
// レスポンスの到着順はリクエスト送信順と一致しない（各レスポンスのidで
// 呼び出し元が対応付けること。JSON-RPC 2.0の仕様上問題ない）。
// inがEOFに達したら、その時点で実行中のリクエストが全て完了するのを待ってから返る。
func Serve(registry *tools.Registry, in io.Reader, out io.Writer) error {
	scanner := bufio.NewScanner(in)
	// tool_call引数（例: 大きめのtask文字列）がbufio.Scannerの既定64KB上限を
	// 超えても壊れないよう、上限を10MBまで広げる。
	scanner.Buffer(make([]byte, 0, 64*1024), 10*1024*1024)

	var writeMu sync.Mutex
	writeResp := func(resp rpcResponse) {
		data, err := json.Marshal(resp)
		if err != nil {
			return
		}
		data = append(data, '\n')
		writeMu.Lock()
		defer writeMu.Unlock()
		out.Write(data)
	}

	var wg sync.WaitGroup
	for scanner.Scan() {
		// scanner.Bytes()は次のScan()呼び出しで上書きされうる内部バッファを指すため
		// コピーする（この後のjson.Unmarshalは同期呼び出しなので実害は無いが、
		// 将来goroutine側に生バイト列を渡す変更をしても安全なように防御的にコピーする）。
		line := append([]byte(nil), bytes.TrimSpace(scanner.Bytes())...)
		if len(line) == 0 {
			continue
		}
		var req rpcRequest
		if err := json.Unmarshal(line, &req); err != nil {
			// プロトコル外の壊れた行は無視する（クラッシュさせない）。
			continue
		}

		wg.Add(1)
		go func(req rpcRequest) {
			defer wg.Done()
			resp, shouldReply := handle(registry, req)
			if !shouldReply {
				return // 通知(id無し)には応答しない
			}
			writeResp(resp)
		}(req)
	}
	wg.Wait()
	return scanner.Err()
}

// handle は1リクエスト分を処理する。shouldReply=falseの場合、呼び出し元は
// respを無視して何も書き込まないこと（JSON-RPCの通知は応答してはならないため）。
func handle(registry *tools.Registry, req rpcRequest) (resp rpcResponse, shouldReply bool) {
	isNotification := len(req.ID) == 0

	switch req.Method {
	case "initialize":
		return rpcResponse{JSONRPC: "2.0", ID: req.ID, Result: map[string]any{
			"protocolVersion": protocolVersion,
			"serverInfo":      map[string]any{"name": "mimic-go", "version": "0.1"},
			"capabilities":    map[string]any{"tools": map[string]any{}},
		}}, !isNotification

	case "notifications/initialized":
		return rpcResponse{}, false

	case "tools/list":
		return rpcResponse{JSONRPC: "2.0", ID: req.ID, Result: map[string]any{
			"tools": toolList(registry),
		}}, !isNotification

	case "tools/call":
		if isNotification {
			return rpcResponse{}, false
		}
		return handleToolsCall(registry, req), true

	default:
		if isNotification {
			return rpcResponse{}, false
		}
		return rpcResponse{JSONRPC: "2.0", ID: req.ID, Error: &rpcError{
			Code: -32601, Message: "method not found: " + req.Method,
		}}, true
	}
}

// toolList はregistry.Specs()(OpenAI function calling形式)をMCPのtools/list形式
// （name/description/inputSchema）へ変換する。
func toolList(registry *tools.Registry) []map[string]any {
	specs := registry.Specs()
	out := make([]map[string]any, 0, len(specs))
	for _, s := range specs {
		out = append(out, map[string]any{
			"name":        s.Function.Name,
			"description": s.Function.Description,
			"inputSchema": s.Function.Parameters,
		})
	}
	return out
}

// handleToolsCall はtools/callを実行し、MCPの結果封筒に包んで返す。
// registry.Callはエラーも"エラー: ..."形式の文字列として返す設計
// （internal/tools/registry.go）のため、isErrorは常にfalseで運用する
// （呼び出し側はテキスト先頭のプレフィックスで失敗を判別できる）。
func handleToolsCall(registry *tools.Registry, req rpcRequest) rpcResponse {
	var params struct {
		Name      string         `json:"name"`
		Arguments map[string]any `json:"arguments"`
	}
	if err := json.Unmarshal(req.Params, &params); err != nil {
		return rpcResponse{JSONRPC: "2.0", ID: req.ID, Error: &rpcError{
			Code: -32602, Message: "invalid params: " + err.Error(),
		}}
	}

	argsJSON, err := json.Marshal(params.Arguments)
	if err != nil {
		argsJSON = []byte("{}")
	}
	result := registry.Call(params.Name, string(argsJSON))

	return rpcResponse{JSONRPC: "2.0", ID: req.ID, Result: map[string]any{
		"content": []map[string]any{{"type": "text", "text": result}},
		"isError": false,
	}}
}
