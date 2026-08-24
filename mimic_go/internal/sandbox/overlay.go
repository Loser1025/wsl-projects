// Package sandbox はOverlayFS+unshareによる隔離実行を実装する
// （Python版 subagent.py の縮小移植。run_subagent_reviewable が担っていた
// 「Worker(python3 -m mimic_tui --auto-prompt)の自動起動・検証マーカー・
// クラッシュ再開・チェックポイント」等のオーケストレーション層はteam.pyと
// 合わせて別途大規模な移植が必要なため対象外とし、ここでは隔離プリミティブ
// （workroom作成→サンドボックス内でのコマンド実行→差分抽出→適用/破棄）
// のみを実装する。
//
// Python版と同じくunshare(2)/mount(2)のsyscall直叩きではなく、`unshare`/
// `mount`コマンドをsubprocessで外部呼び出しする方式を踏襲する
// （実機確認済み: subagent.py は syscall直叩きではなかった）。
package sandbox

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

// Mode はサンドボックスの実行方式。
type Mode string

const (
	ModeOverlay Mode = "overlay" // unshare + OverlayFS隔離
	ModeCopy    Mode = "copy"    // 隔離不可環境向けフォールバック（実コピー+差分比較）
)

// DetectMode はunshare+overlayマウントが使える環境かを使い捨てディレクトリで
// 実地診断する（Python版 _detect_sandbox_mode の移植）。失敗時は "copy" を返す
// （隔離強度は落ちるが委任自体を全滅させないためのフォールバック）。
func DetectMode() Mode {
	tmp, err := os.MkdirTemp("", "mimic_sandbox_check_")
	if err != nil {
		return ModeCopy
	}
	defer os.RemoveAll(tmp)

	lower := filepath.Join(tmp, "l")
	upper := filepath.Join(tmp, "u")
	work := filepath.Join(tmp, "w")
	merged := filepath.Join(tmp, "m")
	for _, d := range []string{lower, upper, work, merged} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return ModeCopy
		}
	}

	script := fmt.Sprintf(
		"mount -t overlay overlay -o lowerdir=%s,upperdir=%s,workdir=%s %s && echo MIMIC_SANDBOX_OK",
		shellQuote(lower), shellQuote(upper), shellQuote(work), shellQuote(merged))

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "unshare", "-U", "-m", "-r", "bash", "-c", script)
	out, err := cmd.CombinedOutput()
	if err == nil && strings.Contains(string(out), "MIMIC_SANDBOX_OK") {
		return ModeOverlay
	}
	return ModeCopy
}

func shellQuote(s string) string {
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}

// Workroom は1回の隔離実行に使う作業ディレクトリ一式。
type Workroom struct {
	Base   string // 全体を包む一時ディレクトリ（Cleanupで丸ごと削除）
	Lower  string // 元プロジェクト（読み取り専用として扱う。symlinkではなくbind的にunshare内でmountする）
	Upper  string // 書き込み層（変更差分がここに残る）
	Work   string // overlayfsの内部work dir
	Merged string // 合成ビュー（サンドボックス内の作業ディレクトリ）
}

// NewWorkroom はprojectDirをlowerdirとして参照するworkroomを作成する。
// lowerdirはprojectDirを直接使う（Python版と同じくコピーしない。書き込みは
// upperdirにしか反映されないため、lowerdir=projectDir自体は unshare 内の
// mount操作でのみ変更されうるが、ホスト側namespaceには影響しない）。
func NewWorkroom(projectDir string) (*Workroom, error) {
	absProject, err := filepath.Abs(projectDir)
	if err != nil {
		return nil, err
	}
	base, err := os.MkdirTemp("", "mimic_workroom_")
	if err != nil {
		return nil, err
	}
	w := &Workroom{
		Base:   base,
		Lower:  absProject,
		Upper:  filepath.Join(base, "upper"),
		Work:   filepath.Join(base, "work"),
		Merged: filepath.Join(base, "merged"),
	}
	for _, d := range []string{w.Upper, w.Work, w.Merged} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			os.RemoveAll(base)
			return nil, err
		}
	}
	return w, nil
}

// Cleanup はworkroom一式を破棄する（overlay内部のworkディレクトリはmode 0000で
// 生成されることがあるため、削除前に権限を戻してから rmtree する）。
func (w *Workroom) Cleanup() {
	filepath.Walk(w.Base, func(path string, info os.FileInfo, err error) error {
		if err == nil && info.IsDir() {
			os.Chmod(path, 0o700)
		}
		return nil
	})
	os.RemoveAll(w.Base)
}

// RunResult は隔離実行1回分の結果。
type RunResult struct {
	Output       string
	ExitCode     int
	TimedOut     bool
	ChangedFiles []string // upperdir内の変更/新規ファイル（プロジェクトルートからの相対パス）
}

// Run はworkroom内でunshare+overlayマウントを行い、その合成ビュー(Merged)を
// カレントディレクトリとしてcommandをbashで実行する。実行後、名前空間終了と
// 同時にマウントは自動解除される（後始末不要）。戻り値のChangedFilesは
// upperdir走査で得た変更/新規ファイルの相対パス一覧。
func (w *Workroom) Run(ctx context.Context, command string, timeout time.Duration) (RunResult, error) {
	marker := "MIMIC_SANDBOX_EXIT:"
	script := fmt.Sprintf(
		"set -o pipefail\n"+
			"mount -t overlay overlay -o lowerdir=%s,upperdir=%s,workdir=%s %s || { echo MOUNT_FAILED; exit 90; }\n"+
			"cd %s\n"+
			"%s\n"+
			"echo %s$?\n",
		shellQuote(w.Lower), shellQuote(w.Upper), shellQuote(w.Work), shellQuote(w.Merged),
		shellQuote(w.Merged), command, marker)

	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.Command("unshare", "-U", "-m", "-r", "bash", "-c", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	var outBuf strings.Builder
	cmd.Stdout = &outBuf
	cmd.Stderr = &outBuf
	if err := cmd.Start(); err != nil {
		return RunResult{}, err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	var err error
	select {
	case err = <-done:
	case <-runCtx.Done():
		// unshare自体をkillしてもbash配下の孫プロセス(sleep等)まで届くとは
		// 限らないため、プロセスグループ全体をSIGKILLする
		// （internal/tools/shell.goのkillProcessGroupと同じ方針）。
		if cmd.Process != nil {
			if pgid, pgErr := syscall.Getpgid(cmd.Process.Pid); pgErr == nil {
				syscall.Kill(-pgid, syscall.SIGKILL)
			}
		}
		<-done // プロセス終了(Wait復帰)を待ってからゾンビ化を防ぐ
		return RunResult{Output: outBuf.String(), TimedOut: true}, nil
	}
	output := outBuf.String()
	if strings.Contains(output, "MOUNT_FAILED") {
		return RunResult{Output: output}, fmt.Errorf("overlayマウントに失敗しました（unshare/user namespace非対応環境の可能性）")
	}

	exitCode := 0
	if idx := strings.LastIndex(output, marker); idx >= 0 {
		fmt.Sscanf(output[idx+len(marker):], "%d", &exitCode)
		output = strings.TrimSpace(output[:idx])
	} else if err != nil {
		exitCode = -1
	}

	changed, walkErr := changedFiles(w.Upper)
	if walkErr != nil {
		return RunResult{Output: output, ExitCode: exitCode}, walkErr
	}
	return RunResult{Output: output, ExitCode: exitCode, ChangedFiles: changed}, nil
}

// ChangedFiles はupperdirを走査し、その時点までの累積の変更/新規ファイル
// 一覧を返す。Runを複数回呼んだ後でも、upperdirは各回の変更が実ディスク上に
// 積み重なっているため、都度これを呼べば最新の累積差分が取れる
// （verify失敗リトライで同じWorkroomに対しRunを繰り返す委任フローで使う）。
func (w *Workroom) ChangedFiles() ([]string, error) {
	return changedFiles(w.Upper)
}

// changedFiles はupperdirを走査し、変更/新規ファイルの相対パス一覧を返す。
func changedFiles(upper string) ([]string, error) {
	var changed []string
	err := filepath.Walk(upper, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(upper, path)
		if err != nil {
			return nil
		}
		// overlayのwhiteout(削除マーカー)はキャラクタデバイスファイルとして
		// 現れる。Go標準のos.FileInfoからは種別を判定しづらいため、
		// サイズ0かつModeがchardeviceかで判定する簡易版とする。
		if info.Mode()&os.ModeCharDevice != 0 {
			return nil
		}
		changed = append(changed, rel)
		return nil
	})
	return changed, err
}

// ApplyChanges はupperdir上の変更を projectDir(lower) にコピーで反映する。
func ApplyChanges(w *Workroom, changedFiles []string) error {
	for _, rel := range changedFiles {
		src := filepath.Join(w.Upper, rel)
		dst := filepath.Join(w.Lower, rel)
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return err
		}
		data, err := os.ReadFile(src)
		if err != nil {
			return err
		}
		if err := os.WriteFile(dst, data, 0o644); err != nil {
			return err
		}
	}
	return nil
}
