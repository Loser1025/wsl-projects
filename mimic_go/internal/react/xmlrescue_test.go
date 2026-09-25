package react

import "testing"

func TestHasXMLToolCall(t *testing.T) {
	if !hasXMLToolCall("前置き<tool_call>{}</tool_call>") {
		t.Error("tool_call パターンを検知できていない")
	}
	if hasXMLToolCall("ただのテキストです") {
		t.Error("誤検知している")
	}
}

func TestParseXMLToolCalls_FormatA_JSON(t *testing.T) {
	text := `<tool_call>{"name": "read_file", "arguments": {"path": "a.go"}}</tool_call>`
	calls := parseXMLToolCalls(text)
	if len(calls) != 1 {
		t.Fatalf("len(calls) = %d, want 1", len(calls))
	}
	if calls[0].Function.Name != "read_file" {
		t.Errorf("Name = %q, want read_file", calls[0].Function.Name)
	}
	if calls[0].Function.Arguments != `{"path":"a.go"}` {
		t.Errorf("Arguments = %q", calls[0].Function.Arguments)
	}
}

func TestParseXMLToolCalls_FormatB_FunctionInsideToolCall(t *testing.T) {
	text := `<tool_call><function=read_file><parameter=path>a.go</parameter></function></tool_call>`
	calls := parseXMLToolCalls(text)
	if len(calls) != 1 {
		t.Fatalf("len(calls) = %d, want 1", len(calls))
	}
	if calls[0].Function.Name != "read_file" {
		t.Errorf("Name = %q, want read_file", calls[0].Function.Name)
	}
	if calls[0].Function.Arguments != `{"path":"a.go"}` {
		t.Errorf("Arguments = %q", calls[0].Function.Arguments)
	}
}

func TestParseXMLToolCalls_FormatC_BareFunction(t *testing.T) {
	text := `<function=read_file><parameter=path>a.go</parameter></function>`
	calls := parseXMLToolCalls(text)
	if len(calls) != 1 {
		t.Fatalf("len(calls) = %d, want 1", len(calls))
	}
	if calls[0].Function.Name != "read_file" {
		t.Errorf("Name = %q, want read_file", calls[0].Function.Name)
	}
	if calls[0].Function.Arguments != `{"path":"a.go"}` {
		t.Errorf("Arguments = %q", calls[0].Function.Arguments)
	}
}

func TestParseXMLToolCalls_NoMatch(t *testing.T) {
	if calls := parseXMLToolCalls("ただのテキストです"); len(calls) != 0 {
		t.Errorf("len(calls) = %d, want 0", len(calls))
	}
}

func TestCoerce(t *testing.T) {
	if v := coerce("42"); v != 42 {
		t.Errorf("coerce(42) = %v (%T), want int 42", v, v)
	}
	if v := coerce("3.14"); v != 3.14 {
		t.Errorf("coerce(3.14) = %v (%T), want float64 3.14", v, v)
	}
	if v := coerce("hello"); v != "hello" {
		t.Errorf("coerce(hello) = %v (%T), want string hello", v, v)
	}
}
