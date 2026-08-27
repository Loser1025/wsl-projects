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
	"sync"
	"syscall"
	"time"
)

// applyMu はApplyChangesの実行を全体で1件ずつに直列化する（Python版
// team.py::_apply_lock の移植）。delegate_to_team_parallel等が複数goroutineから
// 同じprojectDirへ同時にApplyChangesを呼ぶと、ファイルコピーの競合や
// 中途半端な適用状態が起こりうるため。
var applyMu sync.Mutex

// applyExcludedPaths はapply対象から除外する内部管理ファイル
// （Python版 subagent.py::_APPLY_EXCLUDED_PATHS の移植）。
var applyExcludedPaths = map[string]bool{
	".mimic_checkpoint.json": true,
}

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

	Mode Mode // overlay/copyのいずれで動作するか（NewWorkroom時に一度だけ実地診断）

	copyInitialized bool // copy-mode時、Merged初期化（Lowerの全コピー）を済ませたか
}

// detectedMode はDetectMode()の実地診断結果をプロセス内でキャッシュする
// （診断自体が最大15秒かかるため、委任のたびに毎回実行しない）。
var (
	detectModeOnce sync.Once
	detectedMode   Mode
)

func cachedDetectMode() Mode {
	detectModeOnce.Do(func() { detectedMode = DetectMode() })
	return detectedMode
}

// NewWorkroom はprojectDirをlowerdirとして参照するworkroomを作成する。
// lowerdirはprojectDirを直接使う（Python版と同じくコピーしない。書き込みは
// upperdirにしか反映されないため、lowerdir=projectDir自体は unshare 内の
// mount操作でのみ変更されうるが、ホスト側namespaceには影響しない）。
// unshare/user namespaceが使えない環境では、実地診断（cachedDetectMode）に
// 基づき自動的にcopy-modeへフォールバックする
// （Python版 subagent.py::_detect_sandbox_mode の移植。以前はGo版で
// DetectModeが定義されているのに一度も呼ばれないデッドコードだった）。
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
		Mode:   cachedDetectMode(),
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
	if w.Mode == ModeCopy {
		return w.runCopy(ctx, command, timeout)
	}
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

// runCopy はunshare/overlayが使えない環境向けのフォールバック実行方式
// （Python版 subagent.py の copy-mode の移植）。隔離度は落ちる
// （名前空間分離が無く、コマンドはホストのプロセス空間で直接動く）が、
// 委任機能自体を完全に無効化するよりはマシという判断。初回呼び出し時に
// LowerをMergedへ丸ごとコピーし、以降はMerged上で直接コマンドを実行する。
func (w *Workroom) runCopy(ctx context.Context, command string, timeout time.Duration) (RunResult, error) {
	if !w.copyInitialized {
		if err := copyTree(w.Lower, w.Merged); err != nil {
			return RunResult{}, fmt.Errorf("copy-modeの初期コピーに失敗しました: %w", err)
		}
		w.copyInitialized = true
	}

	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.Command("bash", "-c", command)
	cmd.Dir = w.Merged
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
		if cmd.Process != nil {
			if pgid, pgErr := syscall.Getpgid(cmd.Process.Pid); pgErr == nil {
				syscall.Kill(-pgid, syscall.SIGKILL)
			}
		}
		<-done
		return RunResult{Output: outBuf.String(), TimedOut: true}, nil
	}

	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			exitCode = -1
		}
	}

	changed, walkErr := changedFilesCopy(w.Lower, w.Merged)
	if walkErr != nil {
		return RunResult{Output: outBuf.String(), ExitCode: exitCode}, walkErr
	}
	return RunResult{Output: outBuf.String(), ExitCode: exitCode, ChangedFiles: changed}, nil
}

// copyTree はsrc配下をdstへ再帰コピーする（copy-modeの初期化用）。
func copyTree(src, dst string) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, info.Mode().Perm()|0o700)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return nil // シンボリックリンクは対象外（overlayモードとの挙動差だが実害は小さい）
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		return os.WriteFile(target, data, info.Mode().Perm())
	})
}

// changedFilesCopy はMerged側を走査し、Lower側と内容が異なる/新規のファイルを
// 変更ファイルとして返す（copy-mode版のchangedFiles相当）。
func changedFilesCopy(lower, merged string) ([]string, error) {
	var changed []string
	err := filepath.Walk(merged, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(merged, path)
		if err != nil {
			return nil
		}
		mergedData, err := os.ReadFile(path)
		if err != nil {
			return nil
		}
		lowerData, lowerErr := os.ReadFile(filepath.Join(lower, rel))
		if lowerErr != nil || string(lowerData) != string(mergedData) {
			changed = append(changed, rel)
		}
		return nil
	})
	return changed, err
}

// deletedFilesCopy はLower側を走査し、Merged側に存在しなくなったファイルを
// 削除分として返す（copy-mode版のdeletedFiles相当）。
func deletedFilesCopy(lower, merged string) ([]string, error) {
	var deleted []string
	err := filepath.Walk(lower, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(lower, path)
		if err != nil {
			return nil
		}
		if _, statErr := os.Stat(filepath.Join(merged, rel)); os.IsNotExist(statErr) {
			deleted = append(deleted, rel)
		}
		return nil
	})
	return deleted, err
}

// ChangedFiles はその時点までの累積の変更/新規ファイル一覧を返す。
// Runを複数回呼んだ後でも、Upper（またはcopy-modeのMerged）は各回の変更が
// 実ディスク上に積み重なっているため、都度これを呼べば最新の累積差分が取れる
// （verify失敗リトライで同じWorkroomに対しRunを繰り返す委任フローで使う）。
func (w *Workroom) ChangedFiles() ([]string, error) {
	if w.Mode == ModeCopy {
		return changedFilesCopy(w.Lower, w.Merged)
	}
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

// deletedFiles はupperdir内のwhiteoutマーカー（overlayfsの削除表現、
// キャラクタデバイスファイルとして現れる）を走査し、削除された相対パス
// 一覧を返す（Python版 subagent.py::apply_subagent_changes のwhiteout走査部分の移植）。
func deletedFiles(upper string) ([]string, error) {
	var deleted []string
	err := filepath.Walk(upper, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.Mode()&os.ModeCharDevice == 0 {
			return nil
		}
		rel, err := filepath.Rel(upper, path)
		if err != nil {
			return nil
		}
		deleted = append(deleted, rel)
		return nil
	})
	return deleted, err
}

// ApplyChanges はupperdir上の変更をprojectDir(lower)にコピーで反映し、
// whiteout(削除マーカー)に対応するファイルをlower側からも削除する
// （Python版 apply_subagent_changes の移植）。.mimic_checkpoint.json等の
// 内部管理ファイルはapplyExcludedPathsにより対象から除外する。
// 複数goroutineから同じprojectDirへ並行してApplyChangesが呼ばれても
// コピー処理が競合しないよう、全体を1件ずつに直列化する
// （Python版 team.py::_apply_lock の移植）。
func ApplyChanges(w *Workroom, changedFiles []string) error {
	applyMu.Lock()
	defer applyMu.Unlock()

	// copy-modeではUpperが存在しないため、変更の出所はMergedになる
	// （overlay-modeはUpperのみに差分が残るのに対し、copy-modeはMerged全体が
	// Lowerのコピー+変更後の状態そのもの）。
	sourceDir := w.Upper
	if w.Mode == ModeCopy {
		sourceDir = w.Merged
	}

	for _, rel := range changedFiles {
		if applyExcludedPaths[rel] {
			continue
		}
		src := filepath.Join(sourceDir, rel)
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

	var deleted []string
	var err error
	if w.Mode == ModeCopy {
		deleted, err = deletedFilesCopy(w.Lower, w.Merged)
	} else {
		deleted, err = deletedFiles(w.Upper)
	}
	if err != nil {
		return err
	}
	for _, rel := range deleted {
		if applyExcludedPaths[rel] {
			continue
		}
		dst := filepath.Join(w.Lower, rel)
		if rmErr := os.Remove(dst); rmErr != nil && !os.IsNotExist(rmErr) {
			return rmErr
		}
	}
	return nil
}
