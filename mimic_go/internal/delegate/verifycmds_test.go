package delegate

import (
	"os"
	"path/filepath"
	"testing"
)

func TestVerifyCmdLearning_RoundTrip(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)

	if got := GetLearnedVerifyCmd(tmp); got != "" {
		t.Fatalf("初期状態で学習済みコマンドが返された: %q", got)
	}

	SaveLearnedVerifyCmd(tmp, "go test ./...")
	if got := GetLearnedVerifyCmd(tmp); got != "go test ./..." {
		t.Errorf("GetLearnedVerifyCmd = %q, want %q", got, "go test ./...")
	}

	// 同一コマンドを再度保存すると通過回数が加算される
	SaveLearnedVerifyCmd(tmp, "go test ./...")
	data := loadVerifyCmds()
	entry, ok := data[verifyCmdKey(tmp)]
	if !ok || entry.Passes != 2 {
		t.Errorf("entry = %+v, ok=%v, want Passes=2", entry, ok)
	}

	ForgetLearnedVerifyCmd(tmp, "go test ./...")
	if got := GetLearnedVerifyCmd(tmp); got != "" {
		t.Errorf("Forget後も学習済みコマンドが残っている: %q", got)
	}
}

func TestNoteVerifyCmdFailure_NoPriorLearning_NoOp(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)
	if forgotten := NoteVerifyCmdFailure(tmp, "go test ./..."); forgotten {
		t.Error("未学習のverify_cmdなのにforgotten=trueになった")
	}
}

func TestNoteVerifyCmdFailure_ThresholdForgets(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)
	SaveLearnedVerifyCmd(tmp, "go test ./...")

	if forgotten := NoteVerifyCmdFailure(tmp, "go test ./..."); forgotten {
		t.Error("1回目の失敗で即座に忘れてしまった")
	}
	if got := GetLearnedVerifyCmd(tmp); got != "go test ./..." {
		t.Errorf("1回目の失敗後も学習は残っているはず: got %q", got)
	}

	if forgotten := NoteVerifyCmdFailure(tmp, "go test ./..."); forgotten {
		t.Error("2回目の失敗で即座に忘れてしまった")
	}

	if forgotten := NoteVerifyCmdFailure(tmp, "go test ./..."); !forgotten {
		t.Error("3回目の失敗でも忘れられなかった")
	}
	if got := GetLearnedVerifyCmd(tmp); got != "" {
		t.Errorf("閾値到達後は学習が破棄されているはず: got %q", got)
	}
}

func TestNoteVerifyCmdFailure_PassResetsFails(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)
	SaveLearnedVerifyCmd(tmp, "go test ./...")
	NoteVerifyCmdFailure(tmp, "go test ./...")
	NoteVerifyCmdFailure(tmp, "go test ./...")
	SaveLearnedVerifyCmd(tmp, "go test ./...") // 通過でFailsがリセットされる
	if forgotten := NoteVerifyCmdFailure(tmp, "go test ./..."); forgotten {
		t.Error("通過直後の1回の失敗で忘れてしまった（Failsがリセットされていない）")
	}
}

func TestTemplateVerifyCmd(t *testing.T) {
	tmp := t.TempDir()
	if got := TemplateVerifyCmd(tmp); got != "" {
		t.Fatalf("マニフェスト無しでテンプレートが返された: %q", got)
	}
	if err := os.WriteFile(filepath.Join(tmp, "go.mod"), []byte("module x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := TemplateVerifyCmd(tmp); got != "go test ./..." {
		t.Errorf("TemplateVerifyCmd = %q, want %q", got, "go test ./...")
	}
}

func TestStaticCheckCmd(t *testing.T) {
	tmp := t.TempDir()
	if err := os.WriteFile(filepath.Join(tmp, "go.mod"), []byte("module x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := StaticCheckCmd(tmp); got != "go build ./..." {
		t.Errorf("StaticCheckCmd = %q, want %q", got, "go build ./...")
	}
}
