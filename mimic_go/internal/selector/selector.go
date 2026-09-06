// Package selector は起動時のマルチプロバイダ・モデルセレクター
// （Python版 config.py::select_model_interactively_multi の移植）を実装する。
// OpenRouter/Gemini/Mistralの利用可能モデルを並列取得し、各モデルへ最小リクエスト
// を送って疎通確認（レイテンシ計測）、結果をテーブル表示して番号で選ばせる。
// Enterキーで疎通確認を打ち切り、その時点までの結果で選択に進める。
package selector

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/sys/unix"

	"mimic/internal/config"
)

// ANSIカラー（Python版と同じRazer Neon Greenテーマを踏襲）。
const (
	colRG  = "\033[38;2;0;255;65m"
	colRGD = "\033[38;2;0;160;45m"
	colWHT = "\033[38;2;255;255;255m"
	colGRY = "\033[38;2;0;200;100m"
	colCYN = "\033[38;2;0;240;200m"
	colYLW = "\033[38;2;255;230;0m"
	colMEM = "\033[38;2;0;200;220m"
	colBLD = "\033[1m"
	colRST = "\033[0m"
)

func g(s string) string  { return colRG + s + colRST }
func gd(s string) string { return colRGD + s + colRST }
func w(s string) string  { return colWHT + s + colRST }
func cy(s string) string { return colCYN + s + colRST }
func y(s string) string  { return colYLW + s + colRST }
func mm(s string) string { return colMEM + s + colRST }
func gr(s string) string { return colGRY + s + colRST }
func bg(s string) string { return colBLD + colRG + s + colRST }
func bw(s string) string { return colBLD + colWHT + s + colRST }

type modelInfo struct {
	ID            string
	ContextLength int
}

var geminiContextLengths = map[string]int{
	"gemini-2.5-pro": 1048576, "gemini-2.5-flash": 1048576,
	"gemini-2.0-flash": 1048576, "gemini-2.0-flash-lite": 1048576,
	"gemini-1.5-pro": 2097152, "gemini-1.5-flash": 1048576, "gemini-1.5-flash-8b": 1048576,
}

func geminiContextLength(modelID string) int {
	for key, val := range geminiContextLengths {
		if strings.Contains(modelID, key) {
			return val
		}
	}
	return 1048576
}

// suppressEcho は端末のローカルエコーを無効化し、元へ戻すためのrestore関数を返す。
// 標準入力がttyでない、またはtermios取得/設定に失敗した場合は何もしない
// no-opのrestoreを返す（無いよりはまし、という位置づけで疎通確認自体は継続する）。
// restoreは複数回呼んでも安全（2回目以降は何もしない）。
func suppressEcho() (restore func()) {
	fd := int(os.Stdin.Fd())
	orig, err := unix.IoctlGetTermios(fd, unix.TCGETS)
	if err != nil {
		return func() {}
	}
	noEcho := *orig
	noEcho.Lflag &^= unix.ECHO
	if err := unix.IoctlSetTermios(fd, unix.TCSETS, &noEcho); err != nil {
		return func() {}
	}
	restored := false
	return func() {
		if restored {
			return
		}
		restored = true
		_ = unix.IoctlSetTermios(fd, unix.TCSETS, orig)
	}
}

var httpClient = &http.Client{}

func fetchFreeModels(apiKey string) []modelInfo {
	var result struct {
		Data []struct {
			ID      string `json:"id"`
			Name    string `json:"name"`
			Pricing struct {
				Prompt     string `json:"prompt"`
				Completion string `json:"completion"`
			} `json:"pricing"`
		} `json:"data"`
	}
	if !fetchJSON(config.OpenRouterAPIBase()+"/models", apiKey, &result) {
		return nil
	}
	var out []modelInfo
	for _, m := range result.Data {
		if (m.Pricing.Prompt == "0" && m.Pricing.Completion == "0") || strings.HasSuffix(m.ID, ":free") {
			out = append(out, modelInfo{ID: m.ID})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func fetchGeminiModels(apiKey string) []modelInfo {
	var result struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if !fetchJSON(config.GeminiAPIBase()+"/models", apiKey, &result) {
		return nil
	}
	var out []modelInfo
	for _, m := range result.Data {
		ml := strings.ToLower(m.ID)
		if !strings.Contains(ml, "gemini") && !strings.Contains(ml, "gemma") {
			continue
		}
		out = append(out, modelInfo{ID: m.ID, ContextLength: geminiContextLength(m.ID)})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func fetchMistralModels(apiKey string) []modelInfo {
	var result struct {
		Data []struct {
			ID               string `json:"id"`
			MaxContextLength int    `json:"max_context_length"`
		} `json:"data"`
	}
	if !fetchJSON(config.MistralAPIBase()+"/models", apiKey, &result) {
		return nil
	}
	var out []modelInfo
	for _, m := range result.Data {
		out = append(out, modelInfo{ID: m.ID, ContextLength: m.MaxContextLength})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func fetchJSON(url, apiKey string, out any) bool {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return false
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("Content-Type", "application/json")
	c := &http.Client{Timeout: 10 * time.Second}
	resp, err := c.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return json.NewDecoder(resp.Body).Decode(out) == nil
}

// testModel はモデルに最小リクエストを送り (成功したか, 応答時間) を返す
// （Python版 _test_model の移植）。
func testModel(apiKey, modelID, baseURL string) (bool, float64) {
	payload := map[string]any{
		"model":      modelID,
		"messages":   []map[string]string{{"role": "user", "content": "hi"}},
		"max_tokens": 1,
	}
	body, _ := json.Marshal(payload)
	req, err := http.NewRequest(http.MethodPost, baseURL+"/chat/completions", strings.NewReader(string(body)))
	if err != nil {
		return false, 0
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+apiKey)

	c := &http.Client{Timeout: 20 * time.Second}
	t0 := time.Now()
	resp, err := c.Do(req)
	if err != nil {
		return false, 0
	}
	defer resp.Body.Close()
	var data map[string]any
	if json.NewDecoder(resp.Body).Decode(&data) != nil {
		return false, 0
	}
	if _, hasErr := data["error"]; hasErr {
		return false, 0
	}
	return true, time.Since(t0).Seconds()
}

type entry struct {
	provider string // "or" / "gemini" / "mistral"
	model    modelInfo
}

type testResult struct {
	ok      bool
	elapsed float64
}

// SelectInteractively はOpenRouter/Gemini/Mistralのモデルを並列取得・疎通テストし、
// 番号選択で使用モデルとプロバイダーを確定する。選択されたProviderConfig
// （Model更新済み）を返す。取得失敗・キャンセル時は元の cfg.Active を返す。
func SelectInteractively(cfg *config.Config) *config.ProviderConfig {
	orCfg := cfg.Providers["openrouter"]
	geminiCfg := cfg.Providers["gemini"]
	mistralCfg := cfg.Providers["mistral"]
	fallback := cfg.Active

	const boxWidth = 76
	fmt.Println()
	fmt.Println(gd("  ╔" + strings.Repeat("═", boxWidth) + "╗"))
	title := "  MULTI-PROVIDER MODEL SELECTOR  ·  LIVE API HEALTH CHECK  "
	pad := boxWidth - len([]rune(title))
	if pad < 0 {
		pad = 0
	}
	fmt.Println(gd("  ║") + colBLD + colRG + title + colRST + strings.Repeat(" ", pad) + gd("║"))
	fmt.Println(gd("  ╚" + strings.Repeat("═", boxWidth) + "╝"))
	fmt.Println()

	// ── フェーズ1: モデル一覧を並列取得 ──
	fmt.Printf("  %s  モデル一覧を取得中...", gr("⟳"))
	var orModels, geminiModels, mistralModels []modelInfo
	var wg sync.WaitGroup
	if orCfg != nil {
		wg.Add(1)
		go func() { defer wg.Done(); orModels = fetchFreeModels(orCfg.APIKeys[0]) }()
	}
	if geminiCfg != nil {
		wg.Add(1)
		go func() { defer wg.Done(); geminiModels = fetchGeminiModels(geminiCfg.APIKeys[0]) }()
	}
	if mistralCfg != nil {
		wg.Add(1)
		go func() { defer wg.Done(); mistralModels = fetchMistralModels(mistralCfg.APIKeys[0]) }()
	}
	wg.Wait()

	var parts []string
	if orCfg != nil {
		parts = append(parts, fmt.Sprintf("%s: %s 件の無料モデル", g("OpenRouter"), w(strconv.Itoa(len(orModels)))))
	}
	if geminiCfg != nil {
		parts = append(parts, fmt.Sprintf("%s: %s 件のモデル", g("Gemini"), w(strconv.Itoa(len(geminiModels)))))
	}
	if mistralCfg != nil {
		parts = append(parts, fmt.Sprintf("%s: %s 件のモデル", cy("Mistral"), w(strconv.Itoa(len(mistralModels)))))
	}
	fmt.Printf("\r  %s  %s%s\n\n", g("✓"), strings.Join(parts, "  /  "), strings.Repeat(" ", 20))

	var allEntries []entry
	for _, m := range orModels {
		allEntries = append(allEntries, entry{"or", m})
	}
	for _, m := range geminiModels {
		allEntries = append(allEntries, entry{"gemini", m})
	}
	for _, m := range mistralModels {
		allEntries = append(allEntries, entry{"mistral", m})
	}
	total := len(allEntries)
	if total == 0 {
		fmt.Printf("  %s  モデル一覧の取得に失敗しました。現在の設定を使用します。\n\n", y("⚠"))
		return fallback
	}

	// ── フェーズ2: 疎通確認（並列、Enterキーで途中終了可）──
	fmt.Printf("  %s  %s\n\n", gr("疎通確認中..."), y("← エンターキーで現時点の結果を表示"))

	// このフェーズだけ端末のローカルエコーを無効化する。無効化しないと、Enter
	// キー押下がターミナル側でそのままエコーされ改行としてカーソルを進めてしまい、
	// "\r"で同じ行を上書き更新しているはずのプログレスバーが複数行に分裂して
	// 表示される（実機のtmux上で実際に確認した見た目の不具合）。フェーズ3の
	// 番号選択プロンプトでは通常通りタイプ内容が見えてほしいので、疎通確認の
	// ループを抜けたら早めにrestoreEchoで元へ戻す。
	restoreEcho := suppressEcho()
	defer restoreEcho()

	// 標準入力の読み取りはこのゴルーチン1つに一本化する。ここで「Enterキー検知」と
	// 後段の「番号選択」の両方を、別々のbufio.Readerで同時にstdinから読もうとすると、
	// ユーザーの入力がどちらか一方にしか届かず、番号選択の入力が横取りされて反応が
	// おかしくなる（実際に発生した不具合）。1本のゴルーチンが読んだ行をchannel経由で
	// 配ることで、常にどちらか片方だけが読んでいる状態を保証する。
	//
	// 単純にブロッキングのbufio.Reader.ReadStringで読むと、この関数を抜けたあとも
	// ゴルーチンが次の read() システムコールに入ったまま停止できず、そのまま
	// Bubble Tea（対話TUI本体）が読むはずのキー入力を横取りし続けてしまう
	// （Goのブロッキング read() は一度呼ぶとチャネルで外部から中断できないため）。
	// 当初SetReadDeadlineで期限を刻む方式を試したが、tmux配下のptyでは
	// デッドラインが効かず無期限にブロックしたままになる事例を実機で確認したため、
	// unix.Pollと自己パイプ（stopPipeへの書き込みでpoll待ちを即座に起こす）による
	// 確実な中断方式に変更した。これなら「次の入力が来るまで無反応」という
	// 事態にならず、関数を抜けるタイミングで確実にゴルーチンを終了させられる。
	lineCh := make(chan string)
	stopReader := make(chan struct{}) // ローカルのchannel送信を打ち切るための合図
	stopPipeR, stopPipeW, pipeErr := os.Pipe()
	if pipeErr != nil {
		// pipe作成自体に失敗する状況は現実的にはほぼ無いが、失敗時は
		// このバッチの新機能（早期終了）を諦めてフォールバックの単純な
		// ブロッキング読み取りにする（無いよりはまし、という位置づけ）。
		stopPipeR, stopPipeW = nil, nil
	}
	readerStopped := make(chan struct{}) // ゴルーチンが実際に停止したことの確認用
	go func() {
		defer close(readerStopped)
		var buf []byte
		tmp := make([]byte, 256)
		stdinFd := int32(os.Stdin.Fd())
		for {
			if stopPipeR != nil {
				fds := []unix.PollFd{
					{Fd: stdinFd, Events: unix.POLLIN},
					{Fd: int32(stopPipeR.Fd()), Events: unix.POLLIN},
				}
				_, perr := unix.Poll(fds, -1)
				if perr != nil {
					if perr == unix.EINTR {
						continue
					}
					close(lineCh)
					return
				}
				if fds[1].Revents&unix.POLLIN != 0 {
					return // 停止シグナル（stopPipeWへの書き込み）を受信
				}
				if fds[0].Revents&unix.POLLIN == 0 {
					continue
				}
			}
			n, err := os.Stdin.Read(tmp)
			if n > 0 {
				buf = append(buf, tmp[:n]...)
				for {
					idx := bytes.IndexByte(buf, '\n')
					if idx < 0 {
						break
					}
					line := string(buf[:idx+1])
					buf = buf[idx+1:]
					select {
					case lineCh <- line:
					case <-stopReader:
						return
					}
				}
			}
			if err != nil {
				close(lineCh)
				return
			}
		}
	}()
	// この関数を抜ける直前に必ずゴルーチンを止め、停止を確認してから標準入力を
	// Bubble Tea側へ明け渡す（確認を待たずに抜けると、まだ読み取り中の可能性がある
	// 期間とBubble Tea起動が重なり、最初のキー入力を横取りされる恐れがあるため）。
	// stopPipeWへの書き込みでpoll()待ちを即座に起こし、read()呼び出し自体を
	// 一度も発生させずに確実にゴルーチンを終了させる。
	defer func() {
		close(stopReader)
		if stopPipeW != nil {
			stopPipeW.Write([]byte{0})
		}
		<-readerStopped
		if stopPipeR != nil {
			stopPipeR.Close()
			stopPipeW.Close()
		}
	}()

	results := make(map[string]testResult)
	var resultsMu sync.Mutex
	const barWidth = 34
	stopTesting := make(chan struct{})
	var stopOnce sync.Once
	stop := func() { stopOnce.Do(func() { close(stopTesting) }) }
	stoppedEarly := false

	testedN := 0
	sem := make(chan struct{}, 10) // Python版 max_workers=10 を踏襲
	var testWg sync.WaitGroup

loop:
	for _, e := range allEntries {
		select {
		case <-lineCh:
			stop()
			stoppedEarly = true
			break loop
		default:
		}
		select {
		case <-lineCh:
			stop()
			stoppedEarly = true
			break loop
		case <-stopTesting:
			break loop
		case sem <- struct{}{}:
		}
		testWg.Add(1)
		go func(e entry) {
			defer testWg.Done()
			defer func() { <-sem }()
			select {
			case <-stopTesting:
				return
			default:
			}
			var ok bool
			var elapsed float64
			switch e.provider {
			case "or":
				ok, elapsed = testModel(orCfg.APIKeys[0], e.model.ID, config.OpenRouterAPIBase())
			case "gemini":
				ok, elapsed = testModel(geminiCfg.APIKeys[0], e.model.ID, config.GeminiAPIBase())
			case "mistral":
				ok, elapsed = testModel(mistralCfg.APIKeys[0], e.model.ID, config.MistralAPIBase())
			}
			select {
			case <-stopTesting:
				return
			default:
			}
			key := e.provider + ":" + e.model.ID
			resultsMu.Lock()
			results[key] = testResult{ok, elapsed}
			testedN++
			n := testedN
			resultsMu.Unlock()

			filled := barWidth * n / total
			if filled > barWidth {
				filled = barWidth
			}
			bar := colRG + strings.Repeat("█", filled) + colGRY + strings.Repeat("░", barWidth-filled) + colRST
			tw := len(strconv.Itoa(total))
			fmt.Printf("\r  [%s]  %s/%d  %s%%",
				bar, w(fmt.Sprintf("%*d", tw, n)), total, gr(fmt.Sprintf("%3d", 100*n/total)))
		}(e)
	}
	if !stoppedEarly {
		// 通常完了時は全ゴルーチンの終了を待つ。早期終了時はPython版の
		// cancel_futures=True相当（実行中のテストの完了を待たず、その時点の
		// 結果だけで先に進む）とし、待たない — 10並列×最大20秒待たされる
		// ことがあり、Enterを押しても即座に反応しないように見えるバグの原因だった。
		testWg.Wait()
	}
	fmt.Printf("\r%s\r", strings.Repeat(" ", 80))
	restoreEcho() // フェーズ3の番号選択プロンプトでは通常通りタイプ内容を見せる

	type workingEntry struct {
		provider string
		model    modelInfo
		elapsed  float64
	}
	resultsMu.Lock()
	resultsSnapshot := make(map[string]testResult, len(results))
	for k, v := range results {
		resultsSnapshot[k] = v
	}
	resultsMu.Unlock()

	var working []workingEntry
	for _, e := range allEntries {
		key := e.provider + ":" + e.model.ID
		if r, ok := resultsSnapshot[key]; ok && r.ok {
			working = append(working, workingEntry{e.provider, e.model, r.elapsed})
		}
	}
	sort.Slice(working, func(i, j int) bool { return working[i].elapsed < working[j].elapsed })

	if len(working) == 0 {
		fmt.Printf("  %s  疎通できたモデルがありませんでした。現在の設定を使用します。\n\n", y("⚠"))
		return fallback
	}

	// ── フェーズ3: 結果テーブル ──
	const cN, cProv, cID, cLat, cCtx = 4, 4, 42, 7, 9

	ctxFmt := func(ctx int) string {
		switch {
		case ctx == 0:
			return "─"
		case ctx >= 1_000_000:
			return fmt.Sprintf("%dM", ctx/1_000_000)
		case ctx >= 1_000:
			return fmt.Sprintf("%dK", ctx/1_000)
		default:
			return strconv.Itoa(ctx)
		}
	}
	latCol := func(elapsed float64, rank int) string {
		s := center(fmt.Sprintf("%.1fs", elapsed), cLat)
		switch {
		case rank == 0:
			return colBLD + colRG + s + colRST
		case elapsed < 3.0:
			return colCYN + s + colRST
		case elapsed < 8.0:
			return colYLW + s + colRST
		default:
			return colGRY + s + colRST
		}
	}
	provBadge := func(provider string) string {
		switch provider {
		case "or":
			return colRG + center("OR", cProv) + colRST
		case "mistral":
			return colCYN + center("MI", cProv) + colRST
		default:
			return "\033[38;2;0;255;65m" + center("GM", cProv) + colRST
		}
	}
	eq := "═"
	hline := func(lc, rc, jc string) string {
		return gd(lc + strings.Repeat(eq, cN+2) + jc + strings.Repeat(eq, cProv+2) + jc +
			strings.Repeat(eq, cID+2) + jc + strings.Repeat(eq, cLat+2) + jc + strings.Repeat(eq, cCtx+2) + rc)
	}
	V := gd("║")

	orCur, geminiCur, mistralCur := "", "", ""
	if orCfg != nil {
		orCur = orCfg.Model
	}
	if geminiCfg != nil {
		geminiCur = geminiCfg.Model
	}
	if mistralCfg != nil {
		mistralCur = mistralCfg.Model
	}

	fmt.Printf("  %s 件が稼働中  %s  %s\n\n", bw(strconv.Itoa(len(working))), gr("/"), gr(fmt.Sprintf("%d 件取得", total)))
	fmt.Println(hline("╔", "╗", "╦"))
	fmt.Printf("%s %s %s %s %s %s %s %s %s %s\n", V, bw(center("No.", cN)), V, bw(center("Pv", cProv)), V,
		bw(padRight("Model ID", cID)), V, bw(center("Latency", cLat)), V, bw(center("Context", cCtx))+" "+V)
	fmt.Println(hline("╠", "╣", "╬"))

	for i, wk := range working {
		mid := wk.model.ID
		isCur := (wk.provider == "or" && mid == orCur) || (wk.provider == "gemini" && mid == geminiCur) || (wk.provider == "mistral" && mid == mistralCur)
		isTop := i == 0

		noP := center(strconv.Itoa(i+1), cN)
		idP := padRight(truncate(mid, cID), cID)
		latD := latCol(wk.elapsed, i)
		ctxD := mm(padLeft(ctxFmt(wk.model.ContextLength), cCtx))
		pvD := provBadge(wk.provider)

		var noD, idD, tag string
		switch {
		case isTop && isCur:
			noD, idD, tag = bg(noP), bg(idP), "  "+bg("★ FASTEST · CURRENT")
		case isTop:
			noD, idD, tag = bg(noP), bg(idP), "  "+bg("★ FASTEST")
		case isCur:
			colorFn := cy
			if wk.provider == "gemini" {
				colorFn = func(s string) string { return "\033[38;2;0;255;65m" + s + colRST }
			}
			noD, idD, tag = colorFn(noP), colorFn(idP), "  "+colorFn("← CURRENT")
		default:
			noD, idD, tag = gr(noP), w(idP), ""
		}
		fmt.Printf("%s %s %s %s %s %s %s %s %s %s%s\n", V, noD, V, pvD, V, idD, V, latD, V, ctxD, " "+V+tag)
	}
	fmt.Println(hline("╚", "╝", "╩"))

	activeProviders := 0
	for _, c := range []*config.ProviderConfig{orCfg, geminiCfg, mistralCfg} {
		if c != nil {
			activeProviders++
		}
	}
	if activeProviders > 1 {
		var legend []string
		if orCfg != nil {
			legend = append(legend, g("OR")+" = OpenRouter")
		}
		if geminiCfg != nil {
			legend = append(legend, "\033[38;2;0;255;65m"+"GM"+colRST+" = Google AI Studio")
		}
		if mistralCfg != nil {
			legend = append(legend, cy("MI")+" = Mistral AI")
		}
		fmt.Printf("\n  凡例: %s\n\n", strings.Join(legend, "  "))
	}

	var cancelParts []string
	if orCfg != nil {
		cancelParts = append(cancelParts, g("OR")+" "+y(orCfg.Model))
	}
	if geminiCfg != nil {
		cancelParts = append(cancelParts, "GM "+y(geminiCfg.Model))
	}
	if mistralCfg != nil {
		cancelParts = append(cancelParts, cy("MI")+" "+y(mistralCfg.Model))
	}
	fmt.Printf("  %s  %s  %s  %s  %s\n\n", gd("[ 0 ]"), gr("キャンセル"), gr("·"), gr("現在:"), strings.Join(cancelParts, "  /  "))

	for {
		fmt.Printf("  %s  番号を入力  %s  ", g("▸"), gd("›"))
		raw, ok := <-lineCh
		if !ok {
			fmt.Println()
			return fallback
		}
		raw = strings.TrimSpace(raw)
		if raw == "" || raw == "0" {
			return fallback
		}
		n, err := strconv.Atoi(raw)
		if err != nil {
			fmt.Printf("  %s  数字を入力してください（0〜%d）。\n", y("⚠"), len(working))
			continue
		}
		if n >= 1 && n <= len(working) {
			sel := working[n-1]
			switch sel.provider {
			case "or":
				orCfg.Model = sel.model.ID
				orCfg.ContextLength = sel.model.ContextLength
				fmt.Printf("\n  %s  %s  %s %s\n\n", bg("✓"), w("選択:"), g("[OR]"), g(sel.model.ID))
				return orCfg
			case "gemini":
				geminiCfg.Model = sel.model.ID
				geminiCfg.ContextLength = sel.model.ContextLength
				fmt.Printf("\n  %s  %s  GM %s\n\n", bg("✓"), w("選択:"), sel.model.ID)
				return geminiCfg
			case "mistral":
				mistralCfg.Model = sel.model.ID
				mistralCfg.ContextLength = sel.model.ContextLength
				fmt.Printf("\n  %s  %s  %s %s\n\n", cy("✓"), w("選択:"), cy("[MI]"), cy(sel.model.ID))
				return mistralCfg
			}
		}
		fmt.Printf("  %s  1〜%d の番号を入力してください。\n", y("⚠"), len(working))
	}
}

func center(s string, width int) string {
	r := []rune(s)
	if len(r) >= width {
		return string(r[:width])
	}
	total := width - len(r)
	left := total / 2
	right := total - left
	return strings.Repeat(" ", left) + s + strings.Repeat(" ", right)
}

func padRight(s string, width int) string {
	r := []rune(s)
	if len(r) >= width {
		return string(r[:width])
	}
	return s + strings.Repeat(" ", width-len(r))
}

func padLeft(s string, width int) string {
	r := []rune(s)
	if len(r) >= width {
		return string(r[:width])
	}
	return strings.Repeat(" ", width-len(r)) + s
}

func truncate(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max])
}
