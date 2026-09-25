package react

import "testing"

func TestNormalizeToolCallKey_PathTrailingSlashIgnored(t *testing.T) {
	a := normalizeToolCallKey("read_file", `{"path": "/tmp/proj/a.go"}`)
	b := normalizeToolCallKey("read_file", `{"path": "/tmp/proj/a.go/"}`)
	if a != b {
		t.Errorf("末尾スラッシュの有無で別キー扱いになった: %q != %q", a, b)
	}
}

func TestNormalizeToolCallKey_ArgOrderIgnored(t *testing.T) {
	a := normalizeToolCallKey("run_bash", `{"command":"go test","working_directory":"/tmp/proj"}`)
	b := normalizeToolCallKey("run_bash", `{"working_directory":"/tmp/proj","command":"go test"}`)
	if a != b {
		t.Errorf("引数順の違いで別キー扱いになった: %q != %q", a, b)
	}
}

func TestNormalizeToolCallKey_DifferentContentDiffers(t *testing.T) {
	a := normalizeToolCallKey("read_file", `{"path": "/tmp/proj/a.go"}`)
	b := normalizeToolCallKey("read_file", `{"path": "/tmp/proj/b.go"}`)
	if a == b {
		t.Errorf("異なるパスなのに同一キーになった: %q", a)
	}
}

func TestNormalizeToolCallKey_InvalidJSONFallsBackToRaw(t *testing.T) {
	got := normalizeToolCallKey("read_file", "not json")
	want := "read_file|not json"
	if got != want {
		t.Errorf("normalizeToolCallKey = %q, want %q", got, want)
	}
}
