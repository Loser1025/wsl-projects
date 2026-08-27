# mimic_tui (Python) → mimic_go (Go) 移植ギャップレポート

**最終全面再監査: 2026-08-27。** Python版20ファイル・約12,800行を全文読み、Go版と1ファイルずつ
突き合わせる形で実施（6グループに分割、並列調査＋相互検証・スポットチェック）。過去の緩い
調査（「領域ごとに自由に探索」方式）では、grepせずに「未実装」と誤判定する事例が発生していた
ため、今回は**判定前に必ずgrepで裏取りする**ことを全担当に義務付け、実際にいくつかの誤検知
（後述）を防げた。

**同日中に、この監査で見つかった優先度高（🔴）項目11件すべてを実装・ビルド確認・
スモークテスト済み。** 詳細は「解消済み（2026-08-27実装分）」セクション参照。

凡例: 🔴 未実装（機能・影響大） / 🟡 部分実装・簡略化 / 🔴(dead) 定義はあるが呼び出されていない
デッドコード / 🟢 意図的な仕様変更（問題なし）/ ⚪ 実装済み・パリティあり

---

## 解消済み（2026-08-27実装分）

再監査で見つかった優先度高の項目をすべて実装した。各項目はビルド確認済み、
多くは実機動作するスモークテストで確認済み。

1. ⚪ **MCPリモートサーバーの`headers`設定バグを修正** — `ServerSpec`に`Headers`
   フィールドを追加し、`register.go`が`env`ではなく`headers`をHTTPトランスポートへ渡すよう修正。
2. ⚪ **最終回答ゲートB（未検証claim検出）の配線漏れを修正** — `worker.go`が
   verify_cmd未指定の書き込み委任結果に「※未検証」マーカーを付与し、`loop.go`がそれを
   検出して`turnHadUnverified`を立て、ゲートBを実際に呼び出すよう修正。
3. ⚪ **サンドボックスのcopy-modeフォールバックを配線** — `NewWorkroom`が起動時に
   `DetectMode()`の結果をキャッシュして使用するようになり、unshare/overlay非対応環境
   では自動的にcopy-mode（全体コピー+差分比較）にフォールバックするようになった。
   `Run`/`ChangedFiles`/`ApplyChanges`すべてモード別に分岐。
4. ⚪ **委任apply承認ゲートを実装** — `APPLY_APPROVAL=auto/ask/threshold`環境変数
   による適用前承認ポリシー（`internal/delegate/applyapproval.go`）と、TUI側の
   apply承認モーダル（書き込み承認と同じUI・タイムアウト機構）を実装。
5. ⚪ **Gemini `thought_signature`のラウンドトリップを実装** — `ToolCall`構造体に
   `ExtraContent.Google.ThoughtSignature`を追加し、ストリーミング受信時のパースと
   次リクエストでの再送をJSON構造体レベルで自動化。
6. ⚪ **システムCPU/MEM計測と■ SYSTEMステータスパネルを実装** — `/proc/stat`・
   `/proc/meminfo`ベースの計測（`internal/vcs/systemstats.go`）を2秒間隔でTUIへ反映。
7. ⚪ **`.env`テンプレート自動生成を実装** — `.env`が存在しない場合にテンプレートを
   書き出し、`ErrEnvTemplateGenerated`番兵エラーで正常終了(exit 0)するよう修正。
8. ⚪ **`search_history`ツールを実装** — セッションJSONLの横断検索（キーワード検索・
   空クエリでの全件サマリ）を新規追加。
9. ⚪ **`run_host_command`ツールを実装** — ホスト直接実行（要承認、Worker環境では
   拒否、非対話モードでは常に拒否）を新規追加。TUI側の専用承認モーダルも実装。
10. ⚪ **Specialistロールの禁止事項フィールドチェックを配線** — `MIMIC_ROLE_REQUIRE_FORBIDDEN=1`
    による2段階導入方式（既定は警告のみ、環境変数で拒否化）を実装。以前は変数が
    宣言のみでチェック自体が呼ばれないデッドコードだった。
11. ⚪ **`max_tokens`をLLMリクエストペイロードに送信** — 設定されているのに一度も
    送信されていなかった`max_tokens`を`streamRequest`に追加。

---

## 解消済み（2026-08-27追加バッチ: 中〜低優先度ギャップ23件）

上記の🔴優先度高11件に続き、同日中に「🟡まだ残っているギャップ」として記録されていた
中〜低優先度の23項目（Task #59-81）もすべて実装・ビルド確認・スモークテスト済み。

**ツール**:
1. ⚪ `read_file`チャンクサイズを20000→10000字へ修正（Python版と一致）。
2. ⚪ write/edit/patch_fileに読み忘れ警告（`internal/tools/readtracker.go`の
   per-turn既読レジストリ）・LCSベースdiffスニペット・非ブロッキング構文チェック
   （.json/.ts/.tsx/.py）を実装。
3. ⚪ `fetch_webpage`のContent-Type charset自動検出を実装
   （`golang.org/x/text/encoding/htmlindex`、Shift_JIS等）。
4. ⚪ `browser_click`にPlaywright風`text=`擬似セレクタ対応を追加
   （chromedpの`BySearch`/DOM.performSearchへ変換）。
5. ⚪ Skillツール名エイリアスヒント（Read→read_file等）とインプロセスSkill使用
   トラッキング（`MarkSkillLoaded`/`PopUsedSkills`、Director/読み取り専用Specialist
   のverify結果をtrustスコアへ反映）を実装。
6. ⚪ `/skills reload`サブコマンドを追加。

**委任システム**:
7. ⚪ `/mcp`ステータス表示に未接続サーバーもエラー理由付きで表示するよう修正
   （`lastResults`を追加保持）。
8. ⚪ 読み取り専用Specialistのラウンド数動的スケーリング（12→18→24、role+task長ベース）
   を実装（`roundsForSpecialist`）。
9. ⚪ 委任apply時のmtimeベース競合検知を実装（Worker実行中に本体側でも変更された
   ファイルを検出し警告）。
10. ⚪ 委任履歴（直近5件）をWorkerのタスク文冒頭にも自動注入するよう修正
    （従来はDirectorのcontext headerのみ）。
11. ⚪ 書き込みストリークインターロックの読み取り専用/実行専用委任完了時リセット
    （`noteReadonlyDelegation`）を実装。機械検証通過時のリセットも追加。

**KeyManager/システム計測**:
12. ⚪ KeyManagerの`Status`/`NReadyKeys`/`WaitForNKeys`/`TotalTokensAvailable`
    メソッドを実装し、`/status`コマンドに反映。
13. ⚪ jiffy(CLK_TCK)を`getconf CLK_TCK`で実測するよう修正（従来は固定100Hz）。

**TUI**:
14. ⚪ `MIMIC_DEFAULT_MODE`環境変数を実装（既定でspecialistモード起動、
    `interactive`指定で従来のReActを既定化）。
15. ⚪ Ctrl+L（画面クリア）/PageUp/PageDown/Ctrl+Home/Ctrl+Endキーバインドを実装。
16. ⚪ 入力欄の動的高さ変更（1〜5行）を実装。
17. ⚪ `<think>`ブロックの表示を単一行折りたたみから複数行ボーダーボックス
    （`╭─ 💭 思考中 ─...` / `│ `プレフィックス / `╰──...`）へ変更。
18. ⚪ セッション終了時（Ctrl+C/Ctrl+Q）の`.md`サマリー自動保存を配線
    （`ReactLog.SaveSession`は既存実装済みだったが呼び出し側が未配線だった）。

**ドキュメント整合性**:
19. ⚪ `internal/tools/skills.go`・`internal/delegate/worker.go`・
    `internal/delegate/specialist.go`の古いパッケージ/関数コメント（「未移植」
    「未実装」と書かれたまま実装済みになっていた箇所）を実装済み内容に合わせて修正。

---

## 総括

安全境界・委任システムの基本骨格・コンテキスト管理・TUI基本操作・出力レンダリング・
browser_*ツールの実機動作・そして今回判明した優先度高ギャップの実装まで含め、
**主要な実行パスはPython版とパリティが取れている**。

---

## グループA: コアループ/エージェント（agent.py, orchestrator.py, main.py, __main__.py）

### ⚪ パリティ確認済み
- リトライ/バックオフ・キーローテーション・RPMトークンバケット（agent.py:387-397,850-949 ↔ llm/stream.go, llm/keymanager.go）
- 送信直前トリム `_trim_to_fit`/`_trim_messages_smart`（agent.py:755-775,201-242 ↔ react/trim.go）
- ReActループ骨格・XML救済・両ゲート実装本体・ループブレーカー・観測切り詰め・チェックポイント（orchestrator.py:19-976 ↔ react/{loop,gates,xmlrescue,checkpoint}.go、定数完全一致）
- CPU/RSS監視・ReactLog（monitoring.py, autogit.py ↔ vcs.ProcessMonitor/ReactLog、loop.go配線）
- `--status`モード・SIGTERM/SIGHUP（__main__.py:99-103,336-344 ↔ main.go）
- MCP接続は`tui.NewModel`内部で行われている（`internal/tui/model.go:209`）— **要訂正**: Group Aは
  当初main.goのみを見て「対話TUIにMCPが配線されていない」と誤検知したが、呼び出し先の
  `NewModel`まで追ったところ実装済みと確認。

### 🔴 未実装・実質デッドコード
- ✅**2026-08-27実装済み**: 最終回答ゲートB（未検証claim検出） — `worker.go`が
  verify_cmd未指定の書き込み委任結果に「※未検証」マーカーを付与し、`loop.go`が
  `turnHadUnverified`を計算してゲートBを実際に呼び出すよう修正。
- ✅**2026-08-27実装済み**: Gemini `thought_signature`のラウンドトリップ — `ToolCall`に
  `ExtraContent.Google.ThoughtSignature`を追加し、JSON構造体レベルで自動往復するよう修正。
- **`_repair_message_sequence`（孤立tool_calls修復）未移植** — Python: agent.py:348-382 ↔
  Go: none found。チェックポイント再開時に整合しないtool_calls/tool履歴がAPIへ送られる
  リスクあり。
- **永続ダイジェスト・シャドーモード未移植**（`.mimic/digests/`、比較用ログのみで実行には
  影響しない低優先度機能）— Python: agent.py:292-345 ↔ Go: none found。

### 🟡 部分実装
- ✅**2026-08-27実装済み**: `max_tokens`を`streamRequest`に追加し、実際にペイロードへ送信するよう修正。
- `_skip_save`相当のフィルタリングが無く、ゲート・空応答リトライの内部システムメッセージが
  会話履歴に永続的に蓄積される（Python: orchestrator.py:749-751でフィルタ、Go: 
  `tui/model.go`が全履歴をそのまま保存）。
- 圧縮しきい値がsystem prompt/context headerのオーバーヘッドを差し引いていない
  （Python `_effective_threshold`未移植、Go: `compact.go`はcontextLengthのみで計算）。
- チェックポイントに`_read_call_ids`（stale-read無効化マップ）が保存されず、resume後に
  古いread結果の無効化が効かなくなる。
- 並列ツール実行にPython版の`max_workers=min(len,4)`のようなキャップが無い（Go:
  goroutine数が無制限、実害は小さい）。
- コンテキスト超過時のトリム・リトライ（`_is_context_exceeded`検知）が未移植（Go側コメントで
  自己申告済み）。

### 🔴 大機能欠落（他グループとも関連）
- Interactive/Specialistモード切替の**コアループ側**の意識（Gate Bの`turnHadUnverified`計算等）
  は無いが、モード切替自体はTUI側（グループF確認）に実装されている。

---

## グループB: ツール（tools.py, tools_linux.py, pipeline.py）

### ⚪ パリティ確認済み
- ToolRegistry基盤・load_skill/list_skills・read_tool_cache・get_repo_map（Go版はgo/parser使用、
  意図的仕様変更）・run_bash（pty・sudo自動入力・SIGTERM/SIGKILLエスカレーション）・
  file_info・smart_read・web_search・run_pipeline・書き込み承認プラミング・Worker境界チェック

### ✅ 2026-08-27実装済み
- **`run_host_command`ツール** — ホスト直接実行（要承認、Workerでは拒否、非対話
  モードでは常に拒否）を新規実装。TUI側専用承認モーダルも実装。
- **`search_history`ツール** — セッションJSONL横断検索（キーワード検索・空クエリ
  での全件サマリ）を新規実装。

### 🟡 部分実装
- patch_fileの3段階マッチのうち3段階目（difflibベースのあいまいブロック検索、閾値0.85）が
  未実装（Go側コメントで自己申告済み）。
- write_file/edit_file/patch_fileで「このターン内でread_fileしていないファイルへの書き込み」
  警告（`_check_read_warning`）・書き込み後のsyntaxチェック（Python/JSON/tsc）・
  unified diffスニペット表示（30行cap）がすべて欠落。Go側は成功/失敗と行数差分のみ返す。
- read_fileのチャンクサイズがPython版10,000字→Go版20,000字にズレている
  （read_tool_cache側のチャンクサイズ10,000字は一致）。
- fetch_webpageが`Content-Type`ヘッダーの文字コードを見ず常にUTF-8としてデコードする
  （Shift-JIS/EUC-JP等のページで文字化けする）。
- grep_codebaseがGo標準`regexp`（RE2構文）を使用しており、Python版の実`grep`コマンド
  （BRE/GNU拡張、バックリファレンス等）と正規表現の方言が異なる。単純パターンは同じ結果。
- browser_clickがCSSセレクタのみ対応、Playwrightの`text=...`疑似セレクタ相当が無い。
- update_scratchpad_smart（Scribe圧縮提案付き版）がGo側に見当たらない（未検証、確信度低）。

### 🟢 意図的な仕様変更（要レビュー推奨）
- **browser_*ツールが常時有効** — Python版は`enable_browser_tools()`/`disable_browser_tools()`
  によるオプトイン方式（`_browser_registry`は既定では登録されない）。Go版は
  `NewDefaultRegistry`が無条件で`registerBrowserTools`を呼ぶため、Specialist読み取り専用
  モードなど、Python版では意図的にbrowser_*を持たないはずの文脈でも常に利用可能になっている。
  設計判断として妥当か要確認。

---

## グループC: Skills/MCP（skills.py, mcp_client.py）

### ⚪ パリティ確認済み
- SKILL.mdスキャン・progressive disclosure・context header注入・trust badge・
  トラストスコア永続化（保存先はプロジェクト単位に意図的変更）・stdio/HTTP両トランスポート・
  承認ゲート・readonly_only接続フィルタ・`/mcp trust`・`/mcp reconnect`・Specialist除外

### ✅ 2026-08-27実装済み（実質的なバグ）
- **HTTPリモートMCPサーバーの`headers`設定バグを修正** — `ServerSpec`に`Headers`
  フィールドを追加し、`register.go`が`Env`ではなく`Headers`をHTTPトランスポートへ
  渡すよう修正。認証必須のリモートMCPサーバーが機能するようになった。

### 🔴 欠落
- ツール名エイリアスヒント（Read/Write/Bash等の表記ゆれ案内、`load_skill`応答に付加）
- インプロセス実行（Director自身・読み取り専用Specialist）でのSkill使用トラッキング
  （`mark_loaded`/`pop_used`相当）— trust scoreはWorkerサブプロセス経由の使用のみ記録される

### 🟡 部分実装
- `/mcp`のステータス表示が接続中サーバーのみ列挙し、設定はあるが未接続/失敗したサーバーを
  表示しない（Python版はエラー理由付きで全設定サーバーを表示）。
- `/skills reload`という明示サブコマンドが無い（ただし`/skills`は毎回rescanするため、
  実質的には常に最新状態＝上位互換の挙動）。
- `client.go`冒頭のパッケージコメントが「HTTPトランスポート・承認UIは未実装」と書いているが
  **両方とも実装済み** — コメントが古いだけで機能はある。ドキュメント整合性の問題。

---

## グループD: 委任/サブエージェント（team.py, subagent.py）

### ⚪ パリティ確認済み
- Researcher基本フロー・delegate_to_worker/team/team_parallel/research・verify retry loop・
  中止exit code判定・委任同時実行数セマフォ・孤立委任マニフェスト（検出/警告のみ）・
  Specialistロール永続化・OverlayFS隔離・whiteout削除・apply_lock・クラッシュ再開・
  タイムアウトwatchdog・trace_id/MIMIC_TRACE_ID配線・get_delegation_trace

### ✅ 2026-08-27実装済み
- **委任apply承認ゲート** — `APPLY_APPROVAL=auto/ask/threshold`環境変数
  （`internal/delegate/applyapproval.go`）＋TUI側apply承認モーダルを実装。
- **サンドボックスのcopy-modeフォールバック** — `NewWorkroom`が起動時に
  `DetectMode()`の結果を使うようになり、unshare/overlay非対応環境では自動的に
  copy-modeへフォールバックするようになった。

### 🔴 完全欠落
- **孤立委任の実際のresume/discard実行アクションが無い**（一覧・24時間警告はあるが、
  実際に中断委任を再開/破棄する手段が無い。Python: team.py:1343-1376）。
- **ラウンド数の動的スケーリング（12→18→24、role+task長に応じて）が無く固定8ラウンド**
  （`_rounds_for_specialist`未移植）。
- `_run_isolated`（Researcher/読み取り専用Specialist）にXML救済・構造化回答強制の
  再要求ループが無い。

### 🟡 部分実装
- Structured JSON plan抽出が`verify_cmd`のみ取り出し、`target_files`/`steps`/`rollback`を
  破棄している。
- 委任apply時の同時編集競合検知（mtimeベース警告）が無い。
- 委任履歴がDirectorのcontext headerには注入されるが、**Worker自身のタスク文には
  注入されていない**（Python版はWorkerのtaskにも履歴をprependする）。
- 書き込みストリークインターロックに「読み取り専用委任完了でリセット」ロジックが無い。
- ✅**2026-08-27実装済み**: Specialistロールの禁止事項フィールドチェック —
  `MIMIC_ROLE_REQUIRE_FORBIDDEN=1`による2段階導入方式を配線（既定は警告のみ）。
- verify_cmd学習の3段階目（LLMによる自動提案、最大6ラウンド）が無く、学習済み/テンプレート
  どちらも無ければ無検証のまま進む。
- `continue_specialist`がPython版の明示的なresume_noteチェックポイント書き換えを行わない
  （会話継続自体は動くが技法が異なる）。

---

## グループE: 監視/設定/AutoGit/ベンチ（autogit.py, monitoring.py, proc_observer.py, config.py, mimic_bench.py）

### ⚪ パリティ確認済み
- AutoGit backup/checkpoint/squash/rollback/diff・ReactLog・KeyManagerのコア（acquire/
  report429/reportSuccess）・複数プロバイダモデルセレクター（ライブ疎通確認・レイテンシ表示
  含め全面的に忠実、Go版はレースコンディション対策まで独自追加）・.envのBOM処理・
  ベンチマーク集計（MCP/verify_cmd統計は元々スコープ外と明記済み）

### ✅ 2026-08-27実装済み
- **`get_system_cpu_percent()`/`get_system_mem_info()`** — `/proc/stat`・`/proc/meminfo`
  ベースの計測を実装し、TUIの■ SYSTEMステータスパネルへ2秒間隔で反映。
- **`.env`テンプレート自動生成** — `.env`が無い場合にテンプレートを書き出して
  案内するよう実装（`ErrEnvTemplateGenerated`番兵エラー経由）。

### 🔴 欠落
- KeyManagerの`status()`/`n_ready_keys()`/`wait_for_n_keys()`/`total_tokens_available()`が
  すべて欠落（`/status`表示のキー稼働状況の詳細化に使われるもの）。

### 🟡 部分実装
- CPU計測のjiffy/CLK_TCKがハードコード100（Python版は`getconf CLK_TCK`で実測）。
  x86 Linuxではほぼ影響なし、ARM等では誤差が出る。
- fd_count/thread_countのサンプリングがGo版に無い（現状どちらの`/stats`表示にも使われて
  いないため実害は低い）。
- 並列バッチ実行時のCPU/RSS計測がバッチ全体で1回のみ（呼び出し単位の分離計測ではない、
  Go側コメントで自己申告済みの近似）。

### 🟢 意図的な仕様変更
- TokenBucketのRPD（日次）上限が未移植（低頻度機能として明示的にスコープ外）。
- ProcessMonitorが任意PIDではなく自プロセスのみ対応（Python側も実際の呼び出しは自プロセス
  のみのため、実質的な差は無い）。

---

## グループF: TUI/コマンド/ビューア（app.py, commands.py, viewer.py, utils.py）

### ⚪ パリティ確認済み
- Chat/Files/Scratchpad/Logタブ構成・書き込み承認モーダル（30秒タイムアウト等）・
  `/status /clear /model /mode /cd /scratchpad /help /viewer /bench /mcp`各コマンド・
  ThinkAwareBuffer（タグ分割ロジック）・render_markdown/_render_inline・
  get_session_trace_text・OpenBrowser・prune_old_sessions・get/set_scratchpad
- **`/mode` `/model`コマンドは実装・配線とも正しく確認**（グループAが当初疑問視したが、
  グループFが独立に`commands.go`の`cmdMode`/`cmdModel`と`runSlashCommand`からの呼び出しを
  実際に追い、誤りでないことを確認）。

### 🔴 欠落
- ステータスパネルの`■ SYSTEM`（CPU/MEM）・ロール/プロファイル表示（グループEの欠落と対）。
- ファイルプレビューの正規表現検索（`/`検索バー、前後2行コンテキスト付きハイライト）。
- **委任apply承認・host-exec承認モーダルが無い**（書き込み承認モーダルのみ実装。
  グループDのapply承認ゲート欠落と対の欠落）。
- `/search` `/sessions`の「会話への注入」フロー — 検索結果一覧の表示のみで、選択して
  会話に読み込ませる機能が無い。
- 起動時デフォルトモードを`MIMIC_DEFAULT_MODE`環境変数で指定する仕組みが無い（Go版は
  常にinteractiveスタート。確認済み: 環境変数自体への参照がGo全体でゼロ件）。
- Ctrl+L（ログクリア）・PageUp/PageDown・Ctrl+Home/End のキーバインドが無い。
- 入力欄の動的高さ変更（複数行入力時に最大5行まで自動拡張）が無い。

### 🟡 部分実装
- ファイルツリーが実際のTreeウィジェットではなく事前スキャンしたフラットリスト
  （ディレクトリをEnterでcwd変更、Backspaceで親へ、という操作が無い）。
- ScratchpadタブがDirector自身の内容のみ表示し、サブエージェント（Worker）のスクラッチパッドを
  trace_id経由で紐付け表示しない。
- `/sessions`が一覧表示のみで、番号指定による詳細表示・あいまい一致解決が無い。
- `/delegations resume/discard`が未実装（Go側コメントで自己申告済み、正確な記述）。
- `/skills`に`reload`サブコマンドの明示的な分岐が無い。
- SessionビューアHTTPが親子委任のツリー表示・チームイベントバッジ・ブラウザ内スクラッチパッド
  履歴パネルを持たない。**Go側のコメントは「委任未実装のため対象外」としているが、委任は
  実際には実装済みのため、このコメントの理由付けは古くなっている** — ドキュメント修正推奨。
- `<think>`ブロックの表示が1行折りたたみ（Python版は`╭─ 💭 思考中`の複数行ボックス表示で
  中身も個別にMarkdownレンダリングされる）。
- PipelineTypewriterのバッファリング/`_should_flush`（コードフェンス未クローズ検知）ロジックが
  無い。ただしGo版のMarkdownレンダラーはログ全体を毎回再レンダリングするため実害は小さい。
- セッション終了時の`.md`サマリー保存（`save_session`）が無い（JSONLの継続書き込みは
  されているため、生ログは失われない）。

---

## 訂正された過去の誤検知（このレポートで判明）

1. 「MCPツールがGo版の対話TUIに配線されていない」— 誤り。`internal/tui/model.go:209`で
   `mcp.ConnectAll`が呼ばれている（呼び出し元の`main.go`だけを見て、`NewModel`内部を
   追わなかったための誤検知）。
2. 「`/mode`/`/model`コマンドが存在しない」— 誤り（グループA内での疑問止まりで最終報告には
   含まれなかったが、グループFが独立に実装・配線を確認）。
3. （過去セッション由来）「`<think>`タグの文字数バジェット強制が未実装」—
   Python版自体に該当コードが存在せず、そもそも対象外と判明済み。
4. （過去セッション由来）「Markdownのテーブル・リンク対応」— Python版`render_markdown`
   自体に実装が無く対象外と判明済み。

これらは全て「grepせずに欠落と判定した」ことが原因であり、今回の調査方式
（判定前にgrep必須・呼び出し先の関数定義まで追う）で再発を防止できた。
