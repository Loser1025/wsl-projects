package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"
)

// watchPollInterval はセッションJSONLの追記分をポーリングする間隔
// （internal/vcs/procobserver.goの既定ポーリング間隔と合わせた値）。
const watchPollInterval = 300 * time.Millisecond

// watchFileAppearTimeout はtrace_idに対応するセッションJSONLが作成されるまで
// 待つ上限（委任開始からWorker起動までのラグを吸収する）。
const watchFileAppearTimeout = 30 * time.Second

// sessionEntry はinternal/vcs/reactlog.go::ReactLog.Addが書き出すJSONLの
// フラットな構造（{"type":..., "ts":..., ...}）を必要な分だけデコードする。
type sessionEntry struct {
	Type    string          `json:"type"`
	Tool    string          `json:"tool"`
	Args    json.RawMessage `json:"args"`
	Result  string          `json:"result"`
	Content json.RawMessage `json:"content"`
}

// runWatch は `mimic watch <trace_id> [project_dir]` を実装する。
// <project_dir>/.mimic/sessions/trace-<trace_id>.jsonl をpollベースでtailし、
// 追記されたイベントを整形して標準出力へ流し続ける
// （internal/vcs/reactlog.go::Addは毎回open→write→closeのため、追記は
// 即座にファイルへ反映される——tail -f相当の追従で十分）。
// final_answerイベントを検知するか、Ctrl+C/SIGTERMで終了する。
func runWatch(args []string) {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "使い方: mimic watch <trace_id> [project_dir]")
		os.Exit(1)
	}
	traceID := args[0]
	projectDir := "."
	if len(args) >= 2 {
		projectDir = args[1]
	}
	path := filepath.Join(projectDir, ".mimic", "sessions", "trace-"+traceID+".jsonl")

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	fmt.Printf("── mimic watch: trace_id=%s ──\n監視ファイル: %s\n(Ctrl+Cで終了)\n\n", traceID, path)

	if !waitForFile(path, sigCh) {
		return
	}

	var offset int64
	for {
		select {
		case <-sigCh:
			return
		default:
		}

		chunk, newOffset, ok := readNewComplete(path, offset)
		if !ok {
			sleepOrExit(sigCh)
			continue
		}
		offset = newOffset

		done := false
		for _, line := range bytes.Split(chunk, []byte("\n")) {
			line = bytes.TrimSpace(line)
			if len(line) == 0 {
				continue
			}
			if printEntry(line) {
				done = true
			}
		}
		if done {
			return
		}
		if len(chunk) == 0 {
			sleepOrExit(sigCh)
		}
	}
}

// waitForFile はpathが出現するまでwatchFileAppearTimeoutを上限にポーリングする。
// シグナルを受けた場合はfalseを返す（呼び出し元は即座に終了すること）。
func waitForFile(path string, sigCh <-chan os.Signal) bool {
	deadline := time.Now().Add(watchFileAppearTimeout)
	for {
		if _, err := os.Stat(path); err == nil {
			return true
		}
		if time.Now().After(deadline) {
			fmt.Fprintf(os.Stderr, "タイムアウト: %s が作成されませんでした\n", path)
			return false
		}
		select {
		case <-sigCh:
			return false
		case <-time.After(watchPollInterval):
		}
	}
}

func sleepOrExit(sigCh <-chan os.Signal) {
	select {
	case <-sigCh:
	case <-time.After(watchPollInterval):
	}
}

// readNewComplete はoffset以降に追記された「完全な行」だけを返す
// （末尾の書きかけ行は次回に持ち越し、offsetを進めない）。
func readNewComplete(path string, offset int64) (chunk []byte, newOffset int64, ok bool) {
	f, err := os.Open(path)
	if err != nil {
		return nil, offset, false
	}
	defer f.Close()

	stat, err := f.Stat()
	if err != nil || stat.Size() <= offset {
		return nil, offset, true // 追記なし
	}
	if _, err := f.Seek(offset, io.SeekStart); err != nil {
		return nil, offset, false
	}
	buf, err := io.ReadAll(f)
	if err != nil {
		return nil, offset, false
	}
	lastNewline := bytes.LastIndexByte(buf, '\n')
	if lastNewline < 0 {
		return nil, offset, true // まだ完全な行が無い
	}
	return buf[:lastNewline], offset + int64(lastNewline) + 1, true
}

// printEntry は1件のJSONLエントリを整形して標準出力へ書く。
// final_answerを検知した場合はtrueを返す（呼び出し元は監視を終了すること）。
func printEntry(line []byte) bool {
	var e sessionEntry
	if err := json.Unmarshal(line, &e); err != nil {
		return false
	}
	switch e.Type {
	case "action":
		fmt.Printf("🔧 %s(%s)\n", e.Tool, truncateRaw(e.Args, 120))
	case "observation":
		fmt.Printf("   → %s\n", truncateText(e.Result, 200))
	case "system_event":
		fmt.Printf("ℹ  %s\n", truncateRaw(e.Content, 200))
	case "final_answer":
		var content string
		_ = json.Unmarshal(e.Content, &content)
		fmt.Printf("\n✓ 完了\n%s\n", content)
		return true
	}
	return false
}

func truncateText(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max]) + "…"
}

func truncateRaw(raw json.RawMessage, max int) string {
	return truncateText(string(raw), max)
}
