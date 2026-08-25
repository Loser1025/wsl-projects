// mimic — Go移植版のエントリポイント（フェーズ1: LLMストリーミング付きTUI）。
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	tea "charm.land/bubbletea/v2"

	"mimic/internal/config"
	"mimic/internal/llm"
	"mimic/internal/selector"
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

	if *statusFlag {
		runStatusMode(cfg.Active.Name, cfg.Active.Model, len(cfg.Active.APIKeys))
		return
	}
	if *promptFlag != "" {
		runNonInteractive(llm.NewClient(cfg.Active), cfg.SystemPrompt, *promptFlag, false)
		return
	}
	if *autoPromptFlag != "" {
		runNonInteractive(llm.NewClient(cfg.Active), cfg.SystemPrompt, *autoPromptFlag, true)
		return
	}

	// 対話モード起動前に、プロバイダ横断のモデルセレクター（一覧取得+疎通確認）を
	// 必ず経由する（Python版 __main__.py の対話モード起動フローを踏襲）。
	active := selector.SelectInteractively(cfg)
	client := llm.NewClient(active)

	fmt.Fprintf(os.Stderr, "[mimic-go] provider=%s model=%s\n", client.ProviderName(), client.Model())

	if cwd, err := os.Getwd(); err == nil {
		sessionsDir := filepath.Join(cwd, ".mimic", "sessions")
		if url, err := viewer.StartServer(sessionsDir); err == nil {
			fmt.Fprintf(os.Stderr, "[mimic-go] session viewer: %s\n", url)
		}
	}

	// alt-screen・マウスモードはv2ではView()が返すtea.Viewのフィールドとして
	// tui.Model.View()側で指定する（NewProgramのオプションではない）。
	// テキスト選択は主要ターミナル（Windows Terminal/iTerm2/GNOME Terminal/
	// Alacritty/kitty等）がShift+ドラッグでアプリのマウス捕捉を無視した
	// 選択を標準サポートしているため、マウスホイールでのviewportスクロールと
	// 両立できる。
	p := tea.NewProgram(tui.NewModel(client, cfg.SystemPrompt))
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "エラー: %v\n", err)
		os.Exit(1)
	}
}
