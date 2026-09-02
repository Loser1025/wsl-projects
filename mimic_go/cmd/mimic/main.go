// mimic — Go移植版のエントリポイント（フェーズ1: LLMストリーミング付きTUI）。
package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	tea "charm.land/bubbletea/v2"

	"mimic/internal/config"
	"mimic/internal/delegate"
	"mimic/internal/llm"
	"mimic/internal/selector"
	"mimic/internal/tui"
)

// setupSignalHandling はSIGTERMを受けた際にメッセージを出して正常終了し、
// SIGHUPは無視する（Python版 __main__.py::_on_sigterm / SIGHUP=SIG_IGN の移植。
// 端末が閉じられてもnohup相当で動作を継続させる意図）。
func setupSignalHandling() {
	signal.Ignore(syscall.SIGHUP)

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM)
	go func() {
		<-sigCh
		fmt.Fprintln(os.Stderr, "\n  [SIGTERM] シャットダウンします...")
		os.Exit(0)
	}()
}

func main() {
	envPath := flag.String("env", "./.env", ".envファイルのパス")
	promptFlag := flag.String("prompt", "", "非対話モード: 1ターンだけ実行して結果を標準出力に出して終了する")
	autoPromptFlag := flag.String("auto-prompt", "", "自動実行モード: --promptと同様だが完了マーカー付きで出力する（Worker連携用、フェーズ3で本格活用予定）")
	statusFlag := flag.Bool("status", false, "現在の設定（プロバイダ/モデル/キー数）を表示して終了する")
	flag.Parse()

	setupSignalHandling()

	cfg, err := config.Load(*envPath)
	if errors.Is(err, config.ErrEnvTemplateGenerated) {
		fmt.Println(strings.Repeat("=", 55))
		fmt.Println("  設定ファイルを生成しました。")
		fmt.Printf("  場所: %s\n", *envPath)
		fmt.Println("  APIキーを設定してから再実行してください。")
		fmt.Println(strings.Repeat("=", 55))
		os.Exit(0)
	}
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

	// Directorとしての起動時、24時間以上前から進行中のままの孤立委任
	// （前回セッションがクラッシュ等で中断した委任）があれば警告する
	// （Python版 __main__.py の起動時警告の移植）。
	delegate.WarnOrphanedDelegations()

	// 対話モード起動前に、プロバイダ横断のモデルセレクター（一覧取得+疎通確認）を
	// 必ず経由する（Python版 __main__.py の対話モード起動フローを踏襲）。
	active := selector.SelectInteractively(cfg)
	client := llm.NewClient(active)

	fmt.Fprintf(os.Stderr, "[mimic-go] provider=%s model=%s\n", client.ProviderName(), client.Model())

	// Viewerサーバーは常時起動せず、/viewerコマンドでオンデマンド起動する
	// （Python版 commands.py::cmd_viewer と同じ挙動。意図しない常時待受ポートを避ける）。

	// alt-screen・マウスモードはv2ではView()が返すtea.Viewのフィールドとして
	// tui.Model.View()側で指定する（NewProgramのオプションではない）。
	// テキスト選択は主要ターミナル（Windows Terminal/iTerm2/GNOME Terminal/
	// Alacritty/kitty等）がShift+ドラッグでアプリのマウス捕捉を無視した
	// 選択を標準サポートしているため、マウスホイールでのviewportスクロールと
	// 両立できる。
	p := tea.NewProgram(tui.NewModel(client, cfg.SystemPrompt, cfg))
	// `/model`引数なし時のライブモデルセレクタが、ReleaseTerminal/RestoreTerminalで
	// 端末を一時的に明け渡すために使う（internal/tui/commands.go::liveModelSelectCmd）。
	tui.SetProgramRef(p)
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "エラー: %v\n", err)
		os.Exit(1)
	}
}
