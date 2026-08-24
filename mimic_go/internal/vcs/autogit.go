// Package vcs はタスク実行時の安全ネット（AutoGit）を実装する
// （Python版 autogit.py::AutoGit の移植。ReactLog(セッションJSONL/md出力)
// は別バッチの範囲とし、本バッチではAutoGitのbackup/checkpoint/
// rollback/squash/diffのみを対象とする）。
package vcs

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// AutoGit はタスク開始前のバックアップコミットと、書き込み系ツール成功後の
// チェックポイントコミットを管理する。goroutineセーフではない前提
// （react.RunTurnは1ターンにつき1goroutineでのみ呼ばれるため問題ない）。
type AutoGit struct {
	lastBackupHash string
	checkpoints    []string
}

func New() *AutoGit {
	return &AutoGit{}
}

func (g *AutoGit) runGit(args []string, cwd string) (int, string, string) {
	cmd := exec.Command("git", args...)
	cmd.Dir = cwd
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	done := make(chan error, 1)
	if err := cmd.Start(); err != nil {
		if os.IsNotExist(err) {
			return -1, "", "git が見つかりません（Git未インストール）"
		}
		return -1, "", err.Error()
	}
	go func() { done <- cmd.Wait() }()

	select {
	case err := <-done:
		rc := 0
		if err != nil {
			if exitErr, ok := err.(*exec.ExitError); ok {
				rc = exitErr.ExitCode()
			} else {
				rc = -1
			}
		}
		return rc, strings.TrimSpace(stdout.String()), strings.TrimSpace(stderr.String())
	case <-time.After(30 * time.Second):
		_ = cmd.Process.Kill()
		return -1, "", "git コマンドがタイムアウトしました"
	}
}

func (g *AutoGit) isGitRepo(cwd string) bool {
	rc, _, _ := g.runGit([]string{"rev-parse", "--git-dir"}, cwd)
	return rc == 0
}

func (g *AutoGit) hasChanges(cwd string) bool {
	rc, out, _ := g.runGit([]string{"status", "--porcelain"}, cwd)
	if rc != 0 {
		return false
	}
	return strings.TrimSpace(out) != ""
}

func (g *AutoGit) getHead(cwd string) string {
	rc, out, _ := g.runGit([]string{"rev-parse", "HEAD"}, cwd)
	if rc != 0 {
		return ""
	}
	return out
}

func (g *AutoGit) ensureGitUser(cwd string) {
	rc, out, _ := g.runGit([]string{"config", "user.email"}, cwd)
	if rc != 0 || out == "" {
		g.runGit([]string{"config", "user.email", "agent@mimic"}, cwd)
		g.runGit([]string{"config", "user.name", "mimic-agent"}, cwd)
	}
}

func shortHash(h string) string {
	if len(h) >= 8 {
		return h[:8]
	}
	if h == "" {
		return "?"
	}
	return h
}

// Backup はタスク開始前のバックアップコミットを作成する
// （react.RunTurn の各ターン冒頭で呼ばれる想定）。
func (g *AutoGit) Backup(cwd string) string {
	if !g.isGitRepo(cwd) {
		if rc, _, err := g.runGit([]string{"init"}, cwd); rc != 0 {
			return fmt.Sprintf("git init 失敗: %s", err)
		}
		gitignorePath := filepath.Join(cwd, ".gitignore")
		if _, err := os.Stat(gitignorePath); os.IsNotExist(err) {
			_ = os.WriteFile(gitignorePath, []byte("__pycache__/\n*.pyc\n*.pyo\n*.log\n"), 0o644)
		}
	}

	if !g.hasChanges(cwd) {
		g.lastBackupHash = g.getHead(cwd)
		return "変更なし。バックアップをスキップ。"
	}

	g.ensureGitUser(cwd)
	g.runGit([]string{"add", "."}, cwd)
	rc, _, err := g.runGit([]string{"commit", "-m", "🤖 mimic-agent: backup before task"}, cwd)
	if rc == 0 {
		g.lastBackupHash = g.getHead(cwd)
		g.checkpoints = nil
		return fmt.Sprintf("バックアップ完了: %s", shortHash(g.lastBackupHash))
	}
	return fmt.Sprintf("バックアップ失敗: %s", err)
}

// Checkpoint は書き込み系ツール成功後の自動チェックポイントコミット。
func (g *AutoGit) Checkpoint(cwd, tool, path string) {
	if !g.isGitRepo(cwd) || !g.hasChanges(cwd) {
		return
	}
	g.ensureGitUser(cwd)
	fileName := ""
	if path != "" {
		fileName = filepath.Base(path)
	}
	msg := fmt.Sprintf("🤖 checkpoint [%s]", tool)
	if fileName != "" {
		msg += " " + fileName
	}
	g.runGit([]string{"add", "."}, cwd)
	rc, _, _ := g.runGit([]string{"commit", "-m", msg}, cwd)
	if rc == 0 {
		if h := g.getHead(cwd); h != "" {
			g.checkpoints = append(g.checkpoints, h)
		}
	}
}

// Rollback は直前のチェックポイント（またはバックアップ）に戻す。
func (g *AutoGit) Rollback(cwd string) string {
	if !g.isGitRepo(cwd) {
		return "Gitリポジトリが見つかりません。"
	}
	var target string
	if len(g.checkpoints) > 0 {
		g.checkpoints = g.checkpoints[:len(g.checkpoints)-1] // 最新チェックポイントを破棄
		if len(g.checkpoints) > 0 {
			target = g.checkpoints[len(g.checkpoints)-1]
		} else {
			target = g.lastBackupHash
		}
	} else {
		target = g.lastBackupHash
	}
	args := []string{"reset", "--hard", "HEAD~1"}
	if target != "" {
		args = []string{"reset", "--hard", target}
	}
	rc, _, err := g.runGit(args, cwd)
	if rc == 0 {
		return fmt.Sprintf("ロールバック完了: %s へ戻しました", shortHash(g.getHead(cwd)))
	}
	return fmt.Sprintf("ロールバック失敗: %s", err)
}

// Squash はこのターンのチェックポイント群を1コミットにまとめる。
func (g *AutoGit) Squash(cwd, message string) string {
	if len(g.checkpoints) == 0 {
		return ""
	}
	if !g.isGitRepo(cwd) {
		return "Gitリポジトリが見つかりません。"
	}
	target := g.lastBackupHash
	if target == "" {
		return "バックアップハッシュが見つかりません。squashをスキップ。"
	}
	if rc, _, err := g.runGit([]string{"reset", "--soft", target}, cwd); rc != 0 {
		return fmt.Sprintf("squash失敗（reset --soft）: %s", err)
	}
	g.ensureGitUser(cwd)
	if rc, _, err := g.runGit([]string{"commit", "-m", message}, cwd); rc != 0 {
		return fmt.Sprintf("squash失敗（commit）: %s", err)
	}
	h := g.getHead(cwd)
	g.checkpoints = nil
	return fmt.Sprintf("squash完了: %s — %s", shortHash(h), message)
}

// Diff はバックアップ以降の差分統計を返す。
func (g *AutoGit) Diff(cwd string) string {
	if !g.isGitRepo(cwd) {
		return "Gitリポジトリが見つかりません。"
	}
	if g.lastBackupHash == "" {
		return "バックアップが見つかりません（タスクを実行してください）。"
	}
	rc, out, err := g.runGit([]string{"diff", g.lastBackupHash, "HEAD", "--stat"}, cwd)
	if rc == 0 {
		return out
	}
	return fmt.Sprintf("diff 取得失敗: %s", err)
}

// WriteTools はチェックポイント対象となる書き込み系ツール名の集合
// （Python版 orchestrator.py の write_tools セットを踏襲）。
var WriteTools = map[string]bool{
	"write_file": true,
	"edit_file":  true,
	"patch_file": true,
}
