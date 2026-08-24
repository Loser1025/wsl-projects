// Package tui は mimic の対話UIを実装する。
//
// フェーズ1: チャット入力 + スクロール可能なログ表示 + ReActループ
// (LLMストリーミング + 読み取り専用ツール呼び出し)。
// 未対応（後続フェーズ）: 書き込み系ツール・承認モーダル、委任、サンドボックス。
package tui

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"mimic/internal/delegate"
	"mimic/internal/llm"
	"mimic/internal/react"
	"mimic/internal/tools"
	"mimic/internal/vcs"
)

type Model struct {
	viewport viewport.Model
	input    textarea.Model
	log      []string
	width    int
	height   int
	ready    bool

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
	openLine   bool // 現在ストリーミング中のテキスト行が未確定かどうか
}

// turnEvent はReActループを回すゴルーチンからUpdateループへ渡すイベント。
//
// history はターン完了時(done=true)にのみ乗せる。bubbletea はUpdateのたびに
// Model を値コピーして保持するため、ゴルーチンにポインタで直接history片を
// 書き込ませてもUpdateが持つ「本物の」Modelには反映されない
// （goroutine側は値渡しされた時点の m のコピーの記憶域を指してしまう）。
// そのためgoroutineには独立したコピーを渡して回させ、完了時にまとめて
// 正しいModelへ書き戻す方式にしている。
type turnEvent struct {
	text     string              // テキストチャンク
	tool     *react.ToolActivity // ツール呼び出し通知
	done     bool
	history  []llm.Message // done=true のときのみ設定（更新後の会話履歴全体）
	finalErr error
}

// checkpointPath はターン実行中の会話履歴を永続化する先。異常終了時に
// 次回起動で自動再開できるようにする（Python版 .mimic_checkpoint.json 相当）。
const checkpointPath = ".mimic/checkpoint.json"

func NewModel(client *llm.Client, systemPrompt string) Model {
	ta := textarea.New()
	ta.Placeholder = "メッセージを入力... (Enterで送信、Ctrl+Cで終了)"
	ta.Focus()
	ta.CharLimit = 0
	ta.ShowLineNumbers = false
	ta.SetHeight(3)

	log := []string{"[mimic-go] フェーズ2: ファイル/シェル/Web/Skills系ツール + AutoGit対応済み。"}
	history, err := react.LoadCheckpoint(checkpointPath)
	if err != nil {
		log = append(log, fmt.Sprintf("[警告] チェックポイントの読み込みに失敗しました: %v", err))
	} else if len(history) > 0 {
		log = append(log, fmt.Sprintf("[mimic-go] 前回中断したセッションを再開しました(履歴%d件)。", len(history)))
	}

	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}

	reactLog := vcs.NewReactLog()
	sessionsDir := filepath.Join(cwd, ".mimic", "sessions")
	jsonlPath := filepath.Join(sessionsDir, time.Now().Format("2006-01-02_15-04")+".jsonl")
	if err := reactLog.SetJSONLPath(jsonlPath); err == nil {
		vcs.PruneOldSessions(sessionsDir, 200)
	}
	reactLog.Add("session_start", map[string]any{"model": client.Model(), "provider": client.ProviderName()})

	registry := tools.NewDefaultRegistry()
	delegate.RegisterTools(registry, client)

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

func (m Model) Init() tea.Cmd {
	return textarea.Blink
}

const inputAreaHeight = 5 // 入力欄3行 + 枠線2行

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
// viewport自体は折り返しをせず、幅を超えた行を単純に切り詰めて表示するため、
// 2通目以降で応答が長くなるとテキストが文の途中で切れて見える不具合があった。
// lipgloss.Width()のwordwrapは各論理行を独立に折り返すため、m.log内の
// 各エントリ（1メッセージ=1エントリとは限らず、ストリーミング中は複数行を
// 含みうる）を個別に折り返してから結合する。
func (m Model) renderLog() string {
	w := m.viewport.Width
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

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var (
		taCmd tea.Cmd
		vpCmd tea.Cmd
	)

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		if !m.ready {
			m.viewport = viewport.New(msg.Width, msg.Height-inputAreaHeight)
			m.viewport.SetContent(m.renderLog())
			m.ready = true
		} else {
			m.viewport.Width = msg.Width
			m.viewport.Height = msg.Height - inputAreaHeight
		}
		m.input.SetWidth(msg.Width - 2)

	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c":
			if m.cancelFunc != nil {
				m.cancelFunc()
			}
			return m, tea.Quit
		case "enter":
			if m.streaming {
				return m, nil // ターン実行中は多重送信しない
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

	m.input, taCmd = m.input.Update(msg)
	m.viewport, vpCmd = m.viewport.Update(msg)
	return m, tea.Batch(taCmd, vpCmd)
}

// startTurn はReActループ(internal/react.RunTurn)をバックグラウンドゴルーチンで
// 開始し、チャンネル監視Cmdを返す。UIスレッド(Update)は一切ブロックしない。
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
	// ゴルーチンには独立したコピーを渡す（上のturnEventコメント参照）。
	// ターン実行中は入力を受け付けないため、コピー元との競合はない。
	histCopy := append([]llm.Message(nil), m.history...)

	go func() {
		defer close(ch)
		_, err := react.RunTurn(ctx, client, systemPrompt, registry, &histCopy,
			func(text string) { ch <- turnEvent{text: text} },
			func(activity react.ToolActivity) { ch <- turnEvent{tool: &activity} },
			checkpointPath, autoGit, cwd, reactLog, callLog,
		)
		if err != nil && ctx.Err() == nil {
			ch <- turnEvent{finalErr: err}
			return
		}
		ch <- turnEvent{done: true, history: histCopy}
	}()

	return m, waitForTurnEvent(ch)
}

var borderStyle = lipgloss.NewStyle().
	Border(lipgloss.RoundedBorder()).
	BorderForeground(lipgloss.Color("240"))

func (m Model) View() string {
	if !m.ready {
		return "初期化中..."
	}
	status := ""
	if m.streaming {
		status = " [応答中...]"
	}
	return fmt.Sprintf("%s\n%s%s", m.viewport.View(), borderStyle.Render(m.input.View()), status)
}
