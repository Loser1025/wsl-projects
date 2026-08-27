// Package react はThought→Action→ObservationのReActループ本体を実装する
// （Python版 orchestrator.py::InteractiveOrchestrator.run_react の移植）。
package react

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"mimic/internal/llm"
	"mimic/internal/tools"
	"mimic/internal/vcs"
)

// MaxSteps はPython版の MAX_REACT_STEPS = 120 をそのまま踏襲する。
const MaxSteps = 120

// maxParallelToolWorkers は読み取り専用ツールの並列実行時の最大同時実行数
// （Python版 orchestrator.py::ThreadPoolExecutor(max_workers=min(len(tool_calls),4)) を踏襲）。
const maxParallelToolWorkers = 4

// MaxObservationChars はツール出力(observation)1件あたりの文字数上限
// （Python版 orchestrator.py::_OBS_MAX_CHARS = 2000 を踏襲）。
// 上限なしで履歴に積み続けると、巨大なgrep結果等を含む長いターンで
// 履歴全体を毎ステップ再送信するReActの構造上、メモリ・帯域が
// 際限なく膨張する（実運用でOOM Killerに殺される事例を確認済み）。
const MaxObservationChars = 2000

// DelegationObservationChars は委任系ツールの観測上限（Python版
// _DELEGATION_OBS_MAX_CHARS = 6000 を踏襲）。委任結果はDirectorの唯一の
// 情報源になりうるため、通常ツールより大きい切り詰め上限を使う。
const DelegationObservationChars = 6000

// delegationTools は internal/delegate/register.go が登録する委任系ツール名の集合。
var delegationTools = map[string]bool{
	"delegate_to_specialist":    true,
	"delegate_to_team":          true,
	"delegate_to_worker":        true,
	"delegate_to_team_parallel": true,
	"delegate_research":         true,
	"continue_specialist":       true,
}

// MaxRepeatedFailures は同一のツール呼び出し（名前+引数が同一）の失敗が
// この回数に達すると、以降は実行せず拒否メッセージのみ返すようになる
// （Python版 _MAX_IDENTICAL_TOOL_FAILURES = 3 を踏襲）。
const MaxRepeatedFailures = 3

// MaxLoopRefusals はターン内で実行拒否が発生した累計回数の上限。
// これを超えるとターン自体を中断する（Python版 _MAX_LOOP_REFUSALS = 5 を踏襲）。
const MaxLoopRefusals = 5

// MaxEmptyRetries はツール実行後に空テキストが返ってきた場合に報告を促して
// 再試行させる上限回数（Python版 MAX_EMPTY_RETRIES = 2 を踏襲）。
const MaxEmptyRetries = 2

// MaxXMLToolRetries はXML形式のツール呼び出しがテキストに含まれるがパースに
// 失敗した場合、tool_calls形式での再送を促す上限回数
// （Python版 _MAX_XML_TOOL_RETRIES = 3 を踏襲）。
const MaxXMLToolRetries = 3

// ToolActivity はツール呼び出し発生時にUI側へ通知するためのイベント。
type ToolActivity struct {
	Name        string
	ArgsPreview string
}

// RunTurn は1ユーザーターン分のReActループを実行する。
// history は呼び出し前に最新のuserメッセージまで積まれている前提で、
// ループ中に発生したassistant/toolメッセージも同じスライスに追記される。
// onText はテキストチャンク受信の都度呼ばれる（ライブ表示用）。
// onTool はツール呼び出しの発生ごとに呼ばれる（実行前・実行後のUI表示用）。
// checkpointPath が空でなければ、各ステップ完了ごとに履歴をそこへ保存する。
// keepCheckpointがfalse（通常）ならターン正常完了時に削除する（異常終了時は
// 次回起動時の再開用に残る）。keepCheckpointがtrueなら正常完了時も削除せず、
// 会話履歴を保持し続ける（delegate_to_specialist(can_write=True)からの
// continue_specialistによる追加指示継続で使う——次回起動時に同じ履歴へ
// 追記して再開できるようにするため）。
// autoGit が非nilなら、ターン開始時にバックアップコミット、書き込み系ツール
// （write_file/edit_file/patch_file）成功後にチェックポイントコミットを行う
// （Python版 orchestrator.py の AutoGit 連携を踏襲）。
func RunTurn(ctx context.Context, client *llm.Client, systemPrompt string,
	registry *tools.Registry, history *[]llm.Message,
	onText func(string), onTool func(ToolActivity), checkpointPath string,
	autoGit *vcs.AutoGit, cwd string, reactLog *vcs.ReactLog, callLog *vcs.ToolCallLog,
	keepCheckpoint bool) (string, error) {

	specs := registry.Specs()

	// このターンのread_file既読集合をクリアする
	// （Python版 orchestrator.py::clear_read_files_registry() 呼び出しの移植）。
	tools.ClearReadThisTurnRegistry()

	// Skillの存在をモデルが能動的にlist_skillsを呼ばずとも認識できるよう、
	// name+descriptionの要約を毎ターンsystemPromptへ常時掲載する
	// （Python版 skills.py::context_header_section の移植。Progressive
	// Disclosure: 本文はload_skill(name)を呼ぶまで見せない）。
	systemPrompt += tools.SkillContextHeaderSection()
	// ハーネス自動記録: 書き込み済みファイル・直近の委任結果を毎ターン自動併記する
	// （Python版 agent.py::_build_machine_notes の移植。scratchpadの自己更新が
	// 当てにならない弱いモデル対策として、ハーネス側が確実な事実を提示する）。
	systemPrompt += buildMachineNotes()

	// 会話圧縮: しきい値超過時、古い会話を機械ダイジェストに置換する
	// （Python版 agent.py::_compact_if_needed の移植。ターン開始時に1回のみ実行。
	// system_prompt/context_headerのオーバーヘッド分を差し引いた実効しきい値を使う
	// —— Python版 _effective_threshold の移植）。
	compactIfNeeded(history, client.ContextLength(), len(systemPrompt))

	if autoGit != nil {
		autoGit.Backup(cwd)
	}

	// Squashのコミットメッセージ用にこのターンのuser発言を控えておく
	// （historyは呼び出し時点で最新のuserメッセージまで積まれている前提）。
	userMessage := ""
	if n := len(*history); n > 0 && (*history)[n-1].Role == "user" {
		userMessage = (*history)[n-1].Content
	}
	if reactLog != nil {
		reactLog.Add("user_input", map[string]any{"content": userMessage})
	}

	toolNames := make([]string, len(specs))
	for i, s := range specs {
		toolNames[i] = s.Function.Name
	}

	repeatFailCounts := make(map[string]int)
	refusals := 0
	offloadRetryDone := false
	unverifiedRetryDone := false
	turnHadUnverified := false
	hadToolCall := false
	emptyRetryCount := 0
	xmlToolRetryCount := 0
	// readCallIDs はpath→(このターンでread_fileしたtool_call ID一覧)。
	// 同じpathへの書き込みが起きた時点でその観測を無効化する
	// （Python版 _read_call_ids の移植。stale observation invalidation）。
	readCallIDs := make(map[string][]string)

	for step := 0; step < MaxSteps; step++ {
		// 送信直前トリム: compactionをすり抜けるペースでもコンテキスト窓の90%を
		// 超えないよう、その場で中間メッセージを間引く最終防衛ライン
		// （Python版 agent.py::_trim_to_fit の移植）。
		*history = trimToFit(*history, systemPrompt, client.ContextLength())

		result, err := client.StreamChat(ctx, systemPrompt, *history, specs, onText)
		if err != nil {
			return "", err
		}

		// XML形式ツール呼び出し救済: tool_callsが空でもテキストにXML形式の
		// 呼び出しが含まれていればパースして実行する（弱いモデル対策）。
		if len(result.ToolCalls) == 0 && result.Text != "" && hasXMLToolCall(result.Text) {
			if xmlCalls := parseXMLToolCalls(result.Text); len(xmlCalls) > 0 {
				result.ToolCalls = xmlCalls
			}
		}

		if len(result.ToolCalls) == 0 {
			// 空レスポンス検知: 直前にツールを実行したのにテキストが空のまま
			// 返ってきた場合、報告を促して再試行させる（Python版 MAX_EMPTY_RETRIES=2）。
			if result.Text == "" && hadToolCall && emptyRetryCount < MaxEmptyRetries {
				emptyRetryCount++
				*history = append(*history,
					llm.Message{Role: "assistant", Content: "（思考中...）", SkipSave: true},
					llm.Message{Role: "user", Content: "ツール実行結果を踏まえて、作業内容と結果を日本語で報告してください。", SkipSave: true},
				)
				continue
			}

			// XML検知したがパース失敗 → tool_calls形式での再送を促す
			// （Python版 _MAX_XML_TOOL_RETRIES=3）。
			if result.Text != "" && hasXMLToolCall(result.Text) && xmlToolRetryCount < MaxXMLToolRetries {
				xmlToolRetryCount++
				*history = append(*history,
					llm.Message{Role: "assistant", Content: result.Text, SkipSave: true},
					llm.Message{Role: "user", Content: "[システム] ツール呼び出しがXML形式でテキストに含まれていましたが、" +
						"パースできませんでした。\n" +
						"ツールを呼び出す場合は、テキスト内に書かず、APIのtool_calls機能（JSON形式）を使ってください。\n" +
						"直前のツール呼び出し意図をtool_calls形式で再送してください。", SkipSave: true},
				)
				continue
			}

			// 最終回答ゲートA: 実行手段を持つのにユーザーへ丸投げしていないか検査する
			// （1ターンにつき1回だけ差し戻す）。
			if !offloadRetryDone && detectCommandOffload(result.Text, toolNames) {
				offloadRetryDone = true
				*history = append(*history,
					llm.Message{Role: "assistant", Content: result.Text, SkipSave: true},
					llm.Message{Role: "user", Content: "[システム] 回答内でユーザーにコマンド実行や手動修正を依頼していますが、" +
						"実行はあなたの仕事です。あなたが持っている実行ツールを使って自分で実行してから結果を報告してください。\n" +
						"この環境で本当に実行できない場合（認証・対話操作が必要等）のみ、その理由を明記した上でユーザーへの依頼を残してください。", SkipSave: true},
				)
				continue
			}

			// 最終回答ゲートB: このターン内に「※未検証」の委任結果があったのに
			// 「完了/解決」と断言していないか検査する（1ターンにつき1回だけ差し戻す）。
			if !unverifiedRetryDone && detectUnverifiedClaim(result.Text, turnHadUnverified) {
				unverifiedRetryDone = true
				*history = append(*history,
					llm.Message{Role: "assistant", Content: result.Text, SkipSave: true},
					llm.Message{Role: "user", Content: "[システム] このターンには「※未検証」の委任結果が含まれていますが、" +
						"回答は完了/解決したと断言しています。未検証のまま完了と報告せず、" +
						"検証状況を正直に明記するか、可能であれば検証コマンドを実行して確認してから報告してください。", SkipSave: true},
				)
				continue
			}

			// ツール呼び出しなし = 最終回答。履歴に記録して終了。
			*history = append(*history, llm.Message{Role: "assistant", Content: result.Text})
			// ターン確定時点で、このターン中に挿入した一時的な誘導メッセージ
			// （空応答/XML救済リトライ、ゲートA/Bの差し戻し）を永続履歴から
			// 取り除く（Python版 orchestrator.py の _save_msgs フィルタの移植）。
			*history = filterSkipSave(*history)
			if !keepCheckpoint {
				ClearCheckpoint(checkpointPath)
			} else {
				SaveCheckpoint(checkpointPath, *history)
			}
			if autoGit != nil {
				// ターン内の複数checkpointコミットを1つにまとめる（git logを読みやすくする）。
				// チェックポイントが無い（書き込みなし）ターンではSquashは即noop。
				autoGit.Squash(cwd, "🤖 task: "+truncateForCommitMsg(userMessage, 72))
			}
			if reactLog != nil {
				reactLog.Add("final_answer", map[string]any{"content": result.Text})
			}
			return result.Text, nil
		}

		hadToolCall = true

		// assistant メッセージ（tool_calls付き）を履歴に追記
		*history = append(*history, llm.Message{
			Role:      "assistant",
			Content:   result.Text,
			ToolCalls: result.ToolCalls,
		})

		for _, tc := range result.ToolCalls {
			if onTool != nil {
				onTool(ToolActivity{Name: tc.Function.Name, ArgsPreview: preview(tc.Function.Arguments)})
			}
			if reactLog != nil {
				reactLog.Add("action", map[string]any{"tool": tc.Function.Name, "args": rawJSONArgs(tc.Function.Arguments), "step": step})
			}
		}

		// 書き込み系ツールが1件でも含まれる場合、またはいずれかが既に
		// ループブレーカーで拒否対象になっている場合は逐次実行する
		// （書き込みはチェックポイント/介入が必要、拒否判定は逐次側の既存ロジックに任せる）。
		// それ以外（読み取り系のみ・全件実行対象）は並列実行する
		// （Python版 orchestrator.py の ThreadPoolExecutor 分岐の移植）。
		hasWriteCall := false
		hasRefusalCandidate := false
		for _, tc := range result.ToolCalls {
			if vcs.WriteTools[tc.Function.Name] {
				hasWriteCall = true
			}
			if repeatFailCounts[tc.Function.Name+"|"+tc.Function.Arguments] >= MaxRepeatedFailures {
				hasRefusalCandidate = true
			}
		}

		callOutputs := make([]string, len(result.ToolCalls))
		callElapsed := make([]time.Duration, len(result.ToolCalls))
		callCPUMax := make([]float64, len(result.ToolCalls))
		callRSSDelta := make([]float64, len(result.ToolCalls))
		if len(result.ToolCalls) > 1 && !hasWriteCall && !hasRefusalCandidate {
			// 並列バッチはCPU/RSSを呼び出し単位では分離計測できないため
			// （/procは自プロセス全体の値）、バッチ全体で1回だけ計測し、
			// 同じ値を全呼び出しの記録に付与する近似とする。
			mon := vcs.NewProcessMonitor()
			mon.Start()
			var wg sync.WaitGroup
			// Python版 ThreadPoolExecutor(max_workers=min(len(tool_calls),4)) と
			// 同じく、並列度を最大4に制限する（無制限だとバッチが巨大な場合に
			// システムリソースを圧迫しうるため）。
			sem := make(chan struct{}, maxParallelToolWorkers)
			for i, tc := range result.ToolCalls {
				wg.Add(1)
				sem <- struct{}{}
				go func(i int, tc llm.ToolCall) {
					defer wg.Done()
					defer func() { <-sem }()
					start := time.Now()
					callOutputs[i] = tools.CachedCall(registry, tc.Function.Name, tc.Function.Arguments)
					callElapsed[i] = time.Since(start)
				}(i, tc)
			}
			wg.Wait()
			summary := mon.Stop()
			for i := range result.ToolCalls {
				callCPUMax[i] = summary.CPUMaxPct
				callRSSDelta[i] = summary.RSSDeltaMB
			}
		} else {
			for i, tc := range result.ToolCalls {
				mon := vcs.NewProcessMonitor()
				mon.Start()
				start := time.Now()
				callOutputs[i] = tools.CachedCall(registry, tc.Function.Name, tc.Function.Arguments)
				callElapsed[i] = time.Since(start)
				summary := mon.Stop()
				callCPUMax[i] = summary.CPUMaxPct
				callRSSDelta[i] = summary.RSSDeltaMB
			}
		}

		// 各ツールの結果を順序通りに履歴へ反映する（ループブレーカー拒否判定・
		// stale observation無効化・チェックポイント発火は逐次で行う）。
		for i, tc := range result.ToolCalls {
			key := tc.Function.Name + "|" + tc.Function.Arguments

			// ループブレーカー: 同一引数の呼び出しが規定回数失敗済みなら実行せず拒否する
			// （Python版 _execute_with_intervention の同ロジックを移植）。
			if repeatFailCounts[key] >= MaxRepeatedFailures {
				refusals++
				if refusals > MaxLoopRefusals {
					return "", fmt.Errorf("ループブレーカー: 実行拒否が%d回を超えたため中断しました（最後の呼び出し: %s）", MaxLoopRefusals, tc.Function.Name)
				}
				refusalMsg := fmt.Sprintf(
					"[ループ防止] この呼び出し（%s）は同一の引数で%d回失敗しているため、これ以上実行されません。\n"+
						"引数を変える・別のツールを使う・アプローチを変える、のいずれかを行ってください。\n"+
						"打つ手がない場合は、現状と失敗の内容を最終回答として報告してください。",
					tc.Function.Name, MaxRepeatedFailures)
				*history = append(*history, llm.Message{Role: "tool", ToolCallID: tc.ID, Content: refusalMsg})
				if reactLog != nil {
					reactLog.Add("observation", map[string]any{"tool": tc.Function.Name, "result": refusalMsg, "step": step})
				}
				continue
			}

			output := callOutputs[i]
			elapsed := callElapsed[i]
			callStart := time.Now().Add(-elapsed)

			// 書き込み承認が拒否された場合はPython版 UserRejectedWriteError と同様に
			// ターンを即中断する（リトライやループブレーカーへは進ませない）。
			if tools.IsWriteRejected(output) {
				if reactLog != nil {
					reactLog.Add("system_event", map[string]any{"level": "warning", "content": "書き込みが拒否されました: " + output})
				}
				return "書き込みが拒否されたため処理を中断しました。", nil
			}
			isFailForLog := isFailure(output)
			if callLog != nil {
				status := "ok"
				if isFailForLog {
					status = "error"
				}
				callLog.Add(vcs.ToolCallRecord{
					Tool: tc.Function.Name, Elapsed: elapsed, Status: status, Occurred: callStart,
					CPUMaxPct: callCPUMax[i], RSSDeltaMB: callRSSDelta[i],
				})
			}
			if reactLog != nil {
				resultPreview := output
				if len(resultPreview) > 500 {
					resultPreview = resultPreview[:500]
				}
				reactLog.Add("observation", map[string]any{"tool": tc.Function.Name, "result": resultPreview, "step": step})
			}
			if strings.Contains(output, "※未検証") {
				turnHadUnverified = true
			}
			isFail := isFailForLog
			outputForHistory := output
			if isFail {
				repeatFailCounts[key]++
				if repeatFailCounts[key] == MaxRepeatedFailures-1 {
					outputForHistory += fmt.Sprintf(
						"\n⚠ 同一の呼び出しが%d回連続で失敗しています。"+
							"次も同じ引数で呼ぶと実行が拒否されます。引数または手段を変えてください。",
						repeatFailCounts[key])
				}
			}

			obsLimit := MaxObservationChars
			if delegationTools[tc.Function.Name] {
				obsLimit = DelegationObservationChars
			}
			*history = append(*history, llm.Message{
				Role:       "tool",
				ToolCallID: tc.ID,
				Content:    tools.CacheObs(tc.Function.Name, outputForHistory, obsLimit),
			})

			path := extractPathArg(tc.Function.Arguments)
			if vcs.WriteTools[tc.Function.Name] && path != "" && !isFail {
				tools.InvalidateCacheForPath(path)
			}
			if vcs.WriteTools[tc.Function.Name] && path != "" {
				// 書き込み系: 同一パスの古いread_file観測を無効化する。
				for _, staleID := range readCallIDs[path] {
					for i := range *history {
						if (*history)[i].Role == "tool" && (*history)[i].ToolCallID == staleID {
							(*history)[i].Content = "[このread結果は後で上書きされました—省略]"
							break
						}
					}
				}
				delete(readCallIDs, path)
			} else if tc.Function.Name == "read_file" && path != "" {
				readCallIDs[path] = append(readCallIDs[path], tc.ID)
			}

			if !isFail && vcs.WriteTools[tc.Function.Name] && path != "" {
				recordWrite(path)
			}
			if autoGit != nil && !isFail && vcs.WriteTools[tc.Function.Name] {
				autoGit.Checkpoint(cwd, tc.Function.Name, path)
			}
		}

		if err := SaveCheckpoint(checkpointPath, *history); err != nil {
			// チェックポイント保存の失敗はターン自体を止める理由にはしない
			// （ディスク一時障害等で毎ターン失敗し続けるのを避けるため）。
			_ = err
		}

		if ctx.Err() != nil {
			return "", ctx.Err()
		}
	}

	return "", fmt.Errorf("最大ステップ数(%d)に到達しました", MaxSteps)
}

// filterSkipSave はSkipSave==trueのメッセージを取り除いた新しいスライスを返す
// （Python版 orchestrator.py::_save_msgs フィルタの移植）。
func filterSkipSave(history []llm.Message) []llm.Message {
	hasSkip := false
	for _, m := range history {
		if m.SkipSave {
			hasSkip = true
			break
		}
	}
	if !hasSkip {
		return history
	}
	out := make([]llm.Message, 0, len(history))
	for _, m := range history {
		if !m.SkipSave {
			out = append(out, m)
		}
	}
	return out
}

// isFailure はツール実行結果が Registry.Call のエラー整形文字列かどうかを判定する
// （tools.Registry.Call は "エラー: ..." / "ツール実行エラー: ..." 形式で返す方針）。
func isFailure(output string) bool {
	return strings.HasPrefix(output, "エラー:") || strings.HasPrefix(output, "ツール実行エラー:")
}

// truncateForCommitMsg はコミットメッセージ用に改行を空白へ置換し文字数を切り詰める。
func truncateForCommitMsg(s string, max int) string {
	s = strings.ReplaceAll(s, "\n", " ")
	if len(s) > max {
		return s[:max]
	}
	return s
}

// rawJSONArgs はtool_callの引数JSON文字列をReactLog格納用にmapへデコードする。
// パース失敗時は元の文字列をそのまま返す（ReactLogは表示用途のため寛容に扱う）。
func rawJSONArgs(argsJSON string) any {
	var m map[string]any
	if err := json.Unmarshal([]byte(argsJSON), &m); err != nil {
		return argsJSON
	}
	return m
}

// extractPathArg はtool_callの引数JSONから"path"キーを取り出す
// （AutoGit.Checkpointのコミットメッセージにファイル名を含めるため）。
func extractPathArg(argsJSON string) string {
	var args struct {
		Path string `json:"path"`
	}
	if err := json.Unmarshal([]byte(argsJSON), &args); err != nil {
		return ""
	}
	return args.Path
}

func preview(s string) string {
	const max = 80
	if len(s) > max {
		return s[:max] + "..."
	}
	return s
}
