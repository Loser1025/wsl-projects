// Package react はThought→Action→ObservationのReActループ本体を実装する
// （Python版 orchestrator.py::InteractiveOrchestrator.run_react の縮小版）。
//
// フェーズ1時点で移植済み: 基本ループ、tool_calls実行、履歴への追記、
// 観測の切り詰め、ループブレーカー、チェックポイント保存・再開。
// 未移植（後続フェーズ）: XMLツール呼び出し救済、最終回答ゲートA/B。
package react

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"mimic/internal/llm"
	"mimic/internal/tools"
	"mimic/internal/vcs"
)

// MaxSteps はPython版の MAX_REACT_STEPS = 120 をそのまま踏襲する。
const MaxSteps = 120

// MaxObservationChars はツール出力(observation)1件あたりの文字数上限。
// 上限なしで履歴に積み続けると、巨大なgrep結果等を含む長いターンで
// 履歴全体を毎ステップ再送信するReActの構造上、メモリ・帯域が
// 際限なく膨張する（実運用でOOM Killerに殺される事例を確認済み）。
const MaxObservationChars = 4000

// MaxRepeatedFailures は同一のツール呼び出し（名前+引数が同一）が
// 連続して失敗し続けた場合に強制終了するまでの回数
// （Python版ループブレーカーの「同一失敗3回」を踏襲）。
const MaxRepeatedFailures = 3

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

	var lastFailKey string
	failStreak := 0
	offloadRetryDone := false

	for step := 0; step < MaxSteps; step++ {
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
			// 最終回答ゲートA: 実行手段を持つのにユーザーへ丸投げしていないか検査する
			// （1ターンにつき1回だけ差し戻す。委任結果の未検証断言を見るゲートBは
			// 委任(delegate_*)が未実装のため現状発火しない — gates.go参照）。
			if !offloadRetryDone && detectCommandOffload(result.Text, toolNames) {
				offloadRetryDone = true
				*history = append(*history,
					llm.Message{Role: "assistant", Content: result.Text},
					llm.Message{Role: "user", Content: "[システム] 回答内でユーザーにコマンド実行や手動修正を依頼していますが、" +
						"実行はあなたの仕事です。あなたが持っている実行ツールを使って自分で実行してから結果を報告してください。\n" +
						"この環境で本当に実行できない場合（認証・対話操作が必要等）のみ、その理由を明記した上でユーザーへの依頼を残してください。"},
				)
				continue
			}

			// ツール呼び出しなし = 最終回答。履歴に記録して終了。
			*history = append(*history, llm.Message{Role: "assistant", Content: result.Text})
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

		// assistant メッセージ（tool_calls付き）を履歴に追記
		*history = append(*history, llm.Message{
			Role:      "assistant",
			Content:   result.Text,
			ToolCalls: result.ToolCalls,
		})

		// 各ツールを実行し、tool ロールの応答メッセージを追記する。
		// フェーズ1は逐次実行のみ（Python版の並列実行は後続フェーズで移植）。
		for _, tc := range result.ToolCalls {
			if onTool != nil {
				onTool(ToolActivity{Name: tc.Function.Name, ArgsPreview: preview(tc.Function.Arguments)})
			}
			if reactLog != nil {
				reactLog.Add("action", map[string]any{"tool": tc.Function.Name, "args": rawJSONArgs(tc.Function.Arguments), "step": step})
			}
			callStart := time.Now()
			output := registry.Call(tc.Function.Name, tc.Function.Arguments)
			elapsed := time.Since(callStart)

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
				callLog.Add(vcs.ToolCallRecord{Tool: tc.Function.Name, Elapsed: elapsed, Status: status, Occurred: callStart})
			}
			if reactLog != nil {
				resultPreview := output
				if len(resultPreview) > 500 {
					resultPreview = resultPreview[:500]
				}
				reactLog.Add("observation", map[string]any{"tool": tc.Function.Name, "result": resultPreview, "step": step})
			}
			isFail := isFailForLog
			key := tc.Function.Name + "|" + tc.Function.Arguments
			if isFail && key == lastFailKey {
				failStreak++
			} else if isFail {
				lastFailKey = key
				failStreak = 1
			} else {
				lastFailKey = ""
				failStreak = 0
			}

			*history = append(*history, llm.Message{
				Role:       "tool",
				ToolCallID: tc.ID,
				Content:    truncateObservation(output),
			})

			if autoGit != nil && !isFail && vcs.WriteTools[tc.Function.Name] {
				autoGit.Checkpoint(cwd, tc.Function.Name, extractPathArg(tc.Function.Arguments))
			}

			if isFail && failStreak >= MaxRepeatedFailures {
				return "", fmt.Errorf("ループブレーカー: ツール呼び出し %s が同一引数で%d回連続失敗したため中断しました", tc.Function.Name, failStreak)
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

// isFailure はツール実行結果が Registry.Call のエラー整形文字列かどうかを判定する
// （tools.Registry.Call は "エラー: ..." / "ツール実行エラー: ..." 形式で返す方針）。
func isFailure(output string) bool {
	return strings.HasPrefix(output, "エラー:") || strings.HasPrefix(output, "ツール実行エラー:")
}

// truncateObservation はツール出力(observation)を上限文字数で切り詰める。
func truncateObservation(s string) string {
	if len(s) <= MaxObservationChars {
		return s
	}
	return s[:MaxObservationChars] + fmt.Sprintf("\n...(以下省略、観測切り詰め: 全%d文字中%d文字を表示)", len(s), MaxObservationChars)
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
