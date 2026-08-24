// mimic — Go移植版のエントリポイント（フェーズ1: LLMストリーミング付きTUI）。
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	tea "github.com/charmbracelet/bubbletea"

	"mimic/internal/config"
	"mimic/internal/llm"
	"mimic/internal/tui"
	"mimic/internal/viewer"
)

func main() {
	envPath := flag.String("env", "./.env", ".envファイルのパス")
	promptFlag := flag.String("prompt", "", "非対話モード: 1ターンだけ実行して結果を標準出力に出して終了する")
	autoPromptFlag := flag.String("auto-prompt", "", "自動実行モード: --promptと同様だが完了マーカー付きで出力する（Worker連携用、フェーズ3で本格活用予定）")
	statusFlag := flag.Bool("status", false, "現在の設定（プロバイダ/モデル/キー数）を表示して終了する")
	flag.Parse()

	cfg, err := config.Load(*envPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "設定読み込みエラー: %v\n", err)
		os.Exit(1)
	}

	client := llm.NewClient(cfg.Active)

	if *statusFlag {
		runStatusMode(client.ProviderName(), client.Model(), len(cfg.Active.APIKeys))
		return
	}
	if *promptFlag != "" {
		runNonInteractive(client, cfg.SystemPrompt, *promptFlag, false)
		return
	}
	if *autoPromptFlag != "" {
		runNonInteractive(client, cfg.SystemPrompt, *autoPromptFlag, true)
		return
	}

	fmt.Fprintf(os.Stderr, "[mimic-go] provider=%s model=%s\n", client.ProviderName(), client.Model())

	if cwd, err := os.Getwd(); err == nil {
		sessionsDir := filepath.Join(cwd, ".mimic", "sessions")
		if url, err := viewer.StartServer(sessionsDir); err == nil {
			fmt.Fprintf(os.Stderr, "[mimic-go] session viewer: %s\n", url)
		}
	}

	// あえて tea.WithAltScreen() を付けていない。
	// Textualのalt-screen全面制御がスクロール/テキスト選択を阻害していた
	// 疑いがあるため、フェーズ1ではまずネイティブのターミナルスクロール
	// バックがそのまま機能するインラインモードで動作を確認する。
	// マウスモードも同様の理由で有効化していない
	// （設計書06章「マウスモードの選択的有効化」方針）。
	p := tea.NewProgram(tui.NewModel(client, cfg.SystemPrompt))
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "エラー: %v\n", err)
		os.Exit(1)
	}
}
