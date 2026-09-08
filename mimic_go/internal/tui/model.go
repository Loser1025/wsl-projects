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
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"charm.land/bubbles/v2/progress"
	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/textarea"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"mimic/internal/config"
	"mimic/internal/delegate"
	"mimic/internal/llm"
	"mimic/internal/mcp"
	"mimic/internal/react"
	"mimic/internal/tools"
	"mimic/internal/vcs"
	"mimic/internal/viewer"
)

// ── カラーパレット（Razer Neon Greenテーマ、Python版セレクターと統一） ──
// Python版 app.py の CSS (GitHub Dark系配色) と完全一致させる。
// 背景色（Screen/#161b22等）はTUI全体を透過表示するため意図的に使わない
// （端末側の背景・透過設定をそのまま透けさせる方針）。
var (
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

// Python版 app.py::compose() の TabPane タイトル（絵文字付き）と一致させる。
var tabLabels = []string{"💬 Chat", "📁 Files", "📝 Scratchpad", "📜 Log"}

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
	cfg          *config.Config // /model引数なし時のライブモデルセレクタで使う
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

	// <think>/<thought>ブロック検出（Python版 utils.py::ThinkAwareBuffer の移植）。
	// ターン開始時にリセットし、ストリームチャンクをこれ経由でログへ流す。
	thinkBuf     ThinkAwareBuffer
	inThinkLine  bool
	thinkLineBuf string // 未改行のthink断片バッファ（複数行ボックス表示用）

	// 通常テキストのバッファリング（Python版 PipelineTypewriter::_raw_buf相当）。
	// appendThinkSegment/feedRawTextが使う。
	rawTextBuf string

	// /viewerコマンドでオンデマンド起動する観測ビューアのURL（起動前は空文字）。
	viewerURL string

	// エージェントモード（Python版 app.py::_cmd_mode の移植。interactive=通常の
	// フルツールReAct（既定・退避用）、specialist=delegate_to_specialistのみで
	// 動く軽量Director）。切替時はregistry/systemPromptを丸ごと差し替える。
	agentMode          string
	fullRegistry       *tools.Registry
	specialistRegistry *tools.Registry
	baseSystemPrompt   string // モード接尾辞を含まない素のsystemPrompt

	// Filesタブ状態
	files        []fileEntry
	filesCursor  int
	filesScanned bool
	filePreview  string
	filePath     string

	// ツリーの展開状態（Python版 Textual Tree の「ルートのみ自動展開、他は
	// ノードを開くまで子要素が非表示」の移植。キーはディレクトリの絶対パス）。
	filesExpanded map[string]bool
	// ツリー/プレビューのスクロール位置（Python版 Tree/RichLog の自動スクロールの移植。
	// Go版は手描画のため、カーソル追従・PageUp/PageDown等で明示的に管理する）。
	filesScrollTop    int
	filePreviewScroll int

	// ファイルプレビュー内`/`検索（Python版 app.py::_open_file_search/_run_file_search
	// /_render_preview の移植）。filePreviewAllLinesは検索対象となる全行
	// （表示用filePreviewは4000字で打ち切られるため別に保持する）。
	filePreviewAllLines  []string
	fileSearchActive     bool // 検索クエリ入力中かどうか（Enterで確定しfalseに戻る）
	fileSearchQuery      string
	filePreviewSearching bool         // 検索確定後、結果（マッチ行±2）のみ表示中かどうか
	filePreviewMatches   map[int]bool // マッチした行番号（0-indexed）の集合

	// 書き込み承認フロー（Python版 app.py の承認モーダルの移植）
	approvalCh      chan approvalRequest
	pendingApproval *approvalRequest
	approvalSeq     int

	// 委任apply承認フロー（Python版 app.py::_make_apply_approval_handler の移植。
	// APPLY_APPROVAL=ask/threshold時のみ実際に発動する。デフォルト(auto)では
	// ハンドラは登録されるが呼ばれない＝常に自動適用のまま）。
	applyApprovalCh      chan applyApprovalRequest
	pendingApplyApproval *applyApprovalRequest
	applyApprovalSeq     int

	// ホスト直接実行承認フロー（Python版 app.py::_make_host_exec_approval_handler の移植）。
	hostExecApprovalCh      chan hostExecApprovalRequest
	pendingHostExecApproval *hostExecApprovalRequest
	hostExecApprovalSeq     int

	// /search・/sessionsのヒット後コンテキスト注入フロー（Python版 app.py::_cmd_search/
	// _cmd_sessions の`_enter_approval_mode`による対話確認の移植）。
	pendingSearchSelection *searchSelectionState
	pendingSessionInject   *sessionInjectState

	// ■ SYSTEM パネル用のシステムCPU/MEM使用率（Python版 app.py::_refresh_system_panel
	// の移植。2秒間隔でsystemTickMsg経由で更新する）。
	systemCPUPercent float64
	systemMemUsedMB  float64
	systemMemTotalMB float64

	// ステータスパネルの動的表示用（BUSY中のスピナー、CPU/MEMのバー表示）。
	busySpinner spinner.Model
	cpuBar      progress.Model
	memBar      progress.Model

	// 直近に開始した委任がまだ完了していない間、renderLogでその委任カードの
	// 直後に「実行中...」を表示するためのm.logインデックス（未実行時は-1）。
	// 委任ツールは同期実行のため、次のturnEventが来た時点で必ずクリアする。
	pendingDelegationIdx int
}

// hostExecApprovalRequest はtools.HostExecApprovalHandler経由でツール実行
// goroutineからUpdateループへ渡される承認依頼。
type hostExecApprovalRequest struct {
	id      int
	command string
	reason  string
	respCh  chan bool
}

type hostExecApprovalTimeoutMsg struct{ id int }

// systemTickMsg はシステムCPU/MEM使用率を再計測させる2秒間隔のティック
// （Python版 app.py の set_interval(2, _refresh_system_panel) の移植）。
type systemTickMsg struct{}

const systemTickInterval = 2 * time.Second

func systemTickCmd() tea.Cmd {
	return tea.Tick(systemTickInterval, func(time.Time) tea.Msg { return systemTickMsg{} })
}

// delegationResumeResultMsg は`/delegations resume`のバックグラウンド実行完了を
// Updateループへ通知する（Worker再実行は時間がかかるためgoroutineで行い、
// TUIをブロックしない）。
type delegationResumeResultMsg struct {
	text string
}

// resumeDelegationCmd はdelegate.ResumeDelegationをバックグラウンドで実行する。
func resumeDelegationCmd(traceID string) tea.Cmd {
	return func() tea.Msg {
		result, err := delegate.ResumeDelegation(context.Background(), traceID)
		if err != nil {
			return delegationResumeResultMsg{text: fmt.Sprintf("  [Resume] エラー: %v", err)}
		}
		return delegationResumeResultMsg{text: "  " + result}
	}
}

// approvalRequest はtools.ApprovalHandler経由でツール実行goroutineから
// Updateループへ渡される承認依頼（Python版のスレッド間コールバックに相当）。
type approvalRequest struct {
	id       int
	toolName string
	path     string
	preview  string
	respCh   chan bool
}

const approvalTimeoutSec = 30 // Python版 app.py::_APPROVAL_TIMEOUT

type approvalTimeoutMsg struct{ id int }

// applyApprovalRequest はdelegate.ApplyApprovalHandler経由で委任実行goroutineから
// Updateループへ渡される適用承認依頼。
type applyApprovalRequest struct {
	id           int
	label        string
	changedFiles []string
	summary      string
	respCh       chan bool
}

type applyApprovalTimeoutMsg struct{ id int }

// turnEvent はReActループを回すゴルーチンからUpdateループへ渡すイベント。
type turnEvent struct {
	text     string
	tool     *react.ToolActivity
	done     bool
	history  []llm.Message
	finalErr error
}

const checkpointPath = ".mimic/checkpoint.json"

// programRef はmain.goでtea.NewProgram生成直後にSetProgramRefで登録される
// *tea.Program参照。`/model`引数なし時のライブモデルセレクタが、Bubble Teaの
// レンダリング/入力読み取りを一時停止して端末を明け渡す（ReleaseTerminal）ために
// 使う。Modelはtea.NewProgram呼び出し時点ではまだ*tea.Programを持てない
// （鶏と卵の関係）ため、パッケージレベルの変数で後から差し込む
// （既存のSetWriteApprovalHandler等と同じ橋渡しパターン）。
var programRef *tea.Program

// SetProgramRef はmain.goが起動時に一度だけ呼び出す。
func SetProgramRef(p *tea.Program) {
	programRef = p
}

func NewModel(client *llm.Client, systemPrompt string, cfg *config.Config) Model {
	ta := textarea.New()
	ta.Placeholder = "メッセージを入力... (Enterで送信、Ctrl+Nで改行、Ctrl+Cで終了)"
	ta.Focus()
	ta.CharLimit = 0
	ta.ShowLineNumbers = false
	ta.SetHeight(1)
	// textareaのデフォルトStylesはCursorLineに背景色を塗るため、入力欄全体の
	// 背景透過方針に合わせて背景なしのスタイルへ上書きする。
	styles := ta.Styles()
	styles.Focused.CursorLine = styles.Focused.CursorLine.UnsetBackground()
	styles.Focused.Base = styles.Focused.Base.UnsetBackground()
	styles.Blurred.CursorLine = styles.Blurred.CursorLine.UnsetBackground()
	styles.Blurred.Base = styles.Blurred.Base.UnsetBackground()
	ta.SetStyles(styles)

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

	approvalCh := make(chan approvalRequest)
	// 承認ハンドラはツール実行goroutine（RunTurn内）から呼ばれ、Updateループが
	// 消費するまでブロックする（Python版のthreading.Event+call_from_threadと
	// 同じ「UIスレッドへ判断を委ねて待つ」構造をチャンネルで実現する）。
	tools.SetWriteApprovalHandler(func(toolName, path, preview string) bool {
		respCh := make(chan bool, 1)
		approvalCh <- approvalRequest{toolName: toolName, path: path, preview: preview, respCh: respCh}
		return <-respCh
	})

	applyApprovalCh := make(chan applyApprovalRequest)
	// APPLY_APPROVAL=ask/threshold時のみ実際に発動する（既定では
	// delegate.needsApplyApprovalが常にfalseを返すためこのハンドラは呼ばれない）。
	delegate.SetApplyApprovalHandler(func(label string, changedFiles []string, summary string) bool {
		respCh := make(chan bool, 1)
		applyApprovalCh <- applyApprovalRequest{label: label, changedFiles: changedFiles, summary: summary, respCh: respCh}
		return <-respCh
	})

	hostExecApprovalCh := make(chan hostExecApprovalRequest)
	tools.SetHostExecApprovalHandler(func(command, reason string) bool {
		respCh := make(chan bool, 1)
		hostExecApprovalCh <- hostExecApprovalRequest{command: command, reason: reason, respCh: respCh}
		return <-respCh
	})

	autoGit := vcs.New()
	// delegate_to_team/delegate_to_worker等の適用後コミットを、通常ターンと
	// 同じAutoGitインスタンスに積ませてsquash対象に含める
	// （Python版 team.py::set_team_autogit の移植）。
	delegate.SetTeamAutoGit(autoGit)
	// ビューアの委任親子ツリー表示のため、DirectorのReactLogをinternal/delegateへ
	// 共有する（Python版 team.py::_log_team_event がReactLogへ直接書き込むのと
	// 同じ役割。Go版はinternal/delegateがreactLogを保持していないため注入する）。
	delegate.SetTeamReactLog(reactLog)
	// get_delegation_trace/search_historyツールがセッションログを参照できるよう、
	// TUI(常にDirector)のsessionsディレクトリを共有する。
	delegate.SetSessionsDir(sessionsDir)
	tools.SetSessionsDirForTool(sessionsDir)

	specialistRegistry := registry.Exclude(specialistExcludedTools, []string{"mcp__"})

	// 起動時デフォルトモード: specialist（委任特化）。MIMIC_DEFAULT_MODE=interactive
	// で従来のReActを既定にできる（Python版 app.py:297-302 の移植）。
	agentMode := "interactive"
	activeRegistry := registry
	activeSystemPrompt := systemPrompt
	defaultMode := strings.ToLower(strings.TrimSpace(os.Getenv("MIMIC_DEFAULT_MODE")))
	if defaultMode == "" {
		defaultMode = "specialist"
	}
	if defaultMode != "interactive" {
		agentMode = "specialist"
		activeRegistry = specialistRegistry
		activeSystemPrompt = systemPrompt + specialistSystemPrompt + delegate.LoadSavedRolesSection(10)
	}

	busySpinner := spinner.New(
		spinner.WithSpinner(spinner.MiniDot),
		spinner.WithStyle(lipgloss.NewStyle().Foreground(colAmber)),
	)
	cpuBar := progress.New(progress.WithWidth(8), progress.WithoutPercentage(), progress.WithColors(colTitle))
	memBar := progress.New(progress.WithWidth(8), progress.WithoutPercentage(), progress.WithColors(colTitle))

	return Model{
		input:                ta,
		busySpinner:          busySpinner,
		cpuBar:               cpuBar,
		memBar:               memBar,
		pendingDelegationIdx: -1,
		client:               client,
		cfg:                  cfg,
		systemPrompt:         activeSystemPrompt,
		baseSystemPrompt:     systemPrompt,
		registry:             activeRegistry,
		fullRegistry:         registry,
		specialistRegistry:   specialistRegistry,
		agentMode:            agentMode,
		history:              history,
		log:                  log,
		reactLog:             reactLog,
		callLog:              vcs.NewToolCallLog(),
		autoGit:              autoGit,
		cwd:                  cwd,
		approvalCh:           approvalCh,
		applyApprovalCh:      applyApprovalCh,
		hostExecApprovalCh:   hostExecApprovalCh,
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
	return tea.Batch(textarea.Blink, waitForApproval(m.approvalCh), waitForApplyApproval(m.applyApprovalCh),
		waitForHostExecApproval(m.hostExecApprovalCh), systemTickCmd(), m.busySpinner.Tick)
}

func waitForHostExecApproval(ch chan hostExecApprovalRequest) tea.Cmd {
	return func() tea.Msg {
		return <-ch
	}
}

func hostExecApprovalTimeoutCmd(id int) tea.Cmd {
	return tea.Tick(approvalTimeoutSec*time.Second, func(time.Time) tea.Msg {
		return hostExecApprovalTimeoutMsg{id: id}
	})
}

func waitForApplyApproval(ch chan applyApprovalRequest) tea.Cmd {
	return func() tea.Msg {
		return <-ch
	}
}

func applyApprovalTimeoutCmd(id int) tea.Cmd {
	return tea.Tick(approvalTimeoutSec*time.Second, func(time.Time) tea.Msg {
		return applyApprovalTimeoutMsg{id: id}
	})
}

// waitForApproval は承認依頼チャンネルを1件読み、tea.Msgとして返す
// （turnEventと同様、消費するたびにUpdate側で再度armし直すワンショット方式）。
func waitForApproval(ch chan approvalRequest) tea.Cmd {
	return func() tea.Msg {
		return <-ch
	}
}

func approvalTimeoutCmd(id int) tea.Cmd {
	return tea.Tick(approvalTimeoutSec*time.Second, func(time.Time) tea.Msg {
		return approvalTimeoutMsg{id: id}
	})
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
// 幅が未確定（レイアウト計算前）でもMarkdown装飾自体は常に適用する。
// colThink はthinkブロック専用のカラーテーマ（Python版 utils.py::
// render_markdown_thinker が通常のMarkdown描画と別の淡いテーマを使うのに
// 相当。灰色寄りのミント系にして「思考中」であることを視覚的に区別する）。
var colThink = lipgloss.Color("#6B8F82")

// isThinkBoxLine はthinkブロックのボーダーボックス行（境界線/内容行）かどうかを
// 判定する（appendThinkSegmentが生成する行のプレフィックスで判定）。
func isThinkBoxLine(line string) bool {
	return strings.HasPrefix(line, "╭─ 💭") || strings.HasPrefix(line, "│ ") || strings.HasPrefix(line, "╰")
}

// agentTurnMarker はエージェントの発言ターン開始を示すマーカー行
// （startTurnが挿入し、renderLogが■ AGENTパネル見出しと同じcolAccentで着色する）。
const agentTurnMarker = "■ Agent"

// userLinePrefix はユーザーが送信した発言行の生テキスト上のプレフィックス
// （Enter送信/スラッシュコマンドのエコー、両方ともこの形式で追加される）。
const userLinePrefix = "> "

// colUser はユーザー発言の着色に使う（パレット定義時から「Role表示色」と
// コメントされていたが、ユーザー発言とエージェント発言の判別用に未使用のまま
// だったcolPinkをここで用途通りに使う）。
var userLineStyle = lipgloss.NewStyle().Bold(true).Foreground(colPink)
var agentMarkerStyle = lipgloss.NewStyle().Bold(true).Foreground(colAccent)

// renderUserLine はユーザー発言行を装飾する。複数行入力（Ctrl+Nで改行）の
// 場合も想定し、先頭行の"> "だけを見やすい"❯ "に置き換えて全行を着色する。
func renderUserLine(line string) string {
	sub := strings.Split(line, "\n")
	for i, s := range sub {
		if i == 0 && strings.HasPrefix(s, userLinePrefix) {
			s = "❯ " + strings.TrimPrefix(s, userLinePrefix)
		}
		sub[i] = userLineStyle.Render(s)
	}
	return strings.Join(sub, "\n")
}

func (m Model) renderLog() string {
	w := m.viewport.Width()
	rendered := make([]string, len(m.log))
	for i, line := range m.log {
		switch {
		case isThinkBoxLine(line):
			// thinkブロックは通常のMarkdown装飾を適用せず専用カラーのみ適用する
			// （Python版 render_markdown_thinker が通常のrender_markdownとは
			// 別の軽量レンダラーである設計の移植）。
			rendered[i] = lipgloss.NewStyle().Foreground(colThink).Render(line)
		case line == agentTurnMarker:
			rendered[i] = agentMarkerStyle.Render(line)
		case strings.HasPrefix(line, userLinePrefix):
			// ユーザー発言とエージェント出力を一目で見分けられるよう、
			// ここだけ通常のMarkdown装飾をスキップして専用スタイルを適用する。
			rendered[i] = renderUserLine(line)
		default:
			rendered[i] = renderMarkdown(line)
		}
		if i == m.pendingDelegationIdx && m.streaming {
			rendered[i] += "\n      " + delegationPendingStyle.Render("⏳ 実行中...")
		}
	}
	if w <= 0 {
		return strings.Join(rendered, "\n")
	}
	style := lipgloss.NewStyle().Width(w)
	wrapped := make([]string, len(rendered))
	for i, line := range rendered {
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

// feedThinkAwareText はストリームチャンクをThinkAwareBuffer経由で処理し、
// <think>/<thought>ブロックを灰色の折りたたみ表示、それ以外を通常の
// アシスタント発言としてログへ流す（Python版 PipelineTypewriter::feed の
// _enter_think/_flush_think_raw/_exit_think の簡略移植）。
func (m *Model) feedThinkAwareText(chunk string) {
	for _, seg := range m.thinkBuf.Push(chunk) {
		m.appendThinkSegment(seg)
	}
}

// appendThinkSegment はthinkセグメントを灰色ボーダーの複数行ボックスとして
// 描画する（Python版 utils.py::PipelineTypewriter._enter_think/_flush_think_raw/
// _exit_think の移植。単一行への折りたたみではなく、思考内容を改行込みで
// そのまま「│ 」プレフィックス付きの複数行として表示する）。
func (m *Model) appendThinkSegment(seg thinkSegment) {
	if seg.IsThink {
		if !m.inThinkLine {
			m.flushRawBuffer(true) // think遷移前に生テキストバッファを強制flush
			m.closeOpenLine()
			m.log = append(m.log, "╭─ 💭 思考中 "+strings.Repeat("─", 50))
			m.inThinkLine = true
			m.thinkLineBuf = ""
		}
		m.thinkLineBuf += seg.Text
		for {
			idx := strings.Index(m.thinkLineBuf, "\n")
			if idx < 0 {
				break
			}
			line := m.thinkLineBuf[:idx]
			m.thinkLineBuf = m.thinkLineBuf[idx+1:]
			m.log = append(m.log, "│ "+line)
		}
		return
	}
	if m.inThinkLine {
		if m.thinkLineBuf != "" {
			m.log = append(m.log, "│ "+m.thinkLineBuf)
			m.thinkLineBuf = ""
		}
		m.log = append(m.log, "╰"+strings.Repeat("─", 62))
		m.inThinkLine = false
	}
	m.feedRawText(seg.Text)
}

// flushThinkBuffer はターン終了時に残バッファを強制フラッシュする。
func (m *Model) flushThinkBuffer() {
	for _, seg := range m.thinkBuf.Flush() {
		m.appendThinkSegment(seg)
	}
	if m.inThinkLine {
		if m.thinkLineBuf != "" {
			m.log = append(m.log, "│ "+m.thinkLineBuf)
			m.thinkLineBuf = ""
		}
		m.log = append(m.log, "╰"+strings.Repeat("─", 62))
	}
	m.thinkBuf = ThinkAwareBuffer{}
	m.inThinkLine = false
	m.flushRawBuffer(true)
}

// ── 生テキストのバッファリング（Python版 utils.py::PipelineTypewriter の
// Stage1相当。_should_flush/_flush_raw の移植）。改行 or 200文字に達するか、
// コードブロック(```)が閉じている場合にのみflushする。未閉じの```を含む
// チャンクを保持し続けることで、コードブロックの途中でログ行が分断される
// のを防ぐ。thinkブロックへの遷移時（appendThinkSegment）や
// ターン終了時（flushThinkBuffer）はforce=trueで強制flushする。

const rawFlushBufferSize = 200

// shouldFlushRawBuffer はバッファをflushしてよいかを判定する。
func shouldFlushRawBuffer(buf string) bool {
	if !strings.Contains(buf, "\n") && len(buf) < rawFlushBufferSize {
		return false
	}
	if strings.Count(buf, "```")%2 != 0 {
		return false // 未閉じのコードブロック中は保持し続ける
	}
	return true
}

// feedRawText はテキストをバッファへ追加し、flush条件を満たせば
// appendToOpenLineへ出力する。
func (m *Model) feedRawText(text string) {
	m.rawTextBuf += text
	if shouldFlushRawBuffer(m.rawTextBuf) {
		m.flushRawBuffer(false)
	}
}

// flushRawBuffer はバッファ内容をappendToOpenLineへ出力する。force=falseの
// 場合、最後の改行までのみ出力し残りはバッファに保持する（改行が無ければ
// 全量出力する＝Python版の`last_nl == -1`分岐と同じ）。
func (m *Model) flushRawBuffer(force bool) {
	if m.rawTextBuf == "" {
		return
	}
	lastNL := strings.LastIndex(m.rawTextBuf, "\n")
	var toFlush string
	if force || lastNL == -1 {
		toFlush = m.rawTextBuf
		m.rawTextBuf = ""
	} else {
		toFlush = m.rawTextBuf[:lastNL+1]
		m.rawTextBuf = m.rawTextBuf[lastNL+1:]
	}
	if toFlush != "" {
		m.appendToOpenLine(toFlush)
	}
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
	headerLines := lipgloss.Height(m.renderHeader())
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

	case tea.MouseWheelMsg:
		if m.active == tabFiles {
			m.handleFilesMouseWheel(msg.Mouse())
		}

	case tea.MouseClickMsg:
		if m.active == tabFiles && msg.Mouse().Button == tea.MouseLeft {
			m.handleFilesMouseClick(msg.Mouse())
		}

	case delegationResumeResultMsg:
		m.log = append(m.log, msg.text)
		m.openLine = false
		m.viewport.SetContent(m.renderLog())
		m.viewport.GotoBottom()
		return m, nil

	case modelSelectResultMsg:
		if msg.provider == nil {
			m.log = append(m.log, "  ✗ モデルセレクタの起動に失敗しました（変更なし）。")
		} else {
			m.client = llm.NewClient(msg.provider)
			m.history = nil
			m.log = append(m.log, fmt.Sprintf("  ✓ モデルを切り替えました: %s/%s\n  会話履歴をリセットしました。",
				m.client.ProviderName(), m.client.Model()))
		}
		m.openLine = false
		m.viewport.SetContent(m.renderLog())
		m.viewport.GotoBottom()
		return m, nil

	case tea.KeyPressMsg:
		if msg.String() == "ctrl+c" || msg.String() == "ctrl+q" {
			if m.cancelFunc != nil {
				m.cancelFunc()
			}
			// セッション終了時に.mdサマリーを自動保存する
			// （Python版 app.py::action_quit_app / autogit.py::ReactLog.save_session の移植）。
			if m.reactLog != nil && m.reactLog.EntryCount() > 0 {
				sessionsDir := filepath.Join(m.cwd, ".mimic", "sessions")
				m.reactLog.SaveSession(sessionsDir)
			}
			return m, tea.Quit
		}

		// 書き込み承認待ち中はY/n入力の確定のみを特別扱いし、それ以外の
		// タブ切替・チャット送信等は受け付けない（Python版の承認モード
		// 中はinput barがY/n専用になる挙動の移植）。
		if m.pendingApproval != nil {
			if msg.String() == "enter" {
				val := strings.ToLower(strings.TrimSpace(m.input.Value()))
				approved := val == "" || val == "y"
				m.input.Reset()
				m.adjustInputHeight()
				req := m.pendingApproval
				req.respCh <- approved
				respText := "  ✗ 拒否しました（処理を中断します）"
				if approved {
					respText = "  ✓ 承認しました"
				}
				m.log = append(m.log, respText)
				m.pendingApproval = nil
				m.openLine = false
				m.viewport.SetContent(m.renderLog())
				m.viewport.GotoBottom()
				return m, waitForApproval(m.approvalCh)
			}
			m.input, taCmd = m.input.Update(msg)
			return m, taCmd
		}

		// 委任apply承認待ち中も同様にY/n入力のみ受け付ける。
		if m.pendingApplyApproval != nil {
			if msg.String() == "enter" {
				val := strings.ToLower(strings.TrimSpace(m.input.Value()))
				approved := val == "" || val == "y"
				m.input.Reset()
				m.adjustInputHeight()
				req := m.pendingApplyApproval
				req.respCh <- approved
				respText := "  ✗ 適用を拒否しました（変更は破棄されます）"
				if approved {
					respText = "  ✓ 適用を承認しました"
				}
				m.log = append(m.log, respText)
				m.pendingApplyApproval = nil
				m.openLine = false
				m.viewport.SetContent(m.renderLog())
				m.viewport.GotoBottom()
				return m, waitForApplyApproval(m.applyApprovalCh)
			}
			m.input, taCmd = m.input.Update(msg)
			return m, taCmd
		}

		// ホスト実行承認待ち中も同様にY/n入力のみ受け付ける。
		if m.pendingHostExecApproval != nil {
			if msg.String() == "enter" {
				val := strings.ToLower(strings.TrimSpace(m.input.Value()))
				approved := val == "" || val == "y"
				m.input.Reset()
				m.adjustInputHeight()
				req := m.pendingHostExecApproval
				req.respCh <- approved
				respText := "  ✗ ホスト実行を拒否しました"
				if approved {
					respText = "  ✓ ホスト実行を承認しました"
				}
				m.log = append(m.log, respText)
				m.pendingHostExecApproval = nil
				m.openLine = false
				m.viewport.SetContent(m.renderLog())
				m.viewport.GotoBottom()
				return m, waitForHostExecApproval(m.hostExecApprovalCh)
			}
			m.input, taCmd = m.input.Update(msg)
			return m, taCmd
		}

		// /searchのヒット選択待ち（番号カンマ区切り/all/n）
		// （Python版 app.py::_cmd_search の on_response の移植）。
		if m.pendingSearchSelection != nil {
			if msg.String() == "enter" {
				resp := strings.ToLower(strings.TrimSpace(m.input.Value()))
				m.input.Reset()
				m.adjustInputHeight()
				sel := m.pendingSearchSelection
				m.pendingSearchSelection = nil
				m.applySearchSelection(sel, resp)
				return m, nil
			}
			m.input, taCmd = m.input.Update(msg)
			return m, taCmd
		}

		// /sessionsの詳細表示後の注入確認（y/n）
		// （Python版 app.py::_cmd_sessions の on_response の移植）。
		if m.pendingSessionInject != nil {
			if msg.String() == "enter" {
				resp := strings.ToLower(strings.TrimSpace(m.input.Value()))
				m.input.Reset()
				m.adjustInputHeight()
				inj := m.pendingSessionInject
				m.pendingSessionInject = nil
				m.applySessionInject(inj, resp)
				return m, nil
			}
			m.input, taCmd = m.input.Update(msg)
			return m, taCmd
		}

		// ファイルプレビュー内検索クエリ入力中は、Enter/Escape/Backspace以外の
		// キー入力をすべてクエリ文字として扱う（Python版 app.py::_open_file_search
		// 〜on_chat_input_submitのfile-search-input専用分岐の移植）。
		if m.fileSearchActive {
			switch msg.String() {
			case "enter":
				m.runFileSearch(m.fileSearchQuery)
				m.fileSearchActive = false
				return m, nil
			case "escape":
				m.closeFileSearch()
				return m, nil
			case "backspace":
				if m.fileSearchQuery == "" {
					// 空の状態でのBackspaceは検索バーを閉じる
					// （Python版 app.py::on_key の該当分岐の移植）。
					m.closeFileSearch()
					return m, nil
				}
				r := []rune(m.fileSearchQuery)
				m.fileSearchQuery = string(r[:len(r)-1])
				return m, nil
			case "space":
				m.fileSearchQuery += " "
				return m, nil
			default:
				if s := msg.String(); len([]rune(s)) == 1 {
					m.fileSearchQuery += s
				}
				return m, nil
			}
		}

		switch msg.String() {
		case "f1":
			m.active = tabChat
			return m, nil
		case "f2":
			m.active = tabFiles
			if !m.filesScanned {
				m.resetFilesTree()
				m.filesScanned = true
			}
			return m, nil
		case "f3":
			m.active = tabScratchpad
			return m, nil
		case "f4":
			m.active = tabLog
			return m, nil
		case "ctrl+l":
			// 画面クリア（Python版 app.py::action_clear_log の移植）。
			m.log = nil
			m.viewport.SetContent(m.renderLog())
			m.viewport.GotoTop()
			return m, nil
		case "pgup", "pgdown", "ctrl+home", "ctrl+end":
			// Python版 app.py::_active_scroll_target / action_scroll_* の移植。
			// Filesタブがアクティブな間はプレビューペインをスクロールし、
			// それ以外（Chat等）は従来通りメインログをスクロールする。
			if m.active == tabFiles {
				rows := clampMin(m.viewport.Height(), 1)
				switch msg.String() {
				case "pgup":
					m.filePreviewScroll -= rows
				case "pgdown":
					m.filePreviewScroll += rows
				case "ctrl+home":
					m.filePreviewScroll = 0
				case "ctrl+end":
					m.filePreviewScroll = previewMaxScroll(m.filePreview, rows)
				}
				if m.filePreviewScroll < 0 {
					m.filePreviewScroll = 0
				}
				return m, nil
			}
			switch msg.String() {
			case "pgup":
				m.viewport.PageUp()
			case "pgdown":
				m.viewport.PageDown()
			case "ctrl+home":
				m.viewport.GotoTop()
			case "ctrl+end":
				m.viewport.GotoBottom()
			}
			return m, nil
		}

		if m.active == tabFiles {
			visible := visibleFileEntries(m.files, m.cwd, m.filesExpanded)
			rows := clampMin(m.viewport.Height()-1, 1) // -1: ルート行ぶん
			switch msg.String() {
			case "up", "k":
				if m.filesCursor > 0 {
					m.filesCursor--
				}
				m.ensureFilesCursorVisible(rows)
				return m, nil
			case "down", "j":
				if m.filesCursor < len(visible)-1 {
					m.filesCursor++
				}
				m.ensureFilesCursorVisible(rows)
				return m, nil
			case "right", "l":
				// ディレクトリを展開し、子要素を表示する（cwdは変更しない。
				// Python版 Tree ウィジェットの矢印キー展開の移植）。
				if m.filesCursor >= 0 && m.filesCursor < len(visible) {
					e := visible[m.filesCursor]
					if e.isDir {
						m.filesExpanded[e.path] = true
					}
				}
				return m, nil
			case "left", "h":
				// ディレクトリを折りたたむ。
				if m.filesCursor >= 0 && m.filesCursor < len(visible) {
					e := visible[m.filesCursor]
					if e.isDir && m.filesExpanded[e.path] {
						delete(m.filesExpanded, e.path)
						m.ensureFilesCursorVisible(rows)
					}
				}
				return m, nil
			case "enter":
				if m.filesCursor >= 0 && m.filesCursor < len(visible) {
					e := visible[m.filesCursor]
					if e.isDir {
						// ディレクトリを選択したらそこへcwdを移動してツリーを
						// 作り直す（Python版 app.py::on_tree_node_selected の移植）。
						m.cwd = e.path
						m.resetFilesTree()
						m.log = append(m.log, fmt.Sprintf("  📁 作業Dir → %s", m.cwd))
						m.viewport.SetContent(m.renderLog())
					} else {
						m.openFilePreview(e.path)
					}
				}
				return m, nil
			case "backspace":
				// 親ディレクトリへ移動する（Python版 app.py::on_key の
				// file-tree focus時のBackspace処理の移植。ファイルシステム
				// ルートで親==自身になった場合は何もしない）。
				parent := filepath.Dir(m.cwd)
				if parent != m.cwd {
					m.cwd = parent
					m.resetFilesTree()
					m.log = append(m.log, fmt.Sprintf("  📁 作業Dir → %s", m.cwd))
					m.viewport.SetContent(m.renderLog())
				}
				return m, nil
			case "/":
				// プレビュー内検索を開く（Python版 app.py::_open_file_search の移植。
				// プレビューが開かれている場合のみ）。
				if m.filePath != "" {
					m.fileSearchActive = true
					m.fileSearchQuery = ""
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
			m.adjustInputHeight()
			if strings.HasPrefix(text, "/") {
				if updated, cmd, handled := m.runSlashCommand(text); handled {
					return updated, cmd
				}
			}
			m.history = append(m.history, llm.Message{Role: "user", Content: text})
			m.log = append(m.log, fmt.Sprintf("> %s", text))
			m.openLine = false
			m.viewport.SetContent(m.renderLog())
			m.viewport.GotoBottom()
			return m.startTurn()
		}

	case approvalRequest:
		m.approvalSeq++
		msg.id = m.approvalSeq
		m.pendingApproval = &msg
		m.closeOpenLine()
		m.log = append(m.log, renderApprovalBox(msg))
		m.viewport.SetContent(m.renderLog())
		m.viewport.GotoBottom()
		return m, approvalTimeoutCmd(msg.id)

	case hostExecApprovalRequest:
		m.hostExecApprovalSeq++
		msg.id = m.hostExecApprovalSeq
		m.pendingHostExecApproval = &msg
		m.closeOpenLine()
		m.log = append(m.log, renderHostExecApprovalBox(msg))
		m.viewport.SetContent(m.renderLog())
		m.viewport.GotoBottom()
		return m, hostExecApprovalTimeoutCmd(msg.id)

	case hostExecApprovalTimeoutMsg:
		if m.pendingHostExecApproval != nil && m.pendingHostExecApproval.id == msg.id {
			req := m.pendingHostExecApproval
			// Python版 app.py::_make_host_exec_approval_handler と同じく、
			// タイムアウト時は自動承認する（書き込み/適用承認と同じ既定動作。
			// 隔離なしでホストへ影響する操作のため、運用上はタイムアウトを
			// 十分長く取るか常時監視することが前提）。
			req.respCh <- true
			m.log = append(m.log, fmt.Sprintf("  ⏱ %d秒経過 → 自動承認", approvalTimeoutSec))
			m.pendingHostExecApproval = nil
			m.viewport.SetContent(m.renderLog())
			m.viewport.GotoBottom()
			return m, waitForHostExecApproval(m.hostExecApprovalCh)
		}
		return m, nil

	case systemTickMsg:
		m.systemCPUPercent = vcs.GetSystemCPUPercent()
		m.systemMemUsedMB, m.systemMemTotalMB = vcs.GetSystemMemInfo()
		return m, systemTickCmd()

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.busySpinner, cmd = m.busySpinner.Update(msg)
		return m, cmd

	case approvalTimeoutMsg:
		if m.pendingApproval != nil && m.pendingApproval.id == msg.id {
			req := m.pendingApproval
			req.respCh <- true
			m.log = append(m.log, fmt.Sprintf("  ⏱ %d秒経過 → 自動承認", approvalTimeoutSec))
			m.pendingApproval = nil
			m.viewport.SetContent(m.renderLog())
			m.viewport.GotoBottom()
			return m, waitForApproval(m.approvalCh)
		}
		return m, nil

	case applyApprovalRequest:
		m.applyApprovalSeq++
		msg.id = m.applyApprovalSeq
		m.pendingApplyApproval = &msg
		m.closeOpenLine()
		m.log = append(m.log, renderApplyApprovalBox(msg))
		m.viewport.SetContent(m.renderLog())
		m.viewport.GotoBottom()
		return m, applyApprovalTimeoutCmd(msg.id)

	case applyApprovalTimeoutMsg:
		if m.pendingApplyApproval != nil && m.pendingApplyApproval.id == msg.id {
			req := m.pendingApplyApproval
			req.respCh <- true
			m.log = append(m.log, fmt.Sprintf("  ⏱ %d秒経過 → 自動承認", approvalTimeoutSec))
			m.pendingApplyApproval = nil
			m.viewport.SetContent(m.renderLog())
			m.viewport.GotoBottom()
			return m, waitForApplyApproval(m.applyApprovalCh)
		}
		return m, nil

	case turnEvent:
		// 委任が返ってきた（＝次に何らかのイベントが来た）時点で「実行中」表示は
		// 必ず消す。委任ツールは同期実行のため、次のイベントが来た時点でその
		// 委任が完了しているのは保証されている。
		m.pendingDelegationIdx = -1
		switch {
		case msg.finalErr != nil:
			m.flushThinkBuffer()
			m.closeOpenLine()
			m.log = append(m.log, fmt.Sprintf("[エラー] %v", msg.finalErr))
			m.streaming = false
		case msg.tool != nil:
			m.flushThinkBuffer()
			m.closeOpenLine()
			if card := renderDelegationCall(msg.tool.Name, msg.tool.ArgsPreview); card != "" {
				m.log = append(m.log, card)
				m.pendingDelegationIdx = len(m.log) - 1
			} else if !alwaysApprovedTools[msg.tool.Name] {
				// write_file/edit_file/patch_file/run_host_commandは直後に必ず
				// 承認ダイアログが出て、そこにツール名・パス・プレビューが
				// 表示されるため、ここでのツール呼び出し行は省略する
				// （表示が二重になり情報過多になるとのフィードバックを反映）。
				m.log = append(m.log, renderToolCallLine(msg.tool.Name, msg.tool.ArgsPreview))
			}
		case msg.done:
			m.flushThinkBuffer()
			m.closeOpenLine()
			m.streaming = false
			m.history = msg.history
		default:
			m.feedThinkAwareText(msg.text)
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
		m.adjustInputHeight()
		vp, cmd := m.viewport.Update(msg)
		m.viewport, vpCmd = vp, cmd
	}
	return m, tea.Batch(taCmd, vpCmd)
}

const (
	inputMinLines = 1 // Python版 app.py::_INPUT_MIN_LINES
	inputMaxLines = 5 // Python版 app.py::_INPUT_MAX_LINES
)

// adjustInputHeight は入力欄の行数に応じて高さを1〜5行の範囲で自動調整する
// （Python版 app.py::_on_input_changed の移植）。
func (m *Model) adjustInputHeight() {
	n := strings.Count(m.input.Value(), "\n") + 1
	if n < inputMinLines {
		n = inputMinLines
	}
	if n > inputMaxLines {
		n = inputMaxLines
	}
	if m.input.Height() != n {
		m.input.SetHeight(n)
	}
}

func (m Model) startTurn() (tea.Model, tea.Cmd) {
	m.streaming = true
	// ユーザー発言との境界を一目で分かるように、ターン開始時にエージェント側の
	// 発言だとわかるマーカー行を1本挟む（renderLogで■ AGENT見出しと同じ
	// colAccentに着色される）。
	m.log = append(m.log, agentTurnMarker)
	m.thinkBuf = ThinkAwareBuffer{}
	m.inThinkLine = false
	m.thinkLineBuf = ""
	m.rawTextBuf = ""
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

// fileScanIgnore はPython版 app.py::_populate_tree の ignore セットをそのまま踏襲する。
// これに加えて、名前が"."で始まるすべてのファイル/ディレクトリも除外する
// （Python版の `item.name.startswith(".")` 判定の移植。.git/.venv等は結果的に
// この規則にも合致するが、Python版の明示セットとの対応関係を保つため両方残す）。
var fileScanIgnore = map[string]bool{
	".git": true, "node_modules": true, ".venv": true, "venv": true,
	"__pycache__": true, ".mypy_cache": true,
}

// maxFileScanDepth はPython版 app.py::_populate_tree の `if depth > 2: return` と
// 同じ深さ制限（ルートを0として、0/1/2の3階層まで）。
const maxFileScanDepth = 2

// scanFiles はcwd配下を再帰的に走査し、フラットな一覧にする
// （Python版 app.py::_build_file_tree / _populate_tree の移植。実際のTreeウィジェットの
// 代わりに、深さに応じたインデント付きフラットリストとして表現する）。
func scanFiles(root string) []fileEntry {
	var out []fileEntry
	var walk func(dir string, depth int)
	walk = func(dir string, depth int) {
		if depth > maxFileScanDepth {
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
			if fileScanIgnore[e.Name()] || strings.HasPrefix(e.Name(), ".") {
				continue
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

// visibleFileEntries はscanFilesが返した全件（depth 0〜maxFileScanDepth）のうち、
// 祖先ディレクトリがすべて展開済みのものだけを返す（Python版のTree標準挙動:
// ルートのみ自動展開、それ以外のノードは明示的に開くまで子要素が隠れている、
// の移植）。
func visibleFileEntries(files []fileEntry, root string, expanded map[string]bool) []fileEntry {
	var out []fileEntry
	for _, e := range files {
		dir := filepath.Dir(e.path)
		visible := true
		for dir != root {
			if !expanded[dir] {
				visible = false
				break
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
		if visible {
			out = append(out, e)
		}
	}
	return out
}

// ensureFilesCursorVisible はファイルツリーのカーソルが表示領域内に収まるよう
// スクロール位置を調整する（Python版 Tree ウィジェットの自動スクロールの移植）。
func (m *Model) ensureFilesCursorVisible(rows int) {
	if rows <= 0 {
		return
	}
	if m.filesCursor < m.filesScrollTop {
		m.filesScrollTop = m.filesCursor
	}
	if m.filesCursor >= m.filesScrollTop+rows {
		m.filesScrollTop = m.filesCursor - rows + 1
	}
	if m.filesScrollTop < 0 {
		m.filesScrollTop = 0
	}
}

// resetFilesTree はcwd変更時にツリー状態を初期化する（Python版
// _build_file_tree が毎回ルートのみ展開した新規Treeを組み立てるのと同じ挙動）。
func (m *Model) resetFilesTree() {
	m.files = scanFiles(m.cwd)
	m.filesExpanded = map[string]bool{}
	m.filesCursor = 0
	m.filesScrollTop = 0
	m.filePath = ""
	m.filePreview = ""
	m.filePreviewScroll = 0
}

// filesPaneBoundary はFilesタブでツリー領域とプレビュー領域の境界となる
// 画面X座標を返す（マウスがどちらのペイン上にあるかの判定用。renderBody/
// renderFilesのレイアウト計算[hPad=1 + fileTreeWidth]を複製する）。
func (m Model) filesPaneBoundary() int {
	innerWidth := clamp0(m.width - 2)
	return 1 + fileTreeWidth(innerWidth)
}

const filesMouseWheelStep = 3

// handleFilesMouseWheel はFilesタブでのマウスホイールをツリー/プレビューの
// スクロールに割り当てる（ホイール位置のX座標でどちらのペインを操作するか
// 判定する。Python版はTree/RichLogがネイティブにホイール対応済みのため
// 明示的なコードは無いが、同等のUXをGo版で再現する）。
func (m *Model) handleFilesMouseWheel(ev tea.Mouse) {
	inTree := ev.X < m.filesPaneBoundary()
	rows := clampMin(m.viewport.Height()-1, 1)
	switch ev.Button {
	case tea.MouseWheelUp:
		if inTree {
			m.filesCursor -= filesMouseWheelStep
			if m.filesCursor < 0 {
				m.filesCursor = 0
			}
			m.ensureFilesCursorVisible(rows)
		} else {
			m.filePreviewScroll -= filesMouseWheelStep
			if m.filePreviewScroll < 0 {
				m.filePreviewScroll = 0
			}
		}
	case tea.MouseWheelDown:
		if inTree {
			visible := visibleFileEntries(m.files, m.cwd, m.filesExpanded)
			m.filesCursor += filesMouseWheelStep
			if max := clamp0(len(visible) - 1); m.filesCursor > max {
				m.filesCursor = max
			}
			m.ensureFilesCursorVisible(rows)
		} else {
			previewRows := clampMin(m.viewport.Height(), 1)
			m.filePreviewScroll += filesMouseWheelStep
			if max := previewMaxScroll(m.filePreview, previewRows); m.filePreviewScroll > max {
				m.filePreviewScroll = max
			}
		}
	}
}

// handleFilesMouseClick はツリー領域の行クリックをカーソル移動＋選択
// （ディレクトリならcd、ファイルならプレビュー表示）として扱う
// （Enterキー押下と同じ処理。Python版 Tree ウィジェットのクリック選択に相当）。
// プレビュー領域のクリックは何もしない。
func (m *Model) handleFilesMouseClick(ev tea.Mouse) {
	if ev.X >= m.filesPaneBoundary() {
		return
	}
	row := ev.Y - m.filesBodyTop()
	if row <= 0 {
		return // ルート行（0行目）のクリックは無視
	}
	visible := visibleFileEntries(m.files, m.cwd, m.filesExpanded)
	idx := m.filesScrollTop + (row - 1)
	if idx < 0 || idx >= len(visible) {
		return
	}
	m.filesCursor = idx
	e := visible[idx]
	if e.isDir {
		m.cwd = e.path
		m.resetFilesTree()
		m.log = append(m.log, fmt.Sprintf("  📁 作業Dir → %s", m.cwd))
		m.viewport.SetContent(m.renderLog())
	} else {
		m.openFilePreview(e.path)
	}
}

// runFileSearch はプレビュー内検索を実行する（Python版 app.py::_run_file_search
// の移植。正規表現として不正なパターンはリテラル一致にフォールバックする）。
func (m *Model) runFileSearch(pattern string) {
	if pattern == "" || len(m.filePreviewAllLines) == 0 {
		m.closeFileSearch()
		return
	}
	re, err := regexp.Compile("(?i)" + pattern)
	if err != nil {
		re = regexp.MustCompile("(?i)" + regexp.QuoteMeta(pattern))
	}
	matches := make(map[int]bool)
	for i, line := range m.filePreviewAllLines {
		if re.MatchString(line) {
			matches[i] = true
		}
	}
	m.filePreviewMatches = matches
	m.filePreviewSearching = true
	m.filePreviewScroll = 0
}

// closeFileSearch は検索モードを終了し、通常のプレビュー表示に戻す。
func (m *Model) closeFileSearch() {
	m.fileSearchActive = false
	m.fileSearchQuery = ""
	m.filePreviewSearching = false
	m.filePreviewMatches = nil
}

// openFilePreview はファイルプレビューを開き、検索状態をリセットする
// （Python版 app.py::_show_file_preview の移植）。
func (m *Model) openFilePreview(path string) {
	m.filePath = path
	m.filePreview = readPreview(path)
	m.filePreviewScroll = 0
	m.fileSearchActive = false
	m.fileSearchQuery = ""
	m.filePreviewSearching = false
	m.filePreviewMatches = nil
	if data, err := os.ReadFile(path); err == nil {
		m.filePreviewAllLines = strings.Split(string(data), "\n")
	} else {
		m.filePreviewAllLines = nil
	}
}

// previewMaxScroll はプレビューペインの最終ページに対応するスクロール行数を返す
// （Ctrl+End用）。
func previewMaxScroll(preview string, rows int) int {
	if preview == "" {
		return 0
	}
	n := strings.Count(preview, "\n") + 1
	max := n - rows
	if max < 0 {
		max = 0
	}
	return max
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

// renderApprovalBox はPython版 app.py::_make_approval_handler のASCII枠
// （┌─ 書き込み確認 ─...）を再現する。
func renderApprovalBox(req approvalRequest) string {
	var b strings.Builder
	b.WriteString("\n  ┌─ 書き込み確認 ──────────────────────────────────────\n")
	b.WriteString(fmt.Sprintf("  │  ツール : %s\n", req.toolName))
	b.WriteString(fmt.Sprintf("  │  ファイル: %s\n", req.path))
	b.WriteString("  │\n")
	lines := strings.Split(req.preview, "\n")
	if len(lines) > 20 {
		lines = lines[:20]
	}
	for _, line := range lines {
		b.WriteString("  │  " + line + "\n")
	}
	b.WriteString("  └──────────────────────────────────────────────────────\n")
	b.WriteString(fmt.Sprintf("  実行しますか？ [Y/n] (%d秒で自動承認): ", approvalTimeoutSec))
	return b.String()
}

// renderApplyApprovalBox はPython版 app.py::_make_apply_approval_handler の
// ASCII枠の移植（委任結果の適用可否をユーザーに問う）。
func renderApplyApprovalBox(req applyApprovalRequest) string {
	var b strings.Builder
	b.WriteString("\n  ┌─ 委任結果の適用確認 ──────────────────────────────────\n")
	for i, line := range strings.Split(strings.TrimSpace(req.label), "\n") {
		prefix := "  │  委任  : "
		if i > 0 {
			prefix = "  │          "
		}
		b.WriteString(prefix + line + "\n")
	}
	b.WriteString(fmt.Sprintf("  │  変更ファイル数: %d\n", len(req.changedFiles)))
	for _, f := range req.changedFiles {
		b.WriteString("  │    - " + f + "\n")
	}
	b.WriteString("  │\n")
	for _, line := range strings.Split(req.summary, "\n") {
		b.WriteString("  │  " + line + "\n")
	}
	b.WriteString("  └──────────────────────────────────────────────────────\n")
	b.WriteString(fmt.Sprintf("  適用しますか？ [Y/n] (%d秒で自動承認): ", approvalTimeoutSec))
	return b.String()
}

// renderHostExecApprovalBox はPython版 app.py::_make_host_exec_approval_handler の
// ASCII枠の移植（ホスト直接実行の承認をユーザーに問う。隔離なしで実システムに
// 影響することを明示する）。
func renderHostExecApprovalBox(req hostExecApprovalRequest) string {
	var b strings.Builder
	b.WriteString("\n  ┌─ ⚠ ホスト直接実行の承認 ─────────────────────────────\n")
	b.WriteString(fmt.Sprintf("  │  コマンド: %s\n", firstLine(req.command, 200)))
	b.WriteString(fmt.Sprintf("  │  理由    : %s\n", firstLine(req.reason, 200)))
	b.WriteString("  │  ※ 隔離なしで実システムに影響します（デプロイ・インストール等）\n")
	b.WriteString("  └──────────────────────────────────────────────────────\n")
	b.WriteString(fmt.Sprintf("  実行しますか？ [Y/n] (%d秒で自動承認): ", approvalTimeoutSec))
	return b.String()
}

func firstLine(s string, max int) string {
	if idx := strings.IndexByte(s, '\n'); idx >= 0 {
		s = s[:idx]
	}
	if len(s) > max {
		s = s[:max]
	}
	return s
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
		lines = append(lines, lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color(c)).Render(l))
	}
	sepStyle := lipgloss.NewStyle().Foreground(lipgloss.Color(mimicArtDimColor))
	sep := sepStyle.Render(" " + strings.Repeat("─", 50))
	subtitle := m.client.Model() + "  ·  " + m.cwd
	sub := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color(mimicArtColors[len(mimicArtColors)-1])).Render(" " + subtitle)
	lines = append(lines, sep, sub, sep)
	return strings.Join(lines, "\n")
}

// renderStatusPanel はPython版の #status-panel（■ AGENT / ■ SYSTEM セクション）を
// 再現する（固定幅36）。
func (m Model) renderStatusPanel() string {
	const panelWidth = 36
	statusText := lipgloss.NewStyle().Bold(true).Foreground(colAccent).Render("● IDLE")
	if m.streaming {
		statusText = m.busySpinner.View() + lipgloss.NewStyle().Bold(true).Foreground(colAmber).Render(" BUSY")
	}
	heading := lipgloss.NewStyle().Bold(true).Foreground(colAccent).Render("■ AGENT")
	status := "  Status: " + statusText

	memPct := 0.0
	if m.systemMemTotalMB > 0 {
		memPct = m.systemMemUsedMB / m.systemMemTotalMB * 100.0
	}
	sysHeading := lipgloss.NewStyle().Bold(true).Foreground(colAccent).Render("■ SYSTEM")
	valStyle := lipgloss.NewStyle().Foreground(colTitle)
	sysCPU := fmt.Sprintf("  CPU %s %s", m.cpuBar.ViewAs(m.systemCPUPercent/100), valStyle.Render(fmt.Sprintf("%4.1f%%", m.systemCPUPercent)))
	sysMem := fmt.Sprintf("  MEM %s %s", m.memBar.ViewAs(memPct/100), valStyle.Render(fmt.Sprintf("%.0f/%.0fMB", m.systemMemUsedMB, m.systemMemTotalMB)))

	content := heading + "\n" + status + "\n" + sysHeading + "\n" + sysCPU + "\n" + sysMem

	// 罫線ではなく余白のみで左隣（ASCIIアート）と区切る
	// （背景色は明示的に塗らず、端末側の背景・透過設定をそのまま透けさせる）。
	return lipgloss.NewStyle().
		Width(panelWidth - 2).MaxWidth(panelWidth - 2).
		Foreground(colText).
		PaddingLeft(3).
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
		Padding(0, 2).
		Render(art)

	row := lipgloss.JoinHorizontal(lipgloss.Top, artBox, panel)
	// 各行ごとに実幅を測って右端をスペースで埋める（背景色は塗らず、
	// 端末側の背景をそのまま透けさせる）。
	rowLines := strings.Split(row, "\n")
	for i, rl := range rowLines {
		gap := clamp0(m.width - lipgloss.Width(rl))
		if gap > 0 {
			rowLines[i] = rl + strings.Repeat(" ", gap)
		}
	}
	// 罫線での下部境界線は使わず、アート内の淡色区切り行（renderTitleArt側で
	// 既に描画済み）と余白のみで下と区切る。
	return row
}

func (m Model) renderTabs() string {
	var rendered []string
	for i, label := range tabLabels {
		style := lipgloss.NewStyle().Padding(0, 2).Foreground(colMuted)
		if tabID(i) == m.active {
			style = lipgloss.NewStyle().Padding(0, 2).Bold(true).Underline(true).Foreground(colAccent)
		}
		rendered = append(rendered, style.Render(fmt.Sprintf("%s [F%d]", label, i+1)))
	}
	bar := lipgloss.JoinHorizontal(lipgloss.Top, rendered...)
	// 背景ブロック塗りではなく、選択タブの下線+アクセント色のみで現在地を示す
	// （背景は端末側を透けさせる方針を全タブで統一）。
	return lipgloss.NewStyle().Height(1).MaxHeight(1).Render(bar)
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
		content = m.renderScratchpad(innerWidth)
	case tabLog:
		content = m.renderLogTab(innerWidth)
	}

	// 背景色は明示的に塗らず、端末側の背景（透過設定含む）をそのまま透けさせる。
	style := lipgloss.NewStyle().Width(innerWidth).MaxWidth(innerWidth).Height(height).MaxHeight(height)
	if m.active != tabChat {
		style = style.Padding(0, hPad)
	}
	return style.Render(content)
}

// fileTreeWidth はFilesタブのツリー幅を計算する（renderFilesとマウスの
// 当たり判定[handleFilesMouse]の両方から同じ式を使うための共通ヘルパー。
// 計算がずれると「見た目と実際にクリックできる位置がずれる」バグになるため
// 必ずこの関数を経由すること）。
func fileTreeWidth(width int) int {
	treeWidth := clampMin(width/3, 20)
	if treeWidth > width-4 {
		treeWidth = clampMin(width-4, 1)
	}
	return treeWidth
}

// filesBodyTop はFilesタブ本文（renderBody）が画面上で開始するY座標
// （0始まり）を返す。renderFullのheader+tabsの積み上げと同じ計算をマウス
// 当たり判定用に複製する。
func (m Model) filesBodyTop() int {
	return lipgloss.Height(m.renderHeader()) + 1 // +1 はタブ行
}

func (m Model) renderFiles(width, height int) string {
	treeWidth := fileTreeWidth(width)
	previewWidth := clampMin(width-treeWidth-3, 1)

	// ツリー本体（Python版 Tree ウィジェット: ルートのみ自動展開、他ノードは
	// 展開するまで子要素が非表示。折りたたみディレクトリには▸、展開済みには▾を付す）。
	visible := visibleFileEntries(m.files, m.cwd, m.filesExpanded)
	rootLabel := "📁 " + m.cwd
	rootLine := lipgloss.NewStyle().Foreground(colCyan).Bold(true).MaxWidth(treeWidth).Render(rootLabel)

	var itemLines []string
	for i, e := range visible {
		indent := strings.Repeat("  ", e.depth+1)
		icon := "📄 "
		if e.isDir {
			icon = "▾ 📁 "
			if !m.filesExpanded[e.path] {
				icon = "▸ 📁 "
			}
		}
		line := indent + icon + e.name
		st := lipgloss.NewStyle().Foreground(colText)
		if i == m.filesCursor {
			st = lipgloss.NewStyle().Foreground(colOnAccent).Background(colAccent).Bold(true)
		} else if e.isDir {
			st = lipgloss.NewStyle().Foreground(colCyan)
		}
		itemLines = append(itemLines, st.MaxWidth(treeWidth).Render(line))
	}
	if len(visible) == 0 {
		itemLines = append(itemLines, lipgloss.NewStyle().Foreground(colMuted).Render("  (空、またはスキャン待ち)"))
	}

	// ツリーの表示可能行数（ルート行を除く）に応じてスクロールウィンドウを切り出す
	// （Python版 Tree ウィジェットの自動スクロールの移植）。
	treeRows := clampMin(height-1, 1)
	start := clampMin(m.filesScrollTop, 0)
	if start > clamp0(len(itemLines)-1) {
		start = clamp0(len(itemLines) - 1)
	}
	end := start + treeRows
	if end > len(itemLines) {
		end = len(itemLines)
	}
	treeLines := append([]string{rootLine}, itemLines[start:end]...)
	tree := strings.Join(treeLines, "\n")

	var preview string
	if m.filePreviewSearching {
		// 検索結果表示: マッチ行±2行のコンテキストのみをハイライト付きで表示
		// （Python版 app.py::_run_file_search / _render_preview の移植）。
		var contextIdx []int
		seen := make(map[int]bool)
		for i := range m.filePreviewMatches {
			for d := -2; d <= 2; d++ {
				idx := i + d
				if idx >= 0 && idx < len(m.filePreviewAllLines) && !seen[idx] {
					seen[idx] = true
					contextIdx = append(contextIdx, idx)
				}
			}
		}
		sort.Ints(contextIdx)
		var lines []string
		for _, idx := range contextIdx {
			lineText := fmt.Sprintf("%4d %s", idx+1, m.filePreviewAllLines[idx])
			if m.filePreviewMatches[idx] {
				lineText = lipgloss.NewStyle().Bold(true).Foreground(colAmber).Render(lineText)
			}
			lines = append(lines, lineText)
		}
		preview = strings.Join(lines, "\n")
		if len(lines) == 0 {
			preview = "（マッチする行がありません）"
		}
	} else {
		previewLines := strings.Split(m.filePreview, "\n")
		previewRows := clampMin(height, 1)
		pStart := clampMin(m.filePreviewScroll, 0)
		if pStart > clamp0(len(previewLines)-1) {
			pStart = clamp0(len(previewLines) - 1)
		}
		pEnd := pStart + previewRows
		if pEnd > len(previewLines) {
			pEnd = len(previewLines)
		}
		preview = strings.Join(previewLines[pStart:pEnd], "\n")
		if m.filePreview == "" {
			preview = "↑/↓ でファイル選択、Enterでプレビュー  (←/→でディレクトリ展開/折りたたみ)"
		}
	}

	previewHeader := ""
	if m.filePath != "" {
		rel, _ := filepath.Rel(m.cwd, m.filePath)
		headerLine := rel
		if m.filePreviewSearching {
			headerLine += fmt.Sprintf("  [%d マッチ行]", len(m.filePreviewMatches))
		}
		previewHeader = lipgloss.NewStyle().Foreground(colAccent).Bold(true).Render(headerLine) + "\n"
	}
	if m.fileSearchActive {
		// 検索クエリ入力中のプロンプト行（Python版の#file-search-barに相当）。
		searchLine := lipgloss.NewStyle().Foreground(colOnAccent).Background(colAmber).Render(
			"/ " + m.fileSearchQuery + "█  Enter=確定 Escape=閉じる")
		previewHeader += searchLine + "\n"
	}

	left := lipgloss.NewStyle().
		Width(treeWidth).MaxWidth(treeWidth).Height(height).MaxHeight(height).
		Padding(0, 2, 0, 1).
		Render(tree)
	right := lipgloss.NewStyle().
		Width(previewWidth).MaxWidth(previewWidth).Height(height).MaxHeight(height).
		Padding(0, 1).
		Render(previewHeader + lipgloss.NewStyle().Foreground(colText).MaxWidth(previewWidth).Render(preview))
	return lipgloss.JoinHorizontal(lipgloss.Top, left, right)
}

// renderScratchpad はDirector自身のスクラッチパッド＋更新履歴＋
// delegate_to_team/delegate_to_worker で起動したサブエージェント（Worker）の
// スクラッチパッドを表示する（Python版 app.py::_refresh_scratchpad_tab の移植）。
func (m Model) renderScratchpad(width int) string {
	var b strings.Builder
	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(colAccent)
	subTitleStyle := lipgloss.NewStyle().Bold(true).Foreground(colTitle)
	dimStyle := lipgloss.NewStyle().Foreground(colMuted)
	bodyStyle := lipgloss.NewStyle().Foreground(colText).MaxWidth(width)

	b.WriteString(titleStyle.Render("■ このエージェント（Director）") + "\n")
	content := tools.GetScratchpad()
	if content != "" {
		b.WriteString(bodyStyle.Render(content) + "\n")
	} else {
		b.WriteString(dimStyle.Render("スクラッチパッドはまだ空です。") + "\n")
	}

	history := tools.GetScratchpadHistory()
	if len(history) > 1 {
		b.WriteString("\n" + dimStyle.Render(fmt.Sprintf("── 更新履歴（%d件、新しい順） ──", len(history))) + "\n")
		for i := len(history) - 2; i >= 0; i-- { // 最新(末尾)は上で表示済みなので除く
			e := history[i]
			b.WriteString(dimStyle.Render(e.TS) + "\n")
			b.WriteString(lipgloss.NewStyle().Foreground(colMuted).MaxWidth(width).Render(e.Content) + "\n")
		}
	}

	traceIDs := delegate.GetRecentWorkerTraceIDs()
	if len(traceIDs) > 0 {
		sessionsDir := filepath.Join(m.cwd, ".mimic", "sessions")
		for _, tid := range traceIDs {
			b.WriteString("\n")
			fileName, subHistory, found := viewer.GetSessionScratchpadHistory(sessionsDir, tid)
			title := fmt.Sprintf("■ サブエージェント（Worker, trace_id=%s）", tid)
			if fileName != "" {
				title += "  " + fileName
			}
			b.WriteString(subTitleStyle.Render(title) + "\n")
			if !found {
				b.WriteString(dimStyle.Render("(セッションログがまだありません)") + "\n")
				continue
			}
			if len(subHistory) > 0 {
				b.WriteString(bodyStyle.Render(subHistory[len(subHistory)-1].Content) + "\n")
			} else {
				b.WriteString(dimStyle.Render("スクラッチパッドはまだ空です。") + "\n")
			}
		}
	}

	return strings.TrimRight(b.String(), "\n")
}

func (m Model) renderLogTab(width int) string {
	entries := m.reactLog.RecentEntries(100) // Python版 app.py::_refresh_log_tab と同じ直近100件
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

	// Python版 CSS: #input-bar { border: round #30363d; } / :focus-within { border: round #00ff41; }
	borderColor := colBorder2
	if m.active == tabChat {
		borderColor = colBorderHi
	}
	// 背景色は明示的に塗らず、端末側の背景（透過設定含む）をそのまま透けさせる。
	box := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(borderColor).
		Padding(0, 1).
		Width(innerWidth).MaxWidth(m.width)

	inputView := m.input.View()
	boxRendered := box.Render(inputView)

	hint := "Enter 送信 · Ctrl+N 改行 · F1-F4 タブ切替 · Ctrl+C 終了"
	if m.pendingApproval != nil || m.pendingApplyApproval != nil || m.pendingHostExecApproval != nil {
		hint = fmt.Sprintf("Y/n を入力 · Enter で確定 · %d秒で自動承認", approvalTimeoutSec)
	} else if m.pendingSearchSelection != nil {
		hint = "番号をカンマ区切り / all / n を入力 · Enter で確定"
	} else if m.pendingSessionInject != nil {
		hint = "y/n を入力 · Enter で確定"
	} else if m.streaming {
		hint = "⏳ 実行中... (Ctrl+C で中断)"
	} else if m.active == tabFiles {
		hint = "↑/↓ 選択 · ←/→ 展開/折りたたみ · Enter 開く · / 検索 · PgUp/PgDn プレビュー捲り · Backspace 上へ"
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
