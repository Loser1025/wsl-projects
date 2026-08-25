// Package tui は mimic の対話UIを実装する（Bubble Tea v2 / Lip Gloss v2）。
//
// Python版 app.py のタブ構成(Chat/Files/Scratchpad/Log, F1〜F4)とステータス
// パネルを踏襲しつつ、Razer Neon Greenテーマへ見た目を刷新した本統合版。
// 承認モーダル・スラッシュコマンド全種（/mode /model /search等）は未対応。
//
// 堅牢性の設計方針（/tmp/mimic_ui_sample での検証結果を反映）:
//   - 幅・高さの計算は必ず0以上にクランプする。
//   - Border/Paddingを持つ要素はWidth()に「最終幅からその分を引いた値」を渡す
//     （二重にパディングを見積もるミスが横幅オーバーの主要因だったため）。
//   - header/tabs等は各要素をMaxHeight(1)で強制的に1行へ切り詰め、
//     bodyHeightは定数を仮定せずlipgloss.Height()で実測した値を積み上げて
//     算出する（想定外の折り返しでも画面全体が端末高さをはみ出さない）。
//   - 極端に小さい端末では通常レイアウトを一切組み立てず専用の
//     フォールバック画面だけを返す。
package tui

import (
	"context"
	"fmt"
	"image/color"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"charm.land/bubbles/v2/textarea"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"mimic/internal/bench"
	"mimic/internal/delegate"
	"mimic/internal/llm"
	"mimic/internal/mcp"
	"mimic/internal/react"
	"mimic/internal/tools"
	"mimic/internal/vcs"
)

// ── カラーパレット（Razer Neon Greenテーマ、Python版セレクターと統一） ──
// Python版 app.py の CSS (GitHub Dark系配色) と完全一致させる。
var (
	colBG       = lipgloss.Color("#0D1117") // Screen background
	colBGAlt    = lipgloss.Color("#161B22") // パネル/タイトルバー/入力欄 background
	colBorder   = lipgloss.Color("#21262D") // title-bar border-bottom
	colBorderHi = lipgloss.Color("#00FF41") // 入力欄フォーカス時ボーダー・アクセント緑
	colBorder2  = lipgloss.Color("#30363D") // status-panel border-left / input-bar 通常ボーダー
	colText     = lipgloss.Color("#F0F6FC")
	colMuted    = lipgloss.Color("#8B949E") // Footer等の淡色
	colAccent   = lipgloss.Color("#00FF41") // 緑アクセント (■ AGENT見出し・IDLE等)
	colOnAccent = lipgloss.Color("#0A0F0A")
	colTitle    = lipgloss.Color("#58A6FF") // タイトル/Modeラベルの青
	colAmber    = lipgloss.Color("#FFDA6A") // BUSY等ステータス色
	colCyan     = lipgloss.Color("#58A6FF")
	colPink     = lipgloss.Color("#FF8C42") // Role表示色
)

const (
	minWidth  = 44
	minHeight = 12
)

func clamp0(n int) int {
	if n < 0 {
		return 0
	}
	return n
}

func clampMin(n, min int) int {
	if n < min {
		return min
	}
	return n
}

type tabID int

const (
	tabChat tabID = iota
	tabFiles
	tabScratchpad
	tabLog
)

var tabLabels = []string{"Chat", "Files", "Scratchpad", "Log"}

type fileEntry struct {
	path  string
	name  string
	isDir bool
	depth int
}

type Model struct {
	viewport viewport.Model
	input    textarea.Model
	log      []string
	width    int
	height   int
	ready    bool
	active   tabID

	client       *llm.Client
	systemPrompt string
	registry     *tools.Registry
	history      []llm.Message
	autoGit      *vcs.AutoGit
	reactLog     *vcs.ReactLog
	callLog      *vcs.ToolCallLog
	cwd          string

	streaming  bool
	turnCh     chan turnEvent
	cancelFunc context.CancelFunc
	openLine   bool

	// Filesタブ状態
	files        []fileEntry
	filesCursor  int
	filesScanned bool
	filePreview  string
	filePath     string
}

// turnEvent はReActループを回すゴルーチンからUpdateループへ渡すイベント。
type turnEvent struct {
	text     string
	tool     *react.ToolActivity
	done     bool
	history  []llm.Message
	finalErr error
}

const checkpointPath = ".mimic/checkpoint.json"

func NewModel(client *llm.Client, systemPrompt string) Model {
	ta := textarea.New()
	ta.Placeholder = "メッセージを入力... (Enterで送信、Ctrl+Nで改行、Ctrl+Cで終了)"
	ta.Focus()
	ta.CharLimit = 0
	ta.ShowLineNumbers = false
	ta.SetHeight(1)

	log := []string{"作業Dir: " + mustCwd()}
	history, err := react.LoadCheckpoint(checkpointPath)
	if err != nil {
		log = append(log, fmt.Sprintf("[警告] チェックポイントの読み込みに失敗しました: %v", err))
	} else if len(history) > 0 {
		log = append(log, fmt.Sprintf("前回中断したセッションを再開しました(履歴%d件)。", len(history)))
	}

	cwd := mustCwd()

	reactLog := vcs.NewReactLog()
	sessionsDir := filepath.Join(cwd, ".mimic", "sessions")
	jsonlPath := filepath.Join(sessionsDir, time.Now().Format("2006-01-02_15-04")+".jsonl")
	if err := reactLog.SetJSONLPath(jsonlPath); err == nil {
		vcs.PruneOldSessions(sessionsDir, 200)
	}
	reactLog.Add("session_start", map[string]any{"model": client.Model(), "provider": client.ProviderName()})

	registry := tools.NewDefaultRegistry()
	delegate.RegisterTools(registry, client)
	if results := mcp.ConnectAll(registry, cwd, false); len(results) > 0 {
		for _, r := range results {
			status := "✗"
			if r.OK {
				status = "✓"
			}
			log = append(log, fmt.Sprintf("[MCP] %s %s: %s", status, r.Name, r.Message))
		}
	}

	return Model{
		input:        ta,
		client:       client,
		systemPrompt: systemPrompt,
		registry:     registry,
		history:      history,
		log:          log,
		reactLog:     reactLog,
		callLog:      vcs.NewToolCallLog(),
		autoGit:      vcs.New(),
		cwd:          cwd,
	}
}

func mustCwd() string {
	cwd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return cwd
}

func (m Model) Init() tea.Cmd {
	return textarea.Blink
}

func waitForTurnEvent(ch chan turnEvent) tea.Cmd {
	return func() tea.Msg {
		ev, ok := <-ch
		if !ok {
			return turnEvent{done: true}
		}
		return ev
	}
}

// renderLog はviewportの幅に合わせて m.log の各行を折り返した上で結合する。
func (m Model) renderLog() string {
	w := m.viewport.Width()
	if w <= 0 {
		return strings.Join(m.log, "\n")
	}
	style := lipgloss.NewStyle().Width(w)
	wrapped := make([]string, len(m.log))
	for i, line := range m.log {
		wrapped[i] = style.Render(line)
	}
	return strings.Join(wrapped, "\n")
}

func (m *Model) appendToOpenLine(suffix string) {
	if !m.openLine || len(m.log) == 0 {
		m.log = append(m.log, "")
		m.openLine = true
	}
	m.log[len(m.log)-1] += suffix
}

func (m *Model) closeOpenLine() {
	m.openLine = false
}

// ── レイアウト寸法の再計算 ────────────────────────────────────
// ウィンドウサイズ・アクティブタブが変わるたびに呼ぶ。チャットビューポートの
// 寸法はChatタブアクティブ時のみ意味を持つが、常に更新して整合性を保つ。
func (m *Model) recalcLayout() {
	if m.width <= 0 || m.height <= 0 {
		return
	}
	const headerLines = 1
	const tabsLines = 1
	inputHeight := lipgloss.Height(m.renderInput())
	bodyHeight := clampMin(m.height-headerLines-tabsLines-inputHeight, 1)
	bodyWidth := clamp0(m.width - 2) // renderBodyのPadding(0,1)*2ぶん

	if !m.ready {
		m.viewport = viewport.New(viewport.WithWidth(bodyWidth), viewport.WithHeight(bodyHeight))
		m.viewport.SetContent(m.renderLog())
		m.ready = true
	} else {
		m.viewport.SetWidth(bodyWidth)
		m.viewport.SetHeight(bodyHeight)
	}
	m.input.SetWidth(clampMin(m.width-4, 1))
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var (
		taCmd tea.Cmd
		vpCmd tea.Cmd
	)

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.recalcLayout()

	case tea.KeyPressMsg:
		switch msg.String() {
		case "ctrl+c":
			if m.cancelFunc != nil {
				m.cancelFunc()
			}
			return m, tea.Quit
		case "f1":
			m.active = tabChat
			return m, nil
		case "f2":
			m.active = tabFiles
			if !m.filesScanned {
				m.files = scanFiles(m.cwd)
				m.filesScanned = true
			}
			return m, nil
		case "f3":
			m.active = tabScratchpad
			return m, nil
		case "f4":
			m.active = tabLog
			return m, nil
		}

		if m.active == tabFiles {
			switch msg.String() {
			case "up", "k":
				if m.filesCursor > 0 {
					m.filesCursor--
				}
				return m, nil
			case "down", "j":
				if m.filesCursor < len(m.files)-1 {
					m.filesCursor++
				}
				return m, nil
			case "enter":
				if m.filesCursor >= 0 && m.filesCursor < len(m.files) {
					e := m.files[m.filesCursor]
					if !e.isDir {
						m.filePath = e.path
						m.filePreview = readPreview(e.path)
					}
				}
				return m, nil
			}
		}

		if m.active != tabChat {
			return m, nil // Chat以外のタブでは通常入力を受け付けない
		}

		switch msg.String() {
		case "enter":
			if m.streaming {
				return m, nil
			}
			text := strings.TrimSpace(m.input.Value())
			if text == "" {
				return m, nil
			}
			m.input.Reset()
			if text == "/undo" {
				result := m.autoGit.Rollback(m.cwd)
				m.log = append(m.log, fmt.Sprintf("> %s", text), fmt.Sprintf("[AutoGit] %s", result))
				m.openLine = false
				m.viewport.SetContent(m.renderLog())
				m.viewport.GotoBottom()
				return m, nil
			}
			if text == "/stats" {
				m.log = append(m.log, fmt.Sprintf("> %s", text), m.callLog.StatsText())
				m.openLine = false
				m.viewport.SetContent(m.renderLog())
				m.viewport.GotoBottom()
				return m, nil
			}
			if text == "/bench" {
				report, err := bench.Run(m.cwd)
				if err != nil {
					report = fmt.Sprintf("ベンチマーク集計エラー: %v", err)
				}
				m.log = append(m.log, fmt.Sprintf("> %s", text), report)
				m.openLine = false
				m.viewport.SetContent(m.renderLog())
				m.viewport.GotoBottom()
				return m, nil
			}
			m.history = append(m.history, llm.Message{Role: "user", Content: text})
			m.log = append(m.log, fmt.Sprintf("> %s", text))
			m.openLine = false
			m.viewport.SetContent(m.renderLog())
			m.viewport.GotoBottom()
			return m.startTurn()
		}

	case turnEvent:
		switch {
		case msg.finalErr != nil:
			m.closeOpenLine()
			m.log = append(m.log, fmt.Sprintf("[エラー] %v", msg.finalErr))
			m.streaming = false
		case msg.tool != nil:
			m.closeOpenLine()
			m.log = append(m.log, fmt.Sprintf("  → %s(%s)", msg.tool.Name, msg.tool.ArgsPreview))
		case msg.done:
			m.closeOpenLine()
			m.streaming = false
			m.history = msg.history
		default:
			m.appendToOpenLine(msg.text)
		}
		m.viewport.SetContent(m.renderLog())
		m.viewport.GotoBottom()
		if !msg.done && msg.finalErr == nil {
			return m, waitForTurnEvent(m.turnCh)
		}
		return m, nil
	}

	if m.active == tabChat {
		m.input, taCmd = m.input.Update(msg)
		vp, cmd := m.viewport.Update(msg)
		m.viewport, vpCmd = vp, cmd
	}
	return m, tea.Batch(taCmd, vpCmd)
}

func (m Model) startTurn() (tea.Model, tea.Cmd) {
	m.streaming = true
	ch := make(chan turnEvent)
	ctx, cancel := context.WithCancel(context.Background())
	m.turnCh = ch
	m.cancelFunc = cancel

	client := m.client
	systemPrompt := m.systemPrompt
	registry := m.registry
	autoGit := m.autoGit
	reactLog := m.reactLog
	callLog := m.callLog
	cwd := m.cwd
	histCopy := append([]llm.Message(nil), m.history...)

	go func() {
		defer close(ch)
		_, err := react.RunTurn(ctx, client, systemPrompt, registry, &histCopy,
			func(text string) { ch <- turnEvent{text: text} },
			func(activity react.ToolActivity) { ch <- turnEvent{tool: &activity} },
			checkpointPath, autoGit, cwd, reactLog, callLog, false,
		)
		if err != nil && ctx.Err() == nil {
			ch <- turnEvent{finalErr: err}
			return
		}
		ch <- turnEvent{done: true, history: histCopy}
	}()

	return m, waitForTurnEvent(ch)
}

// ── ファイルツリー ────────────────────────────────────────────

var fileScanIgnore = map[string]bool{
	".git": true, "node_modules": true, ".venv": true, "venv": true,
	"__pycache__": true, ".idea": true, ".vscode": true, ".mimic": true,
}

const maxFileScanEntries = 500
const maxFileScanDepth = 6

// scanFiles はcwd配下を再帰的に走査し、フラットな一覧にする（安全のため件数・
// 深さの上限つき）。巨大リポジトリでも固まらないよう上限で早期打ち切りする。
func scanFiles(root string) []fileEntry {
	var out []fileEntry
	var walk func(dir string, depth int)
	walk = func(dir string, depth int) {
		if len(out) >= maxFileScanEntries || depth > maxFileScanDepth {
			return
		}
		entries, err := os.ReadDir(dir)
		if err != nil {
			return
		}
		sort.Slice(entries, func(i, j int) bool {
			if entries[i].IsDir() != entries[j].IsDir() {
				return entries[i].IsDir()
			}
			return entries[i].Name() < entries[j].Name()
		})
		for _, e := range entries {
			if fileScanIgnore[e.Name()] {
				continue
			}
			if len(out) >= maxFileScanEntries {
				return
			}
			full := filepath.Join(dir, e.Name())
			out = append(out, fileEntry{path: full, name: e.Name(), isDir: e.IsDir(), depth: depth})
			if e.IsDir() {
				walk(full, depth+1)
			}
		}
	}
	walk(root, 0)
	return out
}

const maxPreviewChars = 4000

func readPreview(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Sprintf("エラー: %v", err)
	}
	content := string(data)
	if len(content) > maxPreviewChars {
		content = content[:maxPreviewChars] + fmt.Sprintf("\n…(全%d文字中%d文字を表示)", len(content), maxPreviewChars)
	}
	return content
}

// ── View ──────────────────────────────────────────────────────

func (m Model) View() tea.View {
	var content string
	if m.width < minWidth || m.height < minHeight {
		content = m.renderTooSmall()
	} else {
		content = m.renderFull()
	}
	v := tea.NewView(content)
	v.AltScreen = true
	v.MouseMode = tea.MouseModeCellMotion
	return v
}

func (m Model) renderTooSmall() string {
	msg := fmt.Sprintf("端末が小さすぎます\n最小 %d×%d 必要です\n現在: %d×%d", minWidth, minHeight, m.width, m.height)
	if m.width <= 0 || m.height <= 0 {
		return msg
	}
	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		lipgloss.NewStyle().Foreground(colAmber).Render(msg))
}

func (m Model) renderFull() string {
	header := m.renderHeader()
	tabs := m.renderTabs()
	input := m.renderInput()

	usedHeight := lipgloss.Height(header) + lipgloss.Height(tabs) + lipgloss.Height(input)
	bodyHeight := clampMin(m.height-usedHeight, 1)
	body := m.renderBody(bodyHeight)

	return lipgloss.JoinVertical(lipgloss.Left, header, tabs, body, input)
}

// mimicArtLines はPython版 utils.py::get_ascii_art_str のpyfiglet非依存フォールバック
// ブロック文字と完全一致させたもの（pyfigletはGo版に移植していないため常にこの表現を使う）。
var mimicArtLines = []string{
	"███╗   ███╗██╗███╗   ███╗██╗ ██████╗",
	"████╗ ████║██║████╗ ████║██║██╔════╝",
	"██╔████╔██║██║██╔████╔██║██║██║     ",
	"██║╚██╔╝██║██║██║╚██╔╝██║██║██║     ",
	"██║ ╚═╝ ██║██║██║ ╚═╝ ██║██║╚██████╗",
	"╚═╝     ╚═╝╚═╝╚═╝     ╚═╝╚═╝ ╚═════╝",
}

// mimicArtColors はPython版のRazerグリーン→ティール→エレクトリックアクアの
// グラデーションと同じ配色（1行ずつ対応）。
var mimicArtColors = []string{
	"#00FF41",
	"#00FF78",
	"#00FFB4",
	"#00F2DA",
	"#00E6FF",
	"#50D7FF",
}

var mimicArtDimColor = "#005050"

// renderTitleArt はPython版の #title-art（ASCIIアート+区切り線+サブタイトル）を再現する。
func (m Model) renderTitleArt() string {
	var lines []string
	for i, l := range mimicArtLines {
		c := mimicArtColors[i]
		if i >= len(mimicArtColors) {
			c = mimicArtColors[len(mimicArtColors)-1]
		}
		lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(c).Render(l))
	}
	sepStyle := lipgloss.NewStyle().Foreground(mimicArtDimColor)
	sep := sepStyle.Render(" " + strings.Repeat("─", 50))
	subtitle := m.client.Model() + "  ·  " + m.cwd
	sub := lipgloss.NewStyle().Bold(true).Foreground(mimicArtColors[len(mimicArtColors)-1]).Render(" " + subtitle)
	lines = append(lines, sep, sub, sep)
	return strings.Join(lines, "\n")
}

// renderStatusPanel はPython版の #status-panel（■ AGENT セクション）を再現する
// （固定幅36。CPU/MEMの■ SYSTEMセクションはGo版に対応するシステム計測が
// 未実装のため今回は対象外——Python版のみの機能）。
func (m Model) renderStatusPanel() string {
	const panelWidth = 36
	statusText := "IDLE"
	statusColor := colAccent
	if m.streaming {
		statusText = "BUSY"
		statusColor = colAmber
	}
	heading := lipgloss.NewStyle().Bold(true).Foreground(colAccent).Render("■ AGENT")
	status := "  Status: " + lipgloss.NewStyle().Bold(true).Foreground(statusColor).Render(statusText)
	content := heading + "\n" + status

	return lipgloss.NewStyle().
		Width(panelWidth-2).MaxWidth(panelWidth-2).
		Background(colBGAlt).
		Foreground(colText).
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(colBorder2).
		BorderLeft(true).BorderTop(false).BorderRight(false).BorderBottom(false).
		Padding(0, 1).
		Render(content)
}

// renderHeader はPython版 #title-bar（左: ASCIIアート、右: ステータスパネル、
// 下部境界線）を再現する。
func (m Model) renderHeader() string {
	art := m.renderTitleArt()
	panel := m.renderStatusPanel()

	// 注意: 既にANSIスタイル適用済みの複数行ブロックへ更にWidth()/MaxWidth()に
	// よる切り詰めを重ねると、lipglossのANSI考慮切り詰めロジックが末尾の内容を
	// 誤って削り取る（renderHeaderの旧バージョンで実際に発生したバグ）。
	// そのため箱の内側では自然幅のままPadding/Backgroundのみ適用し、
	// 右側の余白は手動でスペースを追記して埋める安全な方式を使う。
	artBox := lipgloss.NewStyle().
		Background(colBGAlt).
		Padding(0, 2).
		Render(art)

	row := lipgloss.JoinHorizontal(lipgloss.Top, artBox, panel)
	// 各行ごとに実幅を測って右端を埋める（行によって幅が異なるため一括ではなく行単位で処理）。
	rowLines := strings.Split(row, "\n")
	for i, rl := range rowLines {
		gap := clamp0(m.width - lipgloss.Width(rl))
		if gap > 0 {
			rowLines[i] = rl + lipgloss.NewStyle().Background(colBGAlt).Render(strings.Repeat(" ", gap))
		}
	}
	row = strings.Join(rowLines, "\n")

	return lipgloss.NewStyle().
		Background(colBGAlt).
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(colBorder).
		BorderBottom(true).BorderTop(false).BorderLeft(false).BorderRight(false).
		Render(row)
}

func (m Model) renderTabs() string {
	var rendered []string
	for i, label := range tabLabels {
		style := lipgloss.NewStyle().Padding(0, 2).Foreground(colMuted)
		if tabID(i) == m.active {
			style = lipgloss.NewStyle().Padding(0, 2).Bold(true).Foreground(colOnAccent).Background(colAccent)
		}
		rendered = append(rendered, style.Render(fmt.Sprintf("%s [F%d]", label, i+1)))
	}
	bar := lipgloss.JoinHorizontal(lipgloss.Top, rendered...)
	return lipgloss.NewStyle().Width(m.width).MaxWidth(m.width).Height(1).MaxHeight(1).Background(colBGAlt).Render(bar)
}

func (m Model) renderBody(height int) string {
	const hPad = 1
	innerWidth := clamp0(m.width - hPad*2)

	var content string
	switch m.active {
	case tabChat:
		content = m.viewport.View()
	case tabFiles:
		content = m.renderFiles(innerWidth, height)
	case tabScratchpad:
		content = lipgloss.NewStyle().Foreground(colText).MaxWidth(innerWidth).Render(tools.GetScratchpad())
	case tabLog:
		content = m.renderLogTab(innerWidth)
	}

	style := lipgloss.NewStyle().Width(innerWidth).MaxWidth(innerWidth).Height(height).MaxHeight(height)
	if m.active != tabChat {
		style = style.Padding(0, hPad)
	}
	return style.Render(content)
}

func (m Model) renderFiles(width, height int) string {
	treeWidth := clampMin(width/3, 20)
	if treeWidth > width-4 {
		treeWidth = clampMin(width-4, 1)
	}
	previewWidth := clampMin(width-treeWidth-3, 1)

	var treeLines []string
	for i, e := range m.files {
		indent := strings.Repeat("  ", e.depth)
		name := e.name
		if e.isDir {
			name += "/"
		}
		line := indent + name
		st := lipgloss.NewStyle().Foreground(colText)
		if i == m.filesCursor {
			st = lipgloss.NewStyle().Foreground(colOnAccent).Background(colAccent).Bold(true)
		} else if e.isDir {
			st = lipgloss.NewStyle().Foreground(colCyan)
		}
		treeLines = append(treeLines, st.MaxWidth(treeWidth).Render(line))
	}
	if len(treeLines) == 0 {
		treeLines = []string{lipgloss.NewStyle().Foreground(colMuted).Render("(空、またはスキャン待ち)")}
	}
	tree := strings.Join(treeLines, "\n")

	preview := m.filePreview
	if preview == "" {
		preview = "↑/↓ でファイル選択、Enterでプレビュー"
	}
	previewHeader := ""
	if m.filePath != "" {
		rel, _ := filepath.Rel(m.cwd, m.filePath)
		previewHeader = lipgloss.NewStyle().Foreground(colAccent).Bold(true).Render(rel) + "\n"
	}

	left := lipgloss.NewStyle().
		Width(treeWidth).MaxWidth(treeWidth).Height(height).MaxHeight(height).
		Border(lipgloss.NormalBorder(), false, true, false, false).
		BorderForeground(colBorder).
		Padding(0, 1).
		Render(tree)
	right := lipgloss.NewStyle().
		Width(previewWidth).MaxWidth(previewWidth).Height(height).MaxHeight(height).
		Padding(0, 1).
		Render(previewHeader + lipgloss.NewStyle().Foreground(colText).MaxWidth(previewWidth).Render(preview))
	return lipgloss.JoinHorizontal(lipgloss.Top, left, right)
}

func (m Model) renderLogTab(width int) string {
	entries := m.reactLog.RecentEntries(200)
	if len(entries) == 0 {
		return lipgloss.NewStyle().Foreground(colMuted).Render("(まだイベントがありません)")
	}
	var lines []string
	for _, e := range entries {
		t, _ := e["type"].(string)
		ts, _ := e["ts"].(string)
		var body string
		switch t {
		case "action":
			body = fmt.Sprintf("%v", e["tool"])
		case "observation":
			body = fmt.Sprintf("%v", e["tool"])
		case "user_input":
			body = fmt.Sprintf("%v", e["content"])
		case "final_answer":
			body = "final_answer"
		case "session_start":
			body = fmt.Sprintf("model=%v provider=%v", e["model"], e["provider"])
		default:
			body = t
		}
		lines = append(lines, lipgloss.NewStyle().Foreground(colMuted).MaxWidth(width).Render(
			fmt.Sprintf("[%s] %s %s", ts, t, body)))
	}
	return strings.Join(lines, "\n")
}

func (m Model) renderInput() string {
	const borderCols = 2
	const paddingCols = 2
	innerWidth := clampMin(m.width-borderCols-paddingCols, 1)

	borderColor := colBorderHi
	if m.active != tabChat {
		borderColor = colBorder
	}
	box := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(borderColor).
		Padding(0, 1).
		Width(innerWidth).MaxWidth(m.width)

	inputView := m.input.View()
	boxRendered := box.Render(inputView)

	hint := "Enter 送信 · Ctrl+N 改行 · F1-F4 タブ切替 · Ctrl+C 終了"
	if m.streaming {
		hint = "⏳ 実行中... (Ctrl+C で中断)"
	} else if m.active == tabFiles {
		hint = "↑/↓ 選択 · Enter プレビュー · F1-F4 タブ切替"
	} else if m.active != tabChat {
		hint = "F1-F4 タブ切替 · Ctrl+C 終了"
	}
	hintLine := lipgloss.NewStyle().
		Foreground(colMuted).
		Width(m.width).MaxWidth(m.width).Height(1).MaxHeight(1).
		Align(lipgloss.Right).
		Render(hint)

	return lipgloss.JoinVertical(lipgloss.Left, boxRendered, hintLine)
}
