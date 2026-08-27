package tools

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"

	"github.com/creack/pty"
)

const (
	defaultBashTimeout     = 60
	defaultPipelineTimeout = 120
	maxPipelineLines       = 50000
)

// outsideWriteTargetRe はWorker実行時、リダイレクト・tee・cp/mv等で作業ディレクトリ外の
// 絶対パスへ書き込むコマンドを検出するパターン（Python版 tools_linux.py::_OUTSIDE_WRITE_TARGET_RE の移植）。
var outsideWriteTargetRe = regexp.MustCompile(`(?:>>?\s*|\btee\s+(?:-a\s+)?|\b(?:cp|mv)\s+(?:-\S+\s+)*\S+\s+)(/[^\s;|&'"<>]+)`)

// terminalCtrlRe はDECプライベートモード（代替画面・マウストラッキング・
// カーソルキーモード等の端末状態変更シーケンス）を検出するパターン
// （Python版 tools_linux.py::_TERMINAL_CTRL_RE の移植）。これらがそのまま
// 親ターミナルへ出力されると端末状態が壊れるため、ツール出力から除去する。
var terminalCtrlRe = regexp.MustCompile("\x1b\\[\\?[0-9;]*[hl]")

// stripTerminalControlSequences はrun_bash/run_pipelineの出力から
// 端末状態変更シーケンスを除去する。
func stripTerminalControlSequences(s string) string {
	return terminalCtrlRe.ReplaceAllString(s, "")
}

// workerOutsideWriteWarning はWorker実行時、作業ディレクトリ外への書き込みらしきコマンドを
// 検出して警告を返す（Python版 tools_linux.py::_worker_outside_write_warning の移植）。
// シェルコマンドを確実にブロックすることはできないため、検出＋警告に留める。
func workerOutsideWriteWarning(command string) string {
	if os.Getenv("MIMIC_NO_AUTOGIT") == "" {
		return ""
	}
	root, err := os.Getwd()
	if err != nil {
		return ""
	}
	root, err = filepath.Abs(root)
	if err != nil {
		return ""
	}
	var outside []string
	for _, m := range outsideWriteTargetRe.FindAllStringSubmatch(command, -1) {
		target := m[1]
		if strings.HasPrefix(target, "/dev/") || strings.HasPrefix(target, "/proc/") || strings.HasPrefix(target, "/tmp/") {
			continue
		}
		if target == root || strings.HasPrefix(target, root+"/") {
			continue
		}
		outside = append(outside, target)
	}
	if len(outside) == 0 {
		return ""
	}
	shown := outside
	if len(shown) > 5 {
		shown = shown[:5]
	}
	return fmt.Sprintf(
		"\n⚠ 警告: 作業ディレクトリ（%s）外の絶対パスへの書き込みらしき操作を検出: %s\n"+
			"この環境はOverlayFS隔離されており、外部への書き込みは差分として検出・適用されません"+
			"（プロジェクトへの変更として扱われず、Directorにも見えません）。\n"+
			"プロジェクトのファイルを変更する場合は、作業ディレクトリ内の相対パスを使用してください。",
		root, strings.Join(shown, ", "))
}

// sudoPromptRe はsudoパスワードプロンプト検出パターン（デコード後の文字列で照合。
// Python版 tools_linux.py::_SUDO_PROMPT_RE の移植）。
var sudoPromptRe = regexp.MustCompile(`\[sudo\] password for [^:]+|[Pp]assword:|パスワードを入力してください`)

// sudoPassword は環境変数SUDO_PASSWORDからパスワードを取得する
// （Python版 tools_linux.py::_sudo_password の移植。デフォルト値も同一）。
func sudoPassword() []byte {
	pw := os.Getenv("SUDO_PASSWORD")
	if pw == "" {
		pw = "1025"
	}
	return []byte(pw + "\n")
}

// registerShellTools は run_bash / run_pipeline を登録する。
func registerShellTools(r *Registry) {
	r.Register("run_bash",
		"bashコマンドを実行して結果を返す。結果の先頭が[SUCCESS]なら成功、[FAILURE(ExitCode=N)]なら失敗。パイプ・リダイレクト・複数行コマンドに対応。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"command":           map[string]any{"type": "string", "description": "実行するbashコマンド。パイプ・&&・複数行可。"},
				"timeout":           map[string]any{"type": "integer", "description": "タイムアウト秒数（デフォルト60）", "default": 60},
				"working_directory": map[string]any{"type": "string", "description": "コマンドを実行する作業フォルダのフルパス（必ず指定）"},
				"shell":             map[string]any{"type": "string", "description": "使用するシェル: bash / sh / zsh（デフォルト: bash）", "default": "bash"},
			},
			"required": []string{"command"},
		},
		toolRunBash)

	r.Register("run_pipeline",
		"Unixパイプラインコマンドを実行する。grep/awk/sort/findなど大量データを扱う処理に最適。行単位ストリーム読みのため大出力でもメモリを圧迫しない。結果の先頭が[SUCCESS]なら成功、[FAILURE...]なら失敗。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"command":           map[string]any{"type": "string", "description": "実行するシェルコマンド（パイプ・リダイレクト可）"},
				"working_directory": map[string]any{"type": "string", "description": "作業フォルダのフルパス（必ず指定）"},
				"timeout":           map[string]any{"type": "integer", "description": "タイムアウト秒数（デフォルト120）", "default": 120},
				"max_lines":         map[string]any{"type": "integer", "description": "取得する最大行数（デフォルト1000、0で無制限〈上限50000〉）", "default": 1000},
			},
			"required": []string{"command"},
		},
		toolRunPipeline)
}

// toolRunBash はptyを確保してコマンドを実行する（npm/git等の対話的コマンドに
// 対応。Python版 tools_linux.py::run_bash の移植）。sudoパスワードプロンプトを
// 検知した場合、SUDO_PASSWORD環境変数の値を最大3回まで自動入力する。
func toolRunBash(args map[string]any) (string, error) {
	command := argString(args, "command")
	timeoutSec := argInt(args, "timeout", defaultBashTimeout)
	cwd := argString(args, "working_directory")
	shellName := argString(args, "shell")
	if shellName == "" {
		shellName = "bash"
	}

	// PAGER=cat / GIT_PAGER=cat: lessなどのページャーが起動すると、代替画面
	// 等の端末制御シーケンスがpty経由で漏洩し端末状態を破壊するため無効化する。
	wrapped := "export LC_ALL=C.UTF-8\nexport LANG=C.UTF-8\nexport PAGER=cat\nexport GIT_PAGER=cat\nexport GIT_TERMINAL_PROMPT=0\n" + command

	cmd := exec.Command(shellName, "-c", wrapped)
	if cwd != "" {
		cmd.Dir = cwd
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}

	ptmx, err := pty.Start(cmd)
	if err != nil {
		return "", fmt.Errorf("pty起動エラー: %w", err)
	}
	defer ptmx.Close()

	deadline := time.Now().Add(time.Duration(timeoutSec) * time.Second)
	var outBuf bytes.Buffer
	sudoSent := 0
	timedOut := false
	readErrCh := make(chan error, 1)
	chunkCh := make(chan []byte, 16)

	go func() {
		buf := make([]byte, 4096)
		for {
			n, rerr := ptmx.Read(buf)
			if n > 0 {
				chunk := make([]byte, n)
				copy(chunk, buf[:n])
				chunkCh <- chunk
			}
			if rerr != nil {
				readErrCh <- rerr
				return
			}
		}
	}()

readLoop:
	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			timedOut = true
			break
		}
		select {
		case chunk := <-chunkCh:
			outBuf.Write(chunk)
			if sudoSent < 3 && sudoPromptRe.Match(chunk) {
				ptmx.Write(sudoPassword())
				sudoSent++
			}
		case <-readErrCh:
			break readLoop
		case <-time.After(remaining):
			timedOut = true
			break readLoop
		}
	}

	if timedOut || cmd.ProcessState == nil {
		killProcessGroup(cmd)
	}
	waitErr := cmd.Wait()

	// タイムアウト後、EOFまでの残り出力を短時間だけ拾う（プロセスは既にkill済み）。
	if !timedOut {
	drain:
		for {
			select {
			case chunk := <-chunkCh:
				outBuf.Write(chunk)
			case <-time.After(50 * time.Millisecond):
				break drain
			case <-readErrCh:
				break drain
			}
		}
	}

	raw := outBuf.String()
	raw = strings.ReplaceAll(raw, "\r\n", "\n")
	raw = strings.ReplaceAll(raw, "\r", "\n")
	output := strings.TrimSpace(stripTerminalControlSequences(raw))

	if timedOut {
		partial := "\n(出力なし)"
		if output != "" {
			partial = "\n途中出力:\n" + output
		}
		return fmt.Sprintf(
			"[TIMEOUT] %d秒経過でプロセスを強制終了しました。\n作業フォルダ: %s\n"+
				"⚠ タイムアウトですが、途中出力を分析して作業を継続してください。%s",
			timeoutSec, effectiveCwd(cwd), partial), nil
	}

	rc := 0
	if waitErr != nil {
		if exitErr, ok := waitErr.(*exec.ExitError); ok {
			rc = exitErr.ExitCode()
		} else {
			rc = -1
		}
	}
	status := "SUCCESS"
	if rc != 0 {
		status = fmt.Sprintf("FAILURE(ExitCode=%d)", rc)
	}
	parts := []string{fmt.Sprintf("[%s]", status), fmt.Sprintf("作業フォルダ: %s", effectiveCwd(cwd))}
	if output != "" {
		parts = append(parts, output)
	}
	result := strings.Join(parts, "\n")
	result += workerOutsideWriteWarning(command)
	return result, nil
}

func toolRunPipeline(args map[string]any) (string, error) {
	command := argString(args, "command")
	timeoutSec := argInt(args, "timeout", defaultPipelineTimeout)
	cwd := argString(args, "working_directory")
	maxLines := argInt(args, "max_lines", 1000)
	if maxLines <= 0 || maxLines > maxPipelineLines {
		maxLines = maxPipelineLines
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutSec)*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "/bin/bash", "-c", command)
	if cwd != "" {
		cmd.Dir = cwd
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", fmt.Errorf("パイプライン起動エラー: %w", err)
	}
	var stderrBuf bytes.Buffer
	cmd.Stderr = &stderrBuf

	if err := cmd.Start(); err != nil {
		return "", fmt.Errorf("パイプライン起動エラー: %w", err)
	}

	var lines []string
	truncated := false
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		lines = append(lines, stripTerminalControlSequences(scanner.Text()))
		if len(lines) >= maxLines {
			truncated = true
			killProcessGroup(cmd)
			break
		}
	}
	waitErr := cmd.Wait()

	if ctx.Err() == context.DeadlineExceeded {
		killProcessGroup(cmd)
		result := fmt.Sprintf("[FAILURE(TIMEOUT)] %d秒経過\n作業フォルダ: %s", timeoutSec, effectiveCwd(cwd))
		if len(lines) > 0 {
			result += fmt.Sprintf("\n途中出力(%d行):\n%s", len(lines), strings.Join(lines, "\n"))
		}
		return result, nil
	}

	rc := 0
	if waitErr != nil && !truncated {
		if exitErr, ok := waitErr.(*exec.ExitError); ok {
			rc = exitErr.ExitCode()
		} else {
			rc = -1
		}
	}
	status := "SUCCESS"
	if rc != 0 {
		status = fmt.Sprintf("FAILURE(ExitCode=%d)", rc)
	}

	note := ""
	if truncated {
		note = fmt.Sprintf("\n[表示上限 %d 行で打ち切り。続きはmax_linesを増やして再実行]", maxLines)
	}
	parts := []string{fmt.Sprintf("[%s]", status), fmt.Sprintf("作業フォルダ: %s", effectiveCwd(cwd)), fmt.Sprintf("行数: %d", len(lines))}
	if len(lines) > 0 {
		parts = append(parts, strings.Join(lines, "\n")+note)
	}
	if stderrOut := strings.TrimSpace(stripTerminalControlSequences(stderrBuf.String())); stderrOut != "" {
		parts = append(parts, "STDERR:\n"+stderrOut)
	}
	result := strings.Join(parts, "\n")
	result += workerOutsideWriteWarning(command)
	return result, nil
}

func effectiveCwd(cwd string) string {
	if cwd != "" {
		return cwd
	}
	return "(未指定)"
}

// killProcessGroup はタイムアウト/打ち切り時にプロセスグループ全体を終了する
// （子プロセスも含めてkillするため、run_bash/run_pipelineの説明文にある
// 「プロセスグループ全体を終了する」という挙動をGo側でも再現する）。
func killProcessGroup(cmd *exec.Cmd) {
	if cmd.Process == nil {
		return
	}
	pgid, err := syscall.Getpgid(cmd.Process.Pid)
	if err != nil {
		return
	}
	_ = syscall.Kill(-pgid, syscall.SIGTERM)
	time.Sleep(200 * time.Millisecond)
	_ = syscall.Kill(-pgid, syscall.SIGKILL)
}
