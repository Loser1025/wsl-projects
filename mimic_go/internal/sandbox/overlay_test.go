package sandbox

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// newCopyModeWorkroom はDetectMode()の実地診断結果に関わらず、常にcopy-modeで
// 動くWorkroomを構築する（環境依存のoverlay可否に依存しないゴールデンテスト用）。
func newCopyModeWorkroom(t *testing.T, lower string) *Workroom {
	t.Helper()
	base := t.TempDir()
	w := &Workroom{
		Base:   base,
		Lower:  lower,
		Upper:  filepath.Join(base, "upper"),
		Work:   filepath.Join(base, "work"),
		Merged: filepath.Join(base, "merged"),
		Mode:   ModeCopy,
	}
	for _, d := range []string{w.Upper, w.Work, w.Merged} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	return w
}

func TestWorkroom_CopyMode_NewModifiedDeletedRoundTrip(t *testing.T) {
	lower := t.TempDir()
	if err := os.WriteFile(filepath.Join(lower, "b.txt"), []byte("old\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(lower, "a.txt"), []byte("keep me\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	w := newCopyModeWorkroom(t, lower)
	ctx := context.Background()

	// a.txtを削除し、b.txtを変更し、new.txtを新規作成する
	res, err := w.Run(ctx, "rm a.txt && echo new > b.txt && echo hi > new.txt", 10*time.Second)
	if err != nil {
		t.Fatalf("Run failed: %v", err)
	}
	if res.TimedOut || res.ExitCode != 0 {
		t.Fatalf("Run結果が異常: %+v", res)
	}

	changed, err := w.ChangedFiles()
	if err != nil {
		t.Fatalf("ChangedFiles failed: %v", err)
	}
	wantChanged := map[string]bool{"b.txt": true, "new.txt": true}
	if len(changed) != len(wantChanged) {
		t.Fatalf("changed = %v, want keys of %v", changed, wantChanged)
	}
	for _, f := range changed {
		if !wantChanged[f] {
			t.Errorf("想定外の変更ファイル: %s", f)
		}
	}

	if err := ApplyChanges(w, changed); err != nil {
		t.Fatalf("ApplyChanges failed: %v", err)
	}

	if _, err := os.Stat(filepath.Join(lower, "a.txt")); !os.IsNotExist(err) {
		t.Errorf("a.txtが削除されていない (err=%v)", err)
	}
	data, err := os.ReadFile(filepath.Join(lower, "b.txt"))
	if err != nil || string(data) != "new\n" {
		t.Errorf("b.txt = %q, err=%v, want %q", data, err, "new\n")
	}
	data, err = os.ReadFile(filepath.Join(lower, "new.txt"))
	if err != nil || string(data) != "hi\n" {
		t.Errorf("new.txt = %q, err=%v, want %q", data, err, "hi\n")
	}
}

func TestWorkroom_ModeNote_CopyModeWarns(t *testing.T) {
	lower := t.TempDir()
	w := newCopyModeWorkroom(t, lower)
	if got := w.ModeNote(); got == "" {
		t.Error("copy-modeなのにModeNoteが空文字だった")
	}
}

func TestWorkroom_ModeNote_SkippedSymlinksWarns(t *testing.T) {
	lower := t.TempDir()
	if err := os.WriteFile(filepath.Join(lower, "real.txt"), []byte("x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(lower, "real.txt"), filepath.Join(lower, "link.txt")); err != nil {
		t.Skipf("この環境ではsymlinkを作成できない: %v", err)
	}

	w := newCopyModeWorkroom(t, lower)
	if _, err := w.Run(context.Background(), "true", 5*time.Second); err != nil {
		t.Fatalf("Run failed: %v", err)
	}
	note := w.ModeNote()
	if !strings.Contains(note, "シンボリックリンク") {
		t.Errorf("symlink省略の警告が含まれていない: %q", note)
	}
}

func TestWorkroom_OverlayMode_RoundTrip(t *testing.T) {
	if cachedDetectMode() != ModeOverlay {
		t.Skip("この環境ではunshare/overlayマウントが使えないためスキップ")
	}
	lower := t.TempDir()
	if err := os.WriteFile(filepath.Join(lower, "a.txt"), []byte("hello\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	w, err := NewWorkroom(lower)
	if err != nil {
		t.Fatalf("NewWorkroom failed: %v", err)
	}
	defer w.Cleanup()

	ctx := context.Background()
	res, err := w.Run(ctx, "echo world >> a.txt", 10*time.Second)
	if err != nil || res.ExitCode != 0 {
		t.Fatalf("Run failed: err=%v res=%+v", err, res)
	}

	// overlay-modeではLower自体は実行中も一切変更されない
	data, err := os.ReadFile(filepath.Join(lower, "a.txt"))
	if err != nil || string(data) != "hello\n" {
		t.Errorf("実行前にLowerが変更されている: %q", data)
	}

	changed, err := w.ChangedFiles()
	if err != nil {
		t.Fatalf("ChangedFiles failed: %v", err)
	}
	if err := ApplyChanges(w, changed); err != nil {
		t.Fatalf("ApplyChanges failed: %v", err)
	}
	data, err = os.ReadFile(filepath.Join(lower, "a.txt"))
	if err != nil || string(data) != "hello\nworld\n" {
		t.Errorf("適用後のa.txt = %q, want %q", data, "hello\nworld\n")
	}
}
