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
)

const (
	defaultBashTimeout     = 60
	defaultPipelineTimeout = 120
	maxPipelineLines       = 50000
)

// outsideWriteTargetRe はWorker実行時、リダイレクト・tee・cp/mv等で作業ディレクトリ外の
// 絶対パスへ書き込むコマンドを検出するパターン（Python版 tools_linux.py::_OUTSIDE_WRITE_TARGET_RE の移植）。
var outsideWriteTargetRe = regexp.MustCompile(`(?:>>?\s*|\btee\s+(?:-a\s+)?|\b(?:cp|mv)\s+(?:-\S+\s+)*\S+\s+)(/[^\s;|&'"<>]+)`)

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

// registerShellTools は run_bash / run_pipeline を登録する。
// Python版はrun_bashをptyで実行し対話コマンド(npm/git等)に対応しているが、
// Go版フェーズ2ではptyを使わず素直にexec.Commandで実行する簡略版とする
// （github.com/creack/pty導入は本バッチのスコープ外、既知の簡略化点）。
func registerShellTools(r *Registry) {
	r.Register("run_bash",
		"bashコマンドを実行して結果を返す。結果の先頭が[SUCCESS]なら成功、[FAILURE(ExitCode=N)]なら失敗。パイプ・リダイレクト・複数行コマンドに対応。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"command":           map[string]any{"type": "string", "description": "実行するbashコマンド。パイプ・&&・複数行可。"},
				"timeout":           map[string]any{"type": "integer", "description": "タイムアウト秒数（デフォルト60）", "default": 60},
				"working_directory": map[string]any{"type": "string", "description": "コマンドを実行する作業フォルダのフルパス（必ず指定）"},
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

func toolRunBash(args map[string]any) (string, error) {
	command := argString(args, "command")
	timeoutSec := argInt(args, "timeout", defaultBashTimeout)
	cwd := argString(args, "working_directory")

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutSec)*time.Second)
	defer cancel()

	wrapped := "export LC_ALL=C.UTF-8\nexport LANG=C.UTF-8\nexport PAGER=cat\nexport GIT_PAGER=cat\nexport GIT_TERMINAL_PROMPT=0\n" + command

	cmd := exec.CommandContext(ctx, "bash", "-c", wrapped)
	if cwd != "" {
		cmd.Dir = cwd
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf

	err := cmd.Run()
	output := strings.TrimSpace(buf.String())

	if ctx.Err() == context.DeadlineExceeded {
		killProcessGroup(cmd)
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
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
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
		lines = append(lines, scanner.Text())
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
	if stderrOut := strings.TrimSpace(stderrBuf.String()); stderrOut != "" {
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
