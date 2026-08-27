# mimic_tui (Python) → mimic_go (Go) 移植ギャップレポート

初回調査日: 2026-08-25。同日から翌日にかけて5回の追実装・再調査を経て本版に至る。
2026-08-26時点で、既知だったギャップはすべて実装を試みた（詳細は末尾「実装できなかった／
検証が不十分な項目」を参照）。

凡例: 🔴 未実装（機能・影響大） / 🟡 部分実装・簡略化 / 🟢 意図的な仕様変更（問題なし） / ⚪ 実装済み・パリティあり

---

## 完了済み

以下はすべて実装・ビルド確認（多くは動作スモークテストも）済み。

**安全境界・委任信頼性（1回目バッチ）**
書き込み承認フロー＋TUI承認モーダル／Workerサンドボックス書き込み境界チェック／MCP承認ゲート／
委任apply時の排他ロック／overlay whiteoutによる削除反映／委任結果のAutoGitコミット／
Observation切り詰めtier分け／二段構えループブレーカー／grep_codebase正規表現化／
委任グローバル同時実行数セマフォ／Workerクラッシュリカバリ／孤立委任マニフェスト＋24時間警告／
Specialistロール定義永続化／verify_cmd学習＋言語別テンプレート

**コンテキスト管理・雑多な修正（2回目バッチ）**
.envのBOM処理／SIGTERM・SIGHUP／XML救済リトライ・空応答リトライ／stale observation無効化／
読み取り専用ツールの並列実行／ツール結果LRUキャッシュ／大容量出力ページング(read_tool_cache)／
Skill常時サマリー注入

**TUI・監視・会話圧縮（3回目バッチ）**
スラッシュコマンド12種／会話圧縮（当時は固定しきい値）／チャットログ簡易Markdownレンダリング／
run_bashのANSI端末制御シーケンス除去／CPU%/RSSバックグラウンドサンプリング／
expected_files想定外ファイル警告＋書き込み委任の空diff警告

**委任トレース・出力レンダリング（4回目バッチ）**
`get_delegation_trace`ツール（`MIMIC_TRACE_ID`/`MIMIC_SESSIONS_DIR`経由でWorkerが実プロジェクトの
セッションディレクトリへ直接書き込む方式）／`<think>`/`<thought>`タグのストリーミング検出・分離表示／
Markdownレンダリング拡張（斜体・番号リスト・水平線・見出しレベル別）／Viewerサーバーの
オンデマンド起動化（`/viewer`コマンド）

**残ギャップ全消化（5回目バッチ、2026-08-26）**
- ⚪ `/mcp reconnect <server>` — サーバー切断→再接続、Registry.Unregisterを新設して対応
- ⚪ `/scratchpad`コマンド — 現在のスクラッチパッド内容を表示
- ⚪ context_headerへの直近書き込み・委任履歴の自動注入（`internal/react/contextheader.go`、
  `internal/delegate/history.go`の委任履歴リングバッファ新設）
- ⚪ `_trim_messages_smart`（送信直前90%超トリム。`internal/react/trim.go`。compactionとは
  別軸の保護機構として実装、ブロック単位の間引きアルゴリズムも忠実移植）
- ⚪ 会話圧縮の動的しきい値化（`selector.SelectInteractively`が取得するモデルのcontext_lengthを
  `config.ProviderConfig.ContextLength`→`llm.Client.ContextLength()`経由で圧縮・トリム両方に反映）
- ⚪ run_bashのpty対応・sudo自動入力（`github.com/creack/pty`導入。sudoパスワードプロンプト検出時
  `SUDO_PASSWORD`環境変数の値を最大3回まで自動入力。成功/失敗/タイムアウトともスモークテスト確認済み）
- ⚪ `/model` `/mode`コマンドとモード概念（interactive/specialistの2モード。Specialistは
  write_file/run_bash/固定ロール委任等を除外したレジストリ＋専用system prompt。
  `Registry.Exclude`を新設。`/model`は名前直接指定のみ対応——後述の既知の制約参照）
- 🟡 browser_*系ツール（chromedpベース、6種すべて実装。**このサンドボックス環境にはChrome/
  Chromiumバイナリが無く、実際のブラウザ操作は検証できていない**。優雅な劣化
  （エラーメッセージを返すだけでクラッシュしない）は確認済み）

以下は当初「未実装」と誤認していたが、再調査で**既に実装済み**と判明したもの:
- 書き込みストリークインターロック／KeyManager RPMトークンバケット

以下は当初「未実装」と誤って指摘したが、**Python版自体に実装が無く対象外**と判明したもの:
- `<think>`タグ文字数バジェット強制／Markdownのテーブル・リンク対応

---

## 実装できなかった／検証が不十分な項目

- 🟡 **browser_*ツールの実機動作検証** — Chrome/Chromiumバイナリがこの環境に存在せず、
  `sudo apt-get install`もパスワード入力が必要なため実行できなかった。コードは実装・
  コンパイル確認済みで、Chrome未検出時の優雅なエラー返却も確認したが、実際のnavigate/
  click/screenshot等の動作は未検証。
- 🟡 **`/model`のライブ選択** — Python版は引数無し`/model`で対話的なライブセレクター
  （API疎通確認付き）を起動するが、Go版はBubble Tea実行中に別のブロッキングUIを
  起動する仕組みが無いため、モデル名の直接指定のみ対応（`/model <name>`）。
- 🟡 **specialistモードの既定値** — Python版はデフォルトでspecialistモード
  （`MIMIC_DEFAULT_MODE`）だが、Go版は既存の動作を変えないためinteractiveを既定とした
  （明示的な設計判断、`/mode specialist`で切替可能）。
- ⚪ **go.mod更新**: chromedp導入に伴いGoツールチェーン要件が`go 1.25.0`→`go 1.26`へ
  自動的に引き上げられた（`go get`が該当バージョンを自動ダウンロード・使用）。

---

## 総括

Python版mimic_tuiとの機能パリティは、実行環境の制約（Chrome未インストール）による
browser_*ツールの実機未検証、および対話的UIアーキテクチャの違いに起因する`/model`ライブ
選択の簡略化を除き、既知だったギャップをすべて実装した。安全境界・委任システムの信頼性・
コンテキスト管理・TUI操作性・出力レンダリングいずれも実装・ビルド確認・多くはスモーク
テストで動作確認済み。
