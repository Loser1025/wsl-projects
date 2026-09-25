package mcpserver

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"mimic/internal/tools"
)

func newTestRegistry() *tools.Registry {
	r := tools.NewRegistry()
	r.Register("echo", "引数をそのまま返すテスト用ツール",
		map[string]any{
			"type":       "object",
			"properties": map[string]any{"msg": map[string]any{"type": "string"}},
			"required":   []string{"msg"},
		},
		func(args map[string]any) (string, error) {
			s, _ := args["msg"].(string)
			return "echo:" + s, nil
		})
	return r
}

// decodeResponses はServe()の出力(改行区切りJSON)を順にデコードして返す。
// Serve()はリクエストをgoroutineで並行処理するため、到着順は送信順と
// 一致しない前提で扱うこと（呼び出し側はidで対応付ける）。
func decodeResponses(t *testing.T, out *bytes.Buffer) []rpcResponse {
	t.Helper()
	var resps []rpcResponse
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if line == "" {
			continue
		}
		var r rpcResponse
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			t.Fatalf("応答のJSONパースに失敗: %v (line=%q)", err, line)
		}
		resps = append(resps, r)
	}
	return resps
}

// byID はidをキーにレスポンスを引けるようにする（並行処理により到着順が
// 保証されないテストで使う）。
func byID(t *testing.T, resps []rpcResponse) map[string]rpcResponse {
	t.Helper()
	m := make(map[string]rpcResponse, len(resps))
	for _, r := range resps {
		m[string(r.ID)] = r
	}
	return m
}

func TestServe_InitializeToolsListToolsCall(t *testing.T) {
	registry := newTestRegistry()

	in := strings.NewReader(strings.Join([]string{
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}`,
		`{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}`,
		`{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"msg":"hello"}}}`,
	}, "\n") + "\n")
	var out bytes.Buffer

	if err := Serve(registry, in, &out); err != nil {
		t.Fatalf("Serve failed: %v", err)
	}

	resps := decodeResponses(t, &out)
	// notifications/initializedには応答が無いので3件のはず。
	if len(resps) != 3 {
		t.Fatalf("応答数 = %d, want 3", len(resps))
	}
	byIDResps := byID(t, resps)

	// id=1: initialize
	var initResult struct {
		ProtocolVersion string `json:"protocolVersion"`
	}
	if err := json.Unmarshal(toRaw(t, byIDResps["1"].Result), &initResult); err != nil {
		t.Fatal(err)
	}
	if initResult.ProtocolVersion != protocolVersion {
		t.Errorf("protocolVersion = %q, want %q", initResult.ProtocolVersion, protocolVersion)
	}

	// id=2: tools/list
	var listResult struct {
		Tools []map[string]any `json:"tools"`
	}
	if err := json.Unmarshal(toRaw(t, byIDResps["2"].Result), &listResult); err != nil {
		t.Fatal(err)
	}
	if len(listResult.Tools) != 1 || listResult.Tools[0]["name"] != "echo" {
		t.Errorf("tools/list結果が想定と異なる: %+v", listResult.Tools)
	}

	// id=3: tools/call
	var callResult struct {
		Content []map[string]any `json:"content"`
		IsError bool             `json:"isError"`
	}
	if err := json.Unmarshal(toRaw(t, byIDResps["3"].Result), &callResult); err != nil {
		t.Fatal(err)
	}
	if callResult.IsError {
		t.Error("isError=trueになった")
	}
	if len(callResult.Content) != 1 || callResult.Content[0]["text"] != "echo:hello" {
		t.Errorf("tools/call結果が想定と異なる: %+v", callResult.Content)
	}
}

func TestServe_ConcurrentToolsCallsRunInParallel(t *testing.T) {
	const (
		n     = 5
		sleep = 150 * time.Millisecond
	)
	registry := tools.NewRegistry()
	registry.Register("slow", "指定時間だけ待ってから返すテスト用ツール",
		map[string]any{"type": "object"},
		func(args map[string]any) (string, error) {
			time.Sleep(sleep)
			return "done", nil
		})

	var lines []string
	for i := 1; i <= n; i++ {
		lines = append(lines, fmt.Sprintf(`{"jsonrpc":"2.0","id":%d,"method":"tools/call","params":{"name":"slow","arguments":{}}}`, i))
	}
	in := strings.NewReader(strings.Join(lines, "\n") + "\n")
	var out bytes.Buffer

	start := time.Now()
	if err := Serve(registry, in, &out); err != nil {
		t.Fatalf("Serve failed: %v", err)
	}
	elapsed := time.Since(start)

	resps := decodeResponses(t, &out)
	if len(resps) != n {
		t.Fatalf("応答数 = %d, want %d", len(resps), n)
	}

	// 直列処理ならn*sleep(750ms)近くかかるはず。並行処理できていれば
	// sleep 1回分(150ms)程度で全件終わる。余裕を持って半分未満で判定する。
	if elapsed >= n*sleep/2 {
		t.Errorf("elapsed = %v, 並行実行できていない可能性がある（直列なら約%v）", elapsed, n*sleep)
	}
}

func TestServe_UnknownMethodReturnsError(t *testing.T) {
	registry := newTestRegistry()
	in := strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"bogus/method","params":{}}` + "\n")
	var out bytes.Buffer

	if err := Serve(registry, in, &out); err != nil {
		t.Fatalf("Serve failed: %v", err)
	}
	resps := decodeResponses(t, &out)
	if len(resps) != 1 {
		t.Fatalf("応答数 = %d, want 1", len(resps))
	}
	if resps[0].Error == nil {
		t.Fatal("未知のmethodなのにerrorが返らなかった")
	}
}

func TestServe_MalformedLineIgnored(t *testing.T) {
	registry := newTestRegistry()
	in := strings.NewReader(strings.Join([]string{
		`not valid json`,
		`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`,
	}, "\n") + "\n")
	var out bytes.Buffer

	if err := Serve(registry, in, &out); err != nil {
		t.Fatalf("Serve failed: %v", err)
	}
	resps := decodeResponses(t, &out)
	if len(resps) != 1 {
		t.Fatalf("壊れた行を無視できていない: 応答数 = %d, want 1", len(resps))
	}
}

func toRaw(t *testing.T, v any) json.RawMessage {
	t.Helper()
	// rpcResponse.Resultは`any`型なので、json.Unmarshal直後は map[string]any や
	// []any に既に変換済み——再度Marshalしてから狙いの構造体へUnmarshalし直す。
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}
