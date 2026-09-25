package delegate

import "testing"

func TestCheckWriteInterlock_BelowThreshold(t *testing.T) {
	noteReadonlyDelegation() // reset
	noteWriteDelegation([]string{"a.go"}, nil)
	noteWriteDelegation([]string{"a.go"}, nil)
	if got := checkWriteInterlock(); got != "" {
		t.Errorf("threshold未満なのにブロックされた: %q", got)
	}
}

func TestCheckWriteInterlock_OverlappingStreakBlocks(t *testing.T) {
	noteReadonlyDelegation() // reset
	noteWriteDelegation([]string{"a.go", "b.go"}, nil)
	noteWriteDelegation([]string{"b.go", "c.go"}, nil)
	noteWriteDelegation([]string{"c.go"}, nil)
	got := checkWriteInterlock()
	if got == "" {
		t.Fatal("重複ファイルへの連続書き込みなのにブロックされなかった")
	}
}

func TestCheckWriteInterlock_DisjointStreakAllows(t *testing.T) {
	noteReadonlyDelegation() // reset
	noteWriteDelegation([]string{"a.go"}, nil)
	noteWriteDelegation([]string{"b.go"}, nil)
	noteWriteDelegation([]string{"c.go"}, nil)
	if got := checkWriteInterlock(); got != "" {
		t.Errorf("重複の無い書き込みなのにブロックされた: %q", got)
	}
}

func TestCheckWriteInterlock_SameExitCodeDisjointFilesBlocks(t *testing.T) {
	noteReadonlyDelegation() // reset
	exitCode := 1
	noteWriteDelegation([]string{"a.go"}, &exitCode)
	noteWriteDelegation([]string{"b.go"}, &exitCode)
	noteWriteDelegation([]string{"c.go"}, &exitCode)
	if got := checkWriteInterlock(); got == "" {
		t.Fatal("ファイルは違うが同じexit codeを繰り返しているのにブロックされなかった")
	}
}

func TestCheckWriteInterlock_DifferentExitCodesDisjointFilesAllows(t *testing.T) {
	noteReadonlyDelegation() // reset
	e1, e2, e3 := 1, 2, 1
	noteWriteDelegation([]string{"a.go"}, &e1)
	noteWriteDelegation([]string{"b.go"}, &e2)
	noteWriteDelegation([]string{"c.go"}, &e3)
	if got := checkWriteInterlock(); got != "" {
		t.Errorf("ファイルもexit codeも揺れているのにブロックされた: %q", got)
	}
}

func TestCheckWriteInterlock_ZeroExitCodeNeverBlocksByExit(t *testing.T) {
	noteReadonlyDelegation() // reset
	e0 := 0
	noteWriteDelegation([]string{"a.go"}, &e0)
	noteWriteDelegation([]string{"b.go"}, &e0)
	noteWriteDelegation([]string{"c.go"}, &e0)
	if got := checkWriteInterlock(); got != "" {
		t.Errorf("exit=0(成功)の繰り返しでブロックされた: %q", got)
	}
}

func TestNoteReadonlyDelegation_ResetsStreak(t *testing.T) {
	noteReadonlyDelegation()
	noteWriteDelegation([]string{"a.go"}, nil)
	noteWriteDelegation([]string{"a.go"}, nil)
	noteWriteDelegation([]string{"a.go"}, nil)
	if checkWriteInterlock() == "" {
		t.Fatal("前提条件エラー: この時点でブロックされているはず")
	}
	noteReadonlyDelegation()
	if got := checkWriteInterlock(); got != "" {
		t.Errorf("noteReadonlyDelegation後もブロックされたまま: %q", got)
	}
}
