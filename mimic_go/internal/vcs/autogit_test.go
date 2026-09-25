package vcs

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestShowHeadFile(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("gitが無い環境のためスキップ")
	}
	tmp := t.TempDir()
	g := New()
	if err := os.WriteFile(filepath.Join(tmp, "a.txt"), []byte("original\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	g.Backup(tmp)

	// バックアップ後に内容を変更する。ShowHeadFileはHEAD時点の内容を返すはず。
	if err := os.WriteFile(filepath.Join(tmp, "a.txt"), []byte("changed\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	content, ok := g.ShowHeadFile(tmp, "a.txt")
	if !ok {
		t.Fatal("ShowHeadFile should succeed")
	}
	if string(content) != "original\n" {
		t.Errorf("content = %q, want %q", content, "original\n")
	}

	if _, ok := g.ShowHeadFile(tmp, "nope.txt"); ok {
		t.Error("存在しないパスなのにok=trueになった")
	}
}

func TestShowHeadFile_NotGitRepo(t *testing.T) {
	tmp := t.TempDir()
	g := New()
	if _, ok := g.ShowHeadFile(tmp, "a.txt"); ok {
		t.Error("Gitリポジトリでないのにok=trueになった")
	}
}
