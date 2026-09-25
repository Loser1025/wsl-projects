package delegate

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"mimic/internal/vcs"
)

func TestBestOfNAttempts_EmptyVerifyCmd_Default(t *testing.T) {
	if got := bestOfNAttempts("/anywhere", ""); got != BestOfNFallbackAttemptsDefault {
		t.Errorf("got %d, want default %d", got, BestOfNFallbackAttemptsDefault)
	}
}

func TestBestOfNAttempts_NoLearning_Default(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)
	if got := bestOfNAttempts(tmp, "go test ./..."); got != BestOfNFallbackAttemptsDefault {
		t.Errorf("got %d, want default %d", got, BestOfNFallbackAttemptsDefault)
	}
}

func TestBestOfNAttempts_DifferentVerifyCmd_Default(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)
	SaveLearnedVerifyCmd(tmp, "go test ./...")
	NoteVerifyCmdFailure(tmp, "go test ./...")
	NoteVerifyCmdFailure(tmp, "go test ./...")
	if got := bestOfNAttempts(tmp, "go build ./..."); got != BestOfNFallbackAttemptsDefault {
		t.Errorf("got %d, want default %d", got, BestOfNFallbackAttemptsDefault)
	}
}

func TestBestOfNAttempts_UnstableVerifyCmd_Max(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)
	SaveLearnedVerifyCmd(tmp, "go test ./...")
	NoteVerifyCmdFailure(tmp, "go test ./...")
	NoteVerifyCmdFailure(tmp, "go test ./...") // Fails=2 > Passes=1（閾値2未満のため学習自体はまだ残る）
	if got := bestOfNAttempts(tmp, "go test ./..."); got != BestOfNFallbackAttemptsMax {
		t.Errorf("got %d, want max %d", got, BestOfNFallbackAttemptsMax)
	}
}

func TestConflictContentDiffers_NoAutoGit_DefaultsToTrue(t *testing.T) {
	old := teamAutoGit
	teamAutoGit = nil
	defer func() { teamAutoGit = old }()
	if !conflictContentDiffers("/anywhere", "a.txt", []byte("x")) {
		t.Error("teamAutoGit未設定ならtrue(=mtimeのみで警告)を返すはず")
	}
}

func TestConflictContentDiffers_WithGit(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("gitが無い環境のためスキップ")
	}
	tmp := t.TempDir()
	if err := os.WriteFile(filepath.Join(tmp, "a.txt"), []byte("hello\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	g := vcs.New()
	g.Backup(tmp)

	old := teamAutoGit
	teamAutoGit = g
	defer func() { teamAutoGit = old }()

	if conflictContentDiffers(tmp, "a.txt", []byte("hello\n")) {
		t.Error("HEADと同じ内容なのにdiffers=trueになった")
	}
	if !conflictContentDiffers(tmp, "a.txt", []byte("changed\n")) {
		t.Error("HEADと異なる内容なのにdiffers=falseになった")
	}
}
