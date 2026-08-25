# mimic_tui (Python) → mimic_go (Go) 移植ギャップレポート

調査日: 2026-08-25。`mimic_tui`の全モジュールと`mimic_go`を突き合わせ、6領域に分けてコード全文を比較した結果。

凡例: 🔴 未実装（機能・安全性への影響大） / 🟡 部分実装・簡略化 / 🟢 意図的な仕様変更（問題なし） / ⚪ 実装済み・パリティあり

---

## 最優先で埋めるべきギャップ（安全性・正しさに直結）

1. 🔴 **書き込み承認フローが皆無**（`internal/tools`）— `write_file`/`edit_file`/`patch_file`/`delete_file`が無条件で即実行される。Python版の`_request_write_approval`/`UserRejectedWriteError`に相当する仕組みがゼロ。TUI側の承認UI（ASCII枠・Y/n・タイムアウト自動承認）も連動して未実装。
2. 🔴 **Workerサンドボックスの書き込み境界チェックが機能していない**（`internal/tools`）— `MIMIC_NO_AUTOGIT`環境変数はWorker起動時にセットされる（`internal/delegate/worker.go`）が、`internal/tools`側の書き込み系ツールはこれを一切読んでいない。`_check_worker_write_boundary`/`_worker_outside_write_warning`相当が存在せず、Workerがサンドボックス外へ書き込んでも防止されない。
3. 🔴 **MCPツール呼び出しに承認ゲートが一切ない**（`internal/mcp`）— Python版は`readOnlyHint`を信用せず全MCP呼び出しを`_request_write_approval`に通す設計だが、Go版は接続時のreadonly_onlyフィルタ（Worker専用）以外に安全境界が存在しない。Directorモードでは無制限に実行される。
4. 🔴 **委任の適用（apply）がロック無しで並行実行される**（`internal/delegate`）— `delegate_to_team_parallel`は3並列でWorkerを実行するが、`ApplyChanges`にPython版`_apply_lock`相当の排他制御がない。同一プロジェクトへの同時書き込みで競合が起きうる。
5. 🔴 **削除の反映（overlay whiteout）が未実装**（`internal/delegate/overlay.go`）— Workerがサンドボックス内でファイルを削除しても、`ApplyChanges`はコピーのみでwhiteoutマーカーを走査しないため、実プロジェクトから削除されない。
6. 🔴 **委任結果がAutoGitにコミットされない**（`internal/delegate`）— `apply_subagent_changes`後のcheckpoint commitに相当する処理がなく、適用された変更が記録されずに残る。

---

## 領域1: コアReActループ（agent.py/orchestrator.py → internal/llm, internal/react）

| 項目 | 状態 | 備考 |
|---|---|---|
| ストリーミングのCtrl+C中断 | 🟡 | Goはcontext cancelベース。ヘッダー到達後の`Scan()`中は中断が効かない可能性 |
| `run`/`run_stream`非React系ループ | 🔴 | `RunTurn`(ReAct専用)のみ。実運用上は影響小 |
| リトライ/バックオフ | ⚪ | パリティあり |
| コンテキスト超過時のtrim/repair (`_trim_messages_smart`等) | 🔴 | 完全未移植（コメントで明記済み） |
| 会話圧縮 (`_compact_if_needed`, digest生成) | 🔴 | 完全未移植 |
| `_build_context_header`（タスク目標・直近書き込み・委任履歴の自動注入） | 🔴 | 未移植 |
| Geminiコンテキストキャッシュ | 🔴 | 未移植 |
| ツール結果LRUキャッシュ（128件） | 🔴 | 未移植、書き込み時の無効化も無し |
| Gemini `thought_signature`往復保持 | 🔴 | 未移植 |
| MAX_REACT_STEPS=120 | ⚪ | 一致 |
| AutoGit backup/checkpoint/squash呼び出し | ⚪ | ライフサイクル一致 |
| チェックポイント再開（resume note注入含む） | 🟡 | 保存/クリアはあるが、resume時のノート注入呼び出し箇所が不明瞭 |
| XML tool call救済 | 🟡 | パース自体は移植済みだが、パース失敗時の再プロンプトリトライ（`_MAX_XML_TOOL_RETRIES`）が無い |
| 読み取り専用ツールの並列実行 | 🔴 | 全ツール呼び出しが逐次実行。ThreadPoolExecutor相当なし |
| stale observation無効化（書き込み後の古いread結果上書き） | 🔴 | 未移植 |
| Observation切り詰め定数 | 🟡 | Go=4000字 / Python=2000字で不一致。委任用6000字・peek用600字のtier分けも無し |
| ループブレーカー | 🟡 | Goは3回失敗で即ターン中断（ハード）。Pythonは「拒否」を挟んで5回拒否まで許容する二段構え——Goの方が厳しすぎる挙動 |
| Gate A（コマンド丸投げ検出） | ⚪ | 実装済み・パリティあり |
| Gate B（未検証claim検出） | 🟡 | 実装はあるが発火元（委任結果）が無いため常にdead code |
| プロンプトバリアント（REACT/SPECIALIST/WORKER系） | 🔴 | 未移植。`RunTurn`はフラットな1本のsystemPromptのみ |
| 2モード（interactive/specialist）とツールセット差分 | 🔴 | モード概念自体が存在しない |
| 空応答時の再プロンプト（`_MAX_EMPTY_RETRIES`） | 🔴 | 未移植 |
| max_tokens/json_mode/response_formatのペイロード送出 | 🔴 | リクエスト構造体にフィールド自体がない |

*(注記: CLAUDE.mdに記載の`_THINK_BUDGET_CHARS=15000`強制キャンセルは実際のPythonコードには存在せず、ドキュメントの記載ミス。Go側の未実装は問題ではない)*

---

## 領域2: ツール/パイプライン（tools.py, tools_linux.py, pipeline.py → internal/tools）

### ツール一覧対応表

| Pythonツール | Go状態 |
|---|---|
| read_file | ⚪ 実装済み（チャンクサイズ相違あり） |
| write_file/edit_file/patch_file | 🟡 動くが承認ゲート・read警告・境界チェック・diff生成が無い |
| patch_file のfuzzy match | 🟡 3段階中2段階のみ移植（difflib相当が無い） |
| read_tool_cache | 🔴 未実装（キャッシュ機構自体が無い） |
| get_repo_map | ⚪ |
| run_bash | 🟡 pty未使用（`exec.CommandContext`）。sudo自動入力・端末シーケンス除去・worker警告付与が無い |
| file_info | ⚪ |
| grep_codebase | 🟡 正規表現ではなく単純部分一致。除外ディレクトリ/ファイルも少ない（7個 vs 17個、ファイル除外は0個） |
| smart_read | ⚪ |
| run_pipeline | 🟡 ストリーミング自体は移植済みだが出力キャッシュ・worker警告が無い |
| web_search/fetch_webpage | ⚪ |
| browser_*系 | — 意図的に後回し（対象外） |

### その他
- 🔴 大容量出力の自動キャッシュ（10000字超→`cache_tool_output`/`read_tool_cache`ページング）が皆無。「弱いLLM＋厳格なハーネス」というプロジェクトの設計思想に直結する欠落。
- 🔴 `_check_read_warning`（書き込み前read確認）が未移植。
- 🟡 grepの行切り詰めがGo=200字 / Python=300字で不一致。

---

## 領域3: Skills / MCP（skills.py, mcp_client.py → internal/tools/skills.go, internal/mcp）

- 🔴 **Skillの常時サマリー注入（1500字上限、毎ターンプロンプトに自動掲載）が配線されていない** — 定数だけ定義されており使われていない。モデルが`list_skills`を能動的に呼ばない限りSkillの存在に気づけない（Progressive Disclosureが実質死んでいる）。
- 🔴 Skill本文6000字超過時のページング継続が無く、内容が本当に失われる。
- 🔴 ツール名エイリアスヒント（Read/Edit/Bash→read_file/edit_file/run_bash等）が未移植。
- 🟡 trust scoring自体は動くが、trace_idベースの使用量帰属ではなくWorker自身のupperdir走査という簡略版。
- 🔴 `/skills`コマンド（一覧・reload）が未配線。
- ⚪ MCPのstdio/HTTPトランスポート、.mcp.json読み込み順は忠実に移植済み。
- 🔴 **MCP呼び出しの承認ゲートが皆無**（最優先ギャップ、上記参照）。
- 🔴 `/mcp status/reconnect/trust`コマンドが未配線。`ShutdownAll()`はあるが呼び出し箇所がゼロ（atexit相当が動いていない）。
- 未確認: Specialistモードでの`mcp__`系ツール除外（モード自体が無いため恐らく該当なし）。

---

## 領域4: 委任/サブエージェント（team.py, subagent.py → internal/delegate）

- ⚪ Researcherフェーズ、Workerサンドボックス機構（unshare+OverlayFS、copyフォールバック含む）は構造的に忠実に移植されている。
- 🔴 `MIMIC_PROVIDER`/`MIMIC_MODEL`環境変数がWorkerへ引き継がれない（DirectorとWorkerでモデルが食い違う可能性）。
- 🔴 **Workerの標準出力がライブストリーミングされない** — 完了までバッファリングされ、進捗が見えない。
- 🔴 クラッシュリカバリ（`===MIMIC_FINAL===`マーカー未検出時の最大3回再起動）が未実装。Workerが静かにクラッシュすると復旧手段が無い。
- 🔴 **overlay whiteoutによる削除反映が無い**（最優先ギャップ、上記参照）。
- 🔴 `_apply_lock`相当の排他制御が無い（最優先ギャップ、上記参照）。
- 🔴 適用後のAutoGitコミットが無い（最優先ギャップ、上記参照）。
- 🔴 verify_cmd学習機構（`.mimic/verify_cmds.json`、テンプレート自動生成）が全く無い。
- 🔴 全委任を跨ぐグローバル同時実行数セマフォ（`_MAX_DELEGATION_CONCURRENCY=3`）が無い（`delegate_to_team_parallel`内のローカル制限のみ）。
- 🔴 `_rounds_for_specialist`のロール・タスク長に応じたラウンド数スケーリング（12→18→24）が無く、固定8ラウンド。
- 🟡 書き込みインターロックは実装済みだが、read-only委任完了時のストリークリセットが無い。
- 🔴 **ロール定義の永続化（`.mimic/roles/*.json`）が全く無い** — 成功した委任ロールがセッションを跨いで再利用されない。
- 🔴 `get_delegation_trace`ツールが皆無（trace_id自体が存在しない）。
- 🔴 **孤立委任のリカバリ機構が全く無い**（`.mimic/inflight_delegations.json`、`/delegations`コマンド） — Director側がクラッシュした場合、サンドボックスのtempdirが検出も回収もされず放置される。
- 🔴 apply承認ゲート（`APPLY_APPROVAL=ask/threshold`）が無く、常に自動適用。

---

## 領域5: AutoGit/監視/ベンチマーク/設定

- ⚪ AutoGitのbackup/checkpoint/squash/rollback/diffは忠実に移植済み。
- 🔴 **監視レイヤーの中核（`MonitoringToolRegistry`、CPU/RSSサンプリング、`/stats`配線）がほぼ丸ごと未実装** — `ToolCallRecord`/`ToolCallLog`のデータ構造だけ存在し、実際に計測して詰める仕組みが無い（意図的に見送りとコメントあり）。
- 🟡 ベンチマーク集計はSkill統計のみ移植済み。MCP統計・verify_cmd統計は該当機能自体が無いため対象外（明示的にスコープ外と明記）。
- 🔴 `GEMINI_THINKING_LEVEL`（reasoning_effortマッピング）がプロジェクト全体で未実装。
- 🔴 KeyManager相当（RPMトークンバケット、429クールダウン）が`internal/config`に見当たらない（他パッケージにある可能性は要確認）。
- 🔴 `.env`が存在しない場合のテンプレート自動生成・オンボーディング案内が無い（単にエラー終了）。
- 🟡 `.env`のBOM処理が無く、UTF-8 BOM付きファイルで先頭キーのパースが壊れる。
- 🟢 モデル一覧取得・対話的セレクターの簡略化（固定優先順位で自動選択）は意図的なスコープ外と明記済み。

---

## 領域6: TUI/コマンド/エントリポイント

### スラッシュコマンド対応表

| Pythonコマンド | Go状態 |
|---|---|
| /status /clear /model /mode /cd /help /search /sessions /skills /delegations /mcp | 🔴 すべて未実装 |
| /scratchpad | 🟡 タブ（F3）としては存在、コマンドとしては無い |
| /viewer | 🟡 常時起動なのでコマンド自体は不要だが、ブラウザ自動起動が無い |
| /stats /bench | ⚪ 実装済み（ただしハードコード分岐、汎用コマンドレジストリではない） |
| /undo | 🟢 Go独自追加（Python版に無い） |

- 🔴 **モード切替（interactive/specialist）の概念がGoに全く無い** — ツールセット差分もsystem prompt差分も存在しない。
- 🔴 ステータスパネルに`Mode:`/`Role:`行が無い（`■ SYSTEM`のCPU/MEMは既知の未実装として確認済み）。
- 🔴 承認UI（ASCII枠・Y/n・タイムアウト）が未実装（ツール側承認フローとセットで対応要）。
- 🔴 **チャットログがプレーンテキストのみでMarkdownレンダリングされていない**（Python版は`RichMarkdown`で毎チャンク整形）。
- 🔴 起動時の孤立委任24時間警告が無い（`/delegations`未実装と連動）。
- 🟡 `--auto-prompt`のWorker向け`MIMIC_PROVIDER`/`MIMIC_MODEL`引き継ぎが無い。
- ⚪ `--env`/`--prompt`/`--auto-prompt`/`--status`の基本フラグ・`===MIMIC_FINAL===`マーカーは機能的に等価。
- 🔴 SIGTERM/SIGHUPハンドリングが無い。

---

## 総括

現状のGo版は「単独ユーザーが単一モードでチャットしながらツールを呼ぶ」という中核のReActループ・基本ツール群・UIの見た目についてはかなり忠実に移植が進んでいる一方、以下の3つの大きな柱がまるごと未着手です。

1. **承認・安全境界**（書き込み承認、Workerサンドボックス境界チェック、MCP承認、apply承認） — 現状Go版はほぼ全自動実行で、Python版が意図的に設けている「人間の確認」「サンドボックス脱出防止」が機能していません。
2. **委任システムの信頼性機構**（クラッシュ復旧、孤立委任リカバリ、ロール永続化、apply時のロック/コミット/削除反映、verify_cmd学習） — 委任の骨格は動くが、長時間運用・再現性・障害耐性に関わる部分が軒並み未実装です。
3. **コンテキスト管理**（会話圧縮、ツール結果キャッシュ、大容量出力ページング、Skillの常時サマリー注入） — 「弱いLLM＋厳格なハーネス」というプロジェクトの根幹思想に関わる部分で、長いセッションや複雑なタスクでの実用性に直結します。

どこから着手するか、優先順位を一緒に決めましょうか。
