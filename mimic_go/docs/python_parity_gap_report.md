# mimic_tui (Python) → mimic_go (Go) 移植ギャップレポート

**最終更新: 2026-08-30（第4回・フェーズ4完了）。** 第2回全面監査（6グループ並列・grep裏取り必須）
で見つかったバグ2件・ギャップ21件、および見送っていた10件（フェーズ1〜4）をすべて実装・ビルド
確認・スモークテスト済み。既知のパリティギャップはすべて解消し、残るのは軽微な仕様差のみ。

凡例: 🔴 未実装（機能・影響大） / 🟡 部分実装・簡略化 / 🟢 意図的な仕様変更（問題なし）/
⚪ 実装済み・パリティあり

---

## ✅ 2026-08-30（第4回・フェーズ4）で解消した項目

見送りリストの最後の4件を実装した（一部はアーキテクチャ変更・実機検証を伴う大きめの項目）。

1. **`PipelineTypewriter`のStage1/2/3バッファリング機構** — `internal/tui/model.go`に
   `feedRawText`/`flushRawBuffer`を追加。改行 or 200文字に達するか、コードブロック(```)が
   閉じている場合にのみログへflushする（Python版`_should_flush`/`_flush_raw`の移植）。
   thinkブロックへの遷移時・ターン終了時は強制flushする。
2. **ビューアの委任親子ツリー表示・JSON構文ハイライト・折りたたみ** —
   `internal/delegate/worker.go`に`logTeamEvent`を追加し、`team_worker_start`/
   `team_supervisor_verdict`をDirectorのReactLogへsystem_eventとして記録（Python版は
   Python reprをast.literal_evalで復元するが、Go版はJSON文字列で記録しGo版ビューアが
   JSONとして読む — 相互運用性の制約が無いための単純化）。`internal/viewer/viewer.go`に
   trace_idベースの親子関係・実行状況バッジ（`computeSessionTree`/`teamBadgeFor`）、
   関連セッションリンク（`linkedSessions`）、スクラッチパッド更新履歴表示を追加。
   フロントエンドにJSON構文ハイライト・`<details>`による折りたたみを実装。
3. **Gemini Context Cache Manager** — `internal/llm/geminicache.go`を新設。
   `GeminiCacheManager.Get`がシステムプロンプト+ツール定義のMD5ハッシュで既存キャッシュの
   有効性を判定し、失効/内容変化時はGoogle生REST API
   （`https://generativelanguage.googleapis.com/v1beta/cachedContents`、OpenAI互換層とは別）
   でキャッシュを作成する。作成失敗時は10分間のバックオフ後に再試行し、それまでは通常送信に
   フォールバックする。`internal/llm/stream.go`でgeminiプロバイダの場合のみ有効化し、
   キャッシュ命中時はsystem message/toolsを省略し`cachedContent`フィールドで参照する。
4. **`/model`引数なし時のライブモデルセレクタ** — `*tea.Program`参照を`SetProgramRef`で
   package-levelに保持し（Model構築時点ではProgramがまだ存在しないため後から差し込む）、
   `/model`（引数なし）時に`ReleaseTerminal()`→既存の`selector.SelectInteractively`を
   バックグラウンドgoroutineで同期実行→`RestoreTerminal()`という流れで実装
   （`internal/tui/commands.go::liveModelSelectCmd`）。選択結果で`llm.Client`を丸ごと
   差し替え、会話履歴をリセットする。
   **注記**: この機能はTUIの実端末上での対話操作が前提のため、自動テストでの検証は
   限定的（ロジック単体のスモークテストのみ）。実機での動作確認を推奨する。

各項目とも`go build`/`go vet`クリーン、スモークテスト確認済み。

## ✅ 2026-08-28（第4回・フェーズ3）で解消した項目

見送りリストのうち、コマンドの対話フロー2件を実装した。

1. **`/search`・`/sessionsのヒット後コンテキスト注入フロー`** —
   `internal/tui/sessioninject.go`を新設し、Python版の`_search_sessions`/`_parse_session_file`/
   `resolve_session`/`build_session_inject_text`を移植。`/search <query>`はヒット一覧を表示後
   番号カンマ区切り/`all`/`n`の入力を待ち、`/sessions [番号|ファイル名]`はターン詳細を表示後
   `y/n`の入力を待つ（承認モーダルと同じ`pendingXxx`パターンでUpdate側に状態を持たせる）。
   確定すると選択内容が`user`+`assistant`メッセージとして会話履歴に注入される。
2. **`/delegations resume|discard`の実処理** — `internal/sandbox/overlay.go`に既存base
   ディレクトリからWorkroomを再構築する`AttachWorkroom`を追加し、
   `internal/delegate/inflight.go`に`ResumeDelegation`/`DiscardDelegation`を実装。
   resumeは`runWorkerInWorkroom`（既存のチェックポイント再開ロジックをそのまま利用）を
   バックグラウンドgoroutineで実行し、完了時に`delegationResumeResultMsg`でTUIへ通知する
   （Worker再実行は時間がかかるためUIをブロックしない）。`ListOrphanedDelegations`の
   返り値がmap由来で順序不定だったバグも同時に修正（開始時刻昇順でソート、番号が
   実行のたびにズレないように）。

## ✅ 2026-08-28（第4回・フェーズ2）で解消した項目

見送りリストのうち、TUIの中規模機能2件を実装した。

1. **Filesタブのプレビュー内`/`検索バー** — `internal/tui/model.go`にファイルプレビュー内
   正規表現検索（`runFileSearch`/`closeFileSearch`）を実装。`/`キーで検索モードに入り、
   Enterで確定するとマッチ行±2行のコンテキストのみをハイライト付きで表示する
   （Python版 app.py::_run_file_search と同じ挙動）。不正な正規表現はリテラル一致に
   フォールバックする。
2. **Scratchpadタブのサブエージェント表示・更新履歴** — Director自身の更新履歴
   （`tools.GetScratchpadHistory`）と、`delegate_to_team`/`delegate_to_worker`で起動した
   Workerのスクラッチパッド（`viewer.GetSessionScratchpadHistory`、trace_id経由でセッション
   JSONLから取得）を`renderScratchpad`で統合表示する。trace_id追跡のため
   `internal/delegate/history.go`の委任履歴リングバッファに`TraceID`フィールドを追加した
   （Python版はReactLogの`system_event`から拾うが、Go版はreactLogがinternal/delegateから
   見えない構成のため委任履歴バッファ自体にtrace_idを持たせる形で代替）。

## ✅ 2026-08-27（第3回）で解消した項目（バグ2件＋ギャップ21件）

### 🐛 バグ修正
1. **`read_file`の負のoffsetでpanicするリスク** — `internal/tools/file.go`にoffset下限ガードを追加。
2. **Worker委任apply時、チェックポイントファイルがプロジェクトに漏れ出す** —
   `internal/sandbox/overlay.go::applyExcludedPaths`に実際のパス`.mimic/checkpoint.json`を追加。

### コアループ/LLM層
3. 最終回答ゲートAの対象ツールに`run_host_command`を追加（`internal/react/gates.go`）
4. XML救済の検知パターンを拡充: `<invoke>`, `<function_calls>`, `[TOOL_CALL]`にも対応
   （`internal/react/xmlrescue.go`。パース対応フォーマット自体はPython版もtool_call/function=のみ
   という非対称設計を踏襲）
5. ストリーミング応答でcontentが空の場合の`reasoning`フィールドへのフォールバックを実装
   （`internal/llm/stream.go`）
6. ~~Mistral向け`prompt_cache_key`送信を実装~~ → Mistral対応自体を撤去したため削除済み
   （`internal/llm/client.go`）。
   `json_mode`はPython版でも実際は一度も`True`に設定されない死んだ状態のため意図的に見送り
7. `_repair_message_sequence`（孤立tool_calls/tool応答ペアの修復）を実装。Python版の実態に合わせ
   `internal/react/trim.go`の内容を`internal/llm/trim.go`へ移設（Python版もagent.py＝API層に
   これらのトリム関数を置いているため）
8. API例外のコンテキスト超過検知＋緊急トリム再送を実装（`internal/llm/stream.go::StreamChat`。
   400/429でコンテキスト超過キーワードを検知した場合、バックオフせずこの呼び出し限定のローカル
   コピーを削減して即リトライ。呼び出し元の会話履歴自体は変更しない＝Python版と同じ設計）
9. `run_pipeline`の出力キャッシュ — 調査の結果、`internal/react/loop.go`の全ツール共通の
   observation切り詰め層（`tools.CacheObs`）で既にカバーされていることを確認（コード変更不要）

### ツール
10. `read_file`/`read_tool_cache`/`CacheObs`をバイト単位からrune(文字)単位スライスに修正
    （`internal/tools/file.go`, `outputcache.go`）— マルチバイト文字混じりファイルでの
    オフセット・文字数表示のズレを解消
11. `grep_codebase`再帰検索でバイナリファイルを除外し、`maxResults`到達時に`filepath.SkipAll`で
    即座に打ち切るよう修正（`internal/tools/search.go`）
12. `web_search`にフォールバック抽出（uddgを含むhrefの二次抽出）を追加
13. `get_repo_map`（`goFileSymbols`）でレシーバ付きメソッドを対応する型にグルーピングして
    `type X(Method1, Method2)`形式で出力するよう修正（Python版の`class X(method1, method2)`相当）
14. `run_bash`タイムアウト後のSIGTERM→SIGKILL猶予を0.2秒→2秒に修正（Python版と一致）
15. MCP HTTPエラーメッセージ形式 — Go版はレスポンスボディ全文を含み情報量がPython版以上のため
    変更不要と判断

### Skills/MCP/委任
16. `/mcp`一覧が`.mcp.json`を都度再読込するよう修正。未接続かつ一度も接続を試みていない設定済み
    サーバーも「未接続（未試行）」として表示されるようになった（`internal/mcp/register.go`）
17. Researcher/読み取り専用Specialistのツールセットに`read_tool_cache`とブラウザ観測系
    （`browser_navigate`等6種）を追加（`internal/delegate/researcher.go`）
18. `runIsolated`のラウンド上限到達時に`[ラウンド上限到達・調査未完了]`ラベルを付与するよう修正
    （`internal/delegate/researcher.go`）。これにより`RunSpecialistTask`の完了判定
    （プレフィックス比較）が正しく機能するようになった
19. `RunSpecialistContinue`のinflightマニフェスト登録 — 内部で呼ぶ`runWorkerInWorkroom`が
    既に`registerInflight`/`unregisterInflight`を行っていることを確認（コード変更不要、
    古いコメントのみ修正）

### 監視/ログ
20. プロセス監視にFD数・スレッド数・平均CPU・サンプル数・経過秒数を追加し、`Current()`（停止せず
    現在値取得）メソッドを新設（`internal/vcs/procobserver.go`）
21. `ReactLog.SetJSONLPath`が既存JSONLファイルを読み込んでentriesへ復元するよう修正。
    `ReactLog.Clear()`を新設し`/clear`コマンドから呼ばれるよう配線（`internal/vcs/reactlog.go`,
    `internal/tui/commands.go`）

### TUI
22. thinkブロックに専用カラーテーマ（ミント系グレー）を適用し、通常のMarkdown装飾を通さず
    直接色付けするよう修正（`internal/tui/model.go`。Python版`render_markdown_thinker`が
    通常描画と別のレンダラーである設計を踏襲）
23. Logタブの表示件数を200件→100件に修正（Python版`_refresh_log_tab`と一致）

各項目とも`go build`/`go vet`クリーン、該当箇所は個別にスモークテストして確認済み
（テストファイルは検証後削除、本番コードには残していない）。

---

## ✅ 2026-08-28（第4回・フェーズ1）で解消した項目

見送りリストのうち、低リスクで自己完結する3件を実装した（`.claude/plans/nifty-conjuring-cat.md`
参照。フェーズ2以降は続けて着手予定）。

1. **`patch_file`第3段階（あいまい検索）** — LCSベースのratio類似度計算
   （`internal/tools/file.go::sequenceRatio`）で0.85閾値のあいまい一致を検出し、
   一致度が高くても自動修正はせず近似箇所のヒントをエラーに含める（Python版と同じ
   「誤書き込み防止のため自動適用しない」設計）。
2. **verify_cmd自動調達のLLM読み取り専用プローブ**（最大6ラウンド）—
   `internal/delegate/researcher.go::suggestVerifyCmd`を追加し、`internal/delegate/worker.go`の
   verify_cmd解決（学習庫→テンプレート）の3段目として配線。Python版は
   `delegate_to_specialist(can_write=True)`専用だが、Go版はWorker委任の入口を共通化している
   構造上、全`delegate_to_*`経路に広げている（意図的な拡張）。
3. **`_persist_digest_shadow`**（永続ダイジェストのシャドーモード保存）—
   `internal/react/compact.go::persistDigestShadow`を追加し、圧縮のたびに
   `.mimic/digests/<セッションキー>.json`へマージ保存する（動作に影響しない副作用のみ）。
   Python版はパッケージ設置ディレクトリ直下（グローバル）だが、Go版は他の`.mimic/*`と同様
   プロジェクト単位に適応。

## 🟡 残っている軽微な仕様差

見送りリストは全項目実装済み。以下は実装コストに対して効果が小さい、または意図的な設計判断
による軽微な差分のみ（個別に依頼があれば対応）。

- `grep_codebase`の正規表現方言差（Go RE2 vs 本家grep、後方参照非対応等）
- `smart_read(focus=)`がリテラル一致に固定（Python版は正規表現。意図的な安全側の変更）
- `fetch_webpage`の文字コード失敗時フォールバック挙動差（実害小）
- `_generate_diff`の出力フォーマット差（unified diff形式ではない自前LCS diff）
- `load_skill`のキャッシュキー命名規則の違い（Python: 固定キー / Go: 連番キー）
- `find_session_skill_usages`のtrace_id紐付け省略
- 構造化サマリJSON抽出が`verify_cmd`キーのみ（`target_files`/`steps`/`rollback`未使用）
- `RunTeamTask`のResearcher実行中はinflightマニフェスト未登録
- 書き込みインターロック拒否メッセージの案内文言が簡略化
- overlay再マウント時のworkdir明示再作成ステップがない
- デフォルトモデル値の相違（Python: `openrouter/owl-alpha` / Go: `openrouter/auto`）
- browser_*ツールが常時有効（Python版はオプトイン方式）— 設計判断として要レビュー

---

## 総括

コアループ・LLM呼び出し層・ツール群・委任システム・監視・TUI・ビューアの全域で、実際に発見
されたバグ2件を含む計37件（第3回23件＋第4回フェーズ1〜4の10件＋バグ2件）を解消した。
既知のパリティギャップはすべて解消済みで、残るのは意図的な仕様変更・軽微な実装差のみ。
`/model`ライブモデルセレクタとGemini Context Cache Managerは実機・実APIキーでの動作確認を
推奨する（コードレベルではビルド確認・スモークテスト済み）。

## 過去の解消済み項目（2026-08-27 第1回・第2回監査分、計34件）

詳細はgit履歴を参照。最終回答ゲートB配線、サンドボックスcopy-modeフォールバック、委任apply承認
ゲート、Gemini thought_signature、システムCPU/MEM計測、`.env`テンプレート自動生成、
`search_history`/`run_host_command`ツール、Specialistロール禁止事項チェック、`max_tokens`送信、
read_fileチャンクサイズ、並列ツール実行キャップ、圧縮しきい値計算、`_skip_save`フィルタリング、
write/edit/patch_fileの読み忘れ警告・diff・構文チェック、fetch_webpage文字コード検出、
browser_clickの`text=`セレクタ、Skillエイリアスヒント・使用トラッキング、`/skills reload`、
ラウンド数動的スケーリング、mtime競合検知、委任履歴のWorkerタスク注入、書き込みストリーク
リセット、KeyManager status系メソッド、CLK_TCK実測化、`MIMIC_DEFAULT_MODE`、キーバインド追加、
入力欄動的高さ、thinkブロックボックス化、セッション終了時`.md`保存、Filesタブの展開/折りたたみ・
スクロール・マウス操作対応
