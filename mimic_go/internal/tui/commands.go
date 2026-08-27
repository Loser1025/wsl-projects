package tui

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"mimic/internal/bench"
	"mimic/internal/delegate"
	"mimic/internal/mcp"
	"mimic/internal/tools"
	"mimic/internal/viewer"
)

// スラッシュコマンド群（Python版 commands.py の縮小移植）。
// runSlashCommand はコマンド名（先頭の"/"含む）に応じて処理し、
// 対応するコマンドであれば(更新後のModel, true)を返す。未知のコマンドや
// 通常のチャット入力の場合はhandled=falseを返し、呼び出し元が通常の
// チャット送信処理へフォールバックする。
func (m Model) runSlashCommand(text string) (Model, bool) {
	fields := strings.Fields(text)
	if len(fields) == 0 || !strings.HasPrefix(fields[0], "/") {
		return m, false
	}
	cmd := fields[0]
	args := fields[1:]

	switch cmd {
	case "/undo":
		result := m.autoGit.Rollback(m.cwd)
		return m.appendCommandLog(text, fmt.Sprintf("[AutoGit] %s", result)), true
	case "/stats":
		return m.appendCommandLog(text, m.callLog.StatsText()), true
	case "/bench":
		report, err := bench.Run(m.cwd)
		if err != nil {
			report = fmt.Sprintf("ベンチマーク集計エラー: %v", err)
		}
		return m.appendCommandLog(text, report), true
	case "/help":
		return m.appendCommandLog(text, helpText()), true
	case "/status":
		return m.appendCommandLog(text, m.statusText()), true
	case "/clear":
		m.history = nil
		delegate.DiscardSessionWorker()
		delegate.ClearDelegationHistory()
		return m.appendCommandLog(text, "会話履歴をクリアしました。"), true
	case "/cd":
		return m.cmdCD(text, args), true
	case "/sessions":
		return m.appendCommandLog(text, listSessionsText(m.cwd)), true
	case "/skills":
		if len(args) > 0 && args[0] == "reload" {
			return m.appendCommandLog(text, tools.ReloadSkills()), true
		}
		return m.appendCommandLog(text, m.registry.Call("list_skills", "{}")), true
	case "/delegations":
		return m.appendCommandLog(text, delegationsText()), true
	case "/mcp":
		return m.cmdMCP(text, args), true
	case "/search":
		return m.appendCommandLog(text, searchSessionsText(m.cwd, strings.Join(args, " "))), true
	case "/viewer":
		return m.cmdViewer(text), true
	case "/model":
		return m.cmdModel(text, args), true
	case "/mode":
		return m.cmdMode(text, args), true
	case "/scratchpad":
		content := tools.GetScratchpad()
		if strings.TrimSpace(content) == "" {
			content = "（スクラッチパッドは空です）"
		}
		return m.appendCommandLog(text, content), true
	}
	return m, false
}

// appendCommandLog はコマンドとその結果をログに積み、viewportを更新する
// （既存の/undo /stats /bench 実装が共通で行っていた定型処理の切り出し）。
func (m Model) appendCommandLog(cmdText, result string) Model {
	m.log = append(m.log, fmt.Sprintf("> %s", cmdText), result)
	m.openLine = false
	m.viewport.SetContent(m.renderLog())
	m.viewport.GotoBottom()
	return m
}

func helpText() string {
	return strings.Join([]string{
		"利用可能なコマンド:",
		"  /help                     このヘルプを表示",
		"  /status                   プロバイダ・モデル・作業ディレクトリを表示",
		"  /clear                    会話履歴をクリア（保持中の委任セッションも破棄）",
		"  /cd <dir>                 作業ディレクトリを変更",
		"  /sessions                 過去セッション一覧",
		"  /search <キーワード>       過去セッションをキーワード検索",
		"  /skills                   利用可能なSkill一覧",
		"  /skills reload            Skillディレクトリを再スキャン",
		"  /delegations              孤立委任（中断された委任）の一覧",
		"  /mcp                      接続中MCPサーバー一覧",
		"  /mcp trust <server> [read-only|off]  MCPサーバーの信頼設定を変更",
		"  /mcp reconnect <server>   MCPサーバーを再接続",
		"  /undo                     直前の変更をロールバック",
		"  /stats                    ツール呼び出し統計",
		"  /bench                    ベンチマーク集計レポート",
		"  /viewer                   ローカル観測ビューアを起動してブラウザで開く",
		"  /scratchpad               現在のスクラッチパッド内容を表示",
		"  /model                    現在のモデルを表示",
		"  /model <name>             モデルを直接切替（会話履歴リセット）",
		"  /mode                     現在のエージェントモードを表示",
		"  /mode specialist|interactive  エージェントモードを切替（会話履歴リセット）",
	}, "\n")
}

// cmdViewer はローカル観測ビューアをオンデマンド起動する（Python版
// commands.py::cmd_viewer の移植。既に起動済みならURLを再掲するだけで
// 再起動はしない）。
func (m Model) cmdViewer(text string) Model {
	if m.viewerURL != "" {
		return m.appendCommandLog(text, fmt.Sprintf("観測ビューアは起動済みです: %s", m.viewerURL))
	}
	sessionsDir := filepath.Join(m.cwd, ".mimic", "sessions")
	if _, err := os.Stat(sessionsDir); err != nil {
		return m.appendCommandLog(text, "セッションログがまだありません。")
	}
	url, err := viewer.StartServer(sessionsDir)
	if err != nil {
		return m.appendCommandLog(text, fmt.Sprintf("ビューア起動エラー: %v", err))
	}
	m.viewerURL = url
	viewer.OpenBrowser(url)
	return m.appendCommandLog(text, fmt.Sprintf("✓ 観測ビューアを起動しました: %s", url))
}

func (m Model) statusText() string {
	base := fmt.Sprintf(
		"プロバイダ: %s\nモデル: %s\nモード: %s\n作業ディレクトリ: %s\nツール数: %d\n履歴メッセージ数: %d",
		m.client.ProviderName(), m.client.Model(), m.agentMode, m.cwd, len(m.registry.Specs()), len(m.history))
	return base + fmt.Sprintf("\nAPIキー: 即使用可 %d本 / 残トークン合計 %.1f",
		m.client.NReadyKeys(), m.client.TotalTokensAvailable())
}

func (m Model) cmdCD(text string, args []string) Model {
	if len(args) == 0 {
		return m.appendCommandLog(text, fmt.Sprintf("現在の作業ディレクトリ: %s", m.cwd))
	}
	target := args[0]
	if !filepath.IsAbs(target) {
		target = filepath.Join(m.cwd, target)
	}
	info, err := os.Stat(target)
	if err != nil || !info.IsDir() {
		return m.appendCommandLog(text, fmt.Sprintf("エラー: ディレクトリが見つかりません: %s", target))
	}
	abs, err := filepath.Abs(target)
	if err != nil {
		abs = target
	}
	m.cwd = abs
	m.filesScanned = false
	m.files = nil
	m.filesExpanded = nil
	m.filesCursor = 0
	m.filesScrollTop = 0
	m.filePath = ""
	m.filePreview = ""
	m.filePreviewScroll = 0
	return m.appendCommandLog(text, fmt.Sprintf("作業ディレクトリを変更しました: %s", abs))
}

func listSessionsText(cwd string) string {
	dir := filepath.Join(cwd, ".mimic", "sessions")
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) == 0 {
		return "セッション履歴はありません。"
	}
	type sessionFile struct {
		name  string
		mtime time.Time
	}
	var files []sessionFile
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".jsonl") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		files = append(files, sessionFile{e.Name(), info.ModTime()})
	}
	sort.Slice(files, func(i, j int) bool { return files[i].mtime.After(files[j].mtime) })
	if len(files) > 20 {
		files = files[:20]
	}
	var b strings.Builder
	b.WriteString(fmt.Sprintf("過去セッション（直近%d件）:\n", len(files)))
	for _, f := range files {
		fmt.Fprintf(&b, "  %s  %s\n", f.mtime.Format("2006-01-02 15:04"), f.name)
	}
	return b.String()
}

func searchSessionsText(cwd, query string) string {
	if strings.TrimSpace(query) == "" {
		return "エラー: 検索キーワードを指定してください。例: /search TODO"
	}
	dir := filepath.Join(cwd, ".mimic", "sessions")
	entries, err := os.ReadDir(dir)
	if err != nil {
		return "セッション履歴はありません。"
	}
	var hits []string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".jsonl") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			continue
		}
		lines := strings.Split(string(data), "\n")
		for i, line := range lines {
			if strings.Contains(line, query) {
				snippet := line
				if len(snippet) > 200 {
					snippet = snippet[:200]
				}
				hits = append(hits, fmt.Sprintf("%s:%d: %s", e.Name(), i+1, snippet))
				if len(hits) >= 30 {
					break
				}
			}
		}
		if len(hits) >= 30 {
			break
		}
	}
	if len(hits) == 0 {
		return fmt.Sprintf("「%s」は見つかりませんでした。", query)
	}
	return fmt.Sprintf("%d件ヒット:\n%s", len(hits), strings.Join(hits, "\n"))
}

func delegationsText() string {
	entries := delegate.ListOrphanedDelegations()
	if len(entries) == 0 {
		return "孤立委任（中断されたまま残っている委任）はありません。"
	}
	var b strings.Builder
	fmt.Fprintf(&b, "孤立委任 %d件:\n", len(entries))
	for _, e := range entries {
		age := "不明"
		if e.CheckpointAge != nil {
			age = strconv.Itoa(int(*e.CheckpointAge)) + "秒前"
		}
		fmt.Fprintf(&b, "  [%s] %s\n    開始: %s / 最終チェックポイント: %s\n    task: %.80s\n",
			e.TraceID, e.Label, e.StartedAt, age, e.Task)
	}
	b.WriteString("（Go版では自動再開は未対応。baseディレクトリを直接確認・削除してください: 各エントリのbase欄）")
	return b.String()
}

func (m Model) cmdMCP(text string, args []string) Model {
	if len(args) == 0 {
		status := mcp.ListStatus()
		if len(status) == 0 {
			return m.appendCommandLog(text, "接続対象のMCPサーバーはありません（~/.mcp.json, ./.mcp.json にmcpServersが見つかりません）。")
		}
		return m.appendCommandLog(text, "MCPサーバー:\n  "+strings.Join(status, "\n  "))
	}
	if args[0] == "trust" && len(args) >= 2 {
		server := args[1]
		trust := "read-only"
		if len(args) >= 3 {
			trust = args[2]
		}
		if err := mcp.SetServerTrust(m.cwd, server, trust); err != nil {
			return m.appendCommandLog(text, fmt.Sprintf("エラー: %v", err))
		}
		return m.appendCommandLog(text, fmt.Sprintf("%s の信頼設定を '%s' にしました（Worker接続時から有効）。", server, trust))
	}
	if args[0] == "reconnect" && len(args) >= 2 {
		res := mcp.Reconnect(m.registry, m.cwd, args[1])
		status := "✗"
		if res.OK {
			status = "✓"
		}
		return m.appendCommandLog(text, fmt.Sprintf("%s %s: %s", status, res.Name, res.Message))
	}
	return m.appendCommandLog(text, "使い方: /mcp  または  /mcp trust <server> [read-only|off]  または  /mcp reconnect <server>")
}

// cmdModel はモデルの確認・直接変更を行う（Python版 commands.py::cmd_model /
// app.py::_cmd_model の移植。TUI実行中にライブセレクターを再起動する仕組みは
// 無いため、引数なし時はライブ選択の代わりに現在値のみ表示する）。
func (m Model) cmdModel(text string, args []string) Model {
	if len(args) == 0 {
		return m.appendCommandLog(text, fmt.Sprintf(
			"現在のモデル: %s/%s\n変更: /model <モデル名>（Go版はライブ選択未対応のため名前を直接指定）",
			m.client.ProviderName(), m.client.Model()))
	}
	name := args[0]
	m.client.SetModel(name)
	m.history = nil
	return m.appendCommandLog(text, fmt.Sprintf("✓ モデルを変更しました: %s\n会話履歴をリセットしました。", name))
}

// specialistExcludedTools はSpecialistモードで除外するツール名
// （Python版 __main__.py::_SPECIALIST_EXCLUDED_TOOLS の移植。書き込み・シェル・
// Web直接アクセス・旧来の固定ロール委任を除外し、read_file/grep_codebase/
// file_infoは「覗き見ツール」として残す。mcp__*も別途prefix指定で全除外する）。
var specialistExcludedTools = []string{
	"write_file", "edit_file", "patch_file", "delete_file",
	"run_bash", "run_pipeline",
	"smart_read", "get_repo_map",
	"web_search", "fetch_webpage",
	"delegate_to_team", "delegate_to_team_parallel",
	"delegate_to_worker", "delegate_research",
}

// specialistSystemPrompt はSpecialistモード用のシステムプロンプト追記
// （Python版 orchestrator.py::SPECIALIST_REACT_SYSTEM_PROMPT の移植。
// run_host_commandはGo版に未実装のため言及しない）。
const specialistSystemPrompt = `
# 役割と行動指針（Specialist = 動的ロール委任モード）
あなたは指揮役（Director）です。実装・修正・実行・深い調査は専門家Workerへの
委任で行い、自分は「軽量な確認・委任の設計・結果の検証・ユーザーへの報告」に徹します。

## あなたが使えるツール（これがすべて。ここにないツールは存在しない）
- delegate_to_specialist(role, task, can_write, can_execute): 専門家への委任（標準の作業手段）
- continue_specialist(task): 直前のcan_write Workerへの追加指示（会話・作業状態を引き継ぐ）
- read_file / grep_codebase / file_info: 覗き見ツール（読み取り専用・観測は先頭600字まで）
- update_scratchpad: 作業メモの更新
- read_tool_cache: 長いツール出力の続きを読む
- get_delegation_trace: 委任実行トレースの確認

## 覗き見ツール（read_file / grep_codebase / file_info）
存在確認・場所特定のための軽量な読み取りは自分で行える。ただし観測は先頭600字で
打ち切られるため、深読みはできない。600字で足りない調査は読み取り専用の
delegate_to_specialistに委任すること。

## continue_specialist（継続委任）
直前のcan_write委任のWorkerは、会話と作業状態を保持したまま待機している。
前回の変更に対するフィードバックを反映する場合は、新しいdelegate_to_specialist
ではなくcontinue_specialist(task)を使うこと。

## delegate_to_specialistの使い方
roleには「視点」「制約」「完了基準」の3要素を必ず含めること（「完了基準」の
文字列がないと機械チェックで差し戻される）。
`

// cmdMode はエージェントモード（interactive/specialist）を切り替える
// （Python版 app.py::_cmd_mode の移植。切替時は使えるツール一覧・
// systemPromptを丸ごと差し替え、会話履歴・委任履歴・書き込みストリークを
// リセットする）。
func (m Model) cmdMode(text string, args []string) Model {
	arg := ""
	if len(args) > 0 {
		arg = strings.ToLower(args[0])
	}
	switch arg {
	case "interactive", "react", "i":
		delegate.ClearDelegationHistory()
		m.agentMode = "interactive"
		m.registry = m.fullRegistry
		m.systemPrompt = m.baseSystemPrompt
		m.history = nil
		return m.appendCommandLog(text, "⚡ モード: Interactive（フルツールReAct・退避用） 会話履歴をリセットしました。")
	case "specialist", "spec", "s":
		delegate.ClearDelegationHistory()
		m.agentMode = "specialist"
		m.registry = m.specialistRegistry
		m.systemPrompt = m.baseSystemPrompt + specialistSystemPrompt + delegate.LoadSavedRolesSection(10)
		m.history = nil
		return m.appendCommandLog(text, "🧪 モード: Specialist（動的ロール委任） 作業はdelegate_to_specialist/continue_specialistへ委任。会話履歴をリセットしました。")
	default:
		labels := map[string]string{
			"interactive": "Interactive（フルツールReAct・退避用）",
			"specialist":  "Specialist（動的ロール委任）",
		}
		return m.appendCommandLog(text, fmt.Sprintf(
			"現在: %s\n切替: /mode specialist  または  /mode interactive", labels[m.agentMode]))
	}
}
