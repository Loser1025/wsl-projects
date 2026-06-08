# 🦊 cli_agent_demo.py 詳細分析レポート

## 概要

`cli_agent_demo.py` は **Textual** フレームワークを用いて構築された、CLI（Command Line Interface）エージェントの **TUI（Text User Interface）デモアプリケーション** です。ターミナル上で動作するモダンなAIアシスタント風UIを実現しており、マルチエージェントのシミュレーション、リアルタイムログストリーミング、タスク管理、ファイルエクスプローラなどの機能を備えています。

---

## 1. プログラムの構造と主要なコンポーネント

### 1.1 全体構造（646行）

| セクション | 行範囲 | 内容 |
|---|---|---|
| モジュール docstring | 1–15 | 機能一覧の概要 |
| インポート | 17–47 | 標準ライブラリ + Textual 関連 |
| カスタムウィジェット | 53–97 | `AgentStatusBadge`, `TaskCounter`, `LogPanel` |
| メインアプリ | 100–638 | `CLI_Agent_App` クラス |
| エントリポイント | 643–645 | `if __name__ == "__main__"` |

### 1.2 カスタムウィジェット（3つ）

#### ① `AgentStatusBadge(Static)` — 行53〜75
- **役割**: エージェントのステータス（IDLE / WORKING / DONE / ERROR）とアクティブタスク数をリアルタイム表示
- **リアクティブプロパティ**: `status`, `active_tasks`
- **カラーマッピング**: IDLE→grey, WORKING→yellow, DONE→green, ERROR→red
- `watch_status()` / `watch_active_tasks()` で変更を監視し `refresh()` を呼び出す

#### ② `TaskCounter(Static)` — 行78〜85
- **役割**: 完了タスク数 / 全タスク数を表示（例: `✅ 3 / 5 tasks completed`）
- **リアクティブプロパティ**: `done`, `total`

#### ③ `LogPanel(RichLog)` — 行88〜97
- **役割**: システムログ表示用の `RichLog` サブクラス
- `border_subtitle = "SYSTEM LOG"` を設定

### 1.3 メインアプリケーション `CLI_Agent_App(App)` — 行100〜638

| 要素 | 詳細 |
|---|---|
| **TITLE / SUB_TITLE** | `"◉ OWL CLI Agent"` / `"Terminal AI Assistant"` |
| **CSS** | 106〜208行: ダークテーマのスタイル定義 |
| **BINDINGS** | 6つのキーバインド（q, t, r, s, c, ctrl+l） |
| **リアクティブ状態** | `agent_status`, `active_task_count`, `completed_tasks` |
| **デモメッセージ** | `_demo_messages`: 5つのプリセットメッセージ（thinking, tool, response） |

---

## 2. マルチエージェントの動作メカニズム

### 2.1 エージェントの定義

プログラム内では **3つのエージェント** がサイドバーに静的表示されています：

```
🦊 1. OWL Agent
⚡ 2. Fast Runner
🔍 3. Code Reviewer
```

> **注意**: 現在の実装ではこれらは表示のみで、実際に個別のエージェントが独立して動作するわけではありません。デモシミュレーションは単一エージェント（OWL Agent）として動作します。

### 2.2 エージェントの状態遷移

```
IDLE ──→ WORKING ──→ DONE
  ↑         │          │
  └─────────┴──────────┘
       (Reset / Stop)
```

- **IDLE**: 初期状態、タスク待機中
- **WORKING**: デモシミュレーション実行中
- **DONE**: 全タスク完了
- **ERROR**: エラー発生時（UI上は定義済みだが、デモ内では未使用）

### 2.3 デモシミュレーションの動作（`_run_agent_demo`）

`@work(exclusive=True, thread=False)` デコレータ付きの非同期メソッドで、以下のフローで動作します：

```
1. agent_status = "WORKING", active_task_count = 3
2. _demo_messages を順次処理:
   a. "thinking" → 斜体で思考プロセスを表示
   b. "tool" → ツール呼び出しをJSON形式で表示
   c. "response" → トークン単位でストリーミング表示 + Markdown更新
3. プログレスバー更新
4. DataTable の該当行を更新（Status, Progress列）
5. TaskCounter の done を更新
6. agent_status = "DONE", active_task_count = 0
7. 全タスク行を "✅ Done" / "100%" に更新
```

### 2.4 タスク管理

- **初期タスク**: 5件（T-001〜T-005）が `on_mount` でシード
- **新規タスク追加**: `action_simulate_task` でランダムなタスクを追加
- **タスク選択**: DataTable の行クリックで詳細をログに出力

---

## 3. TUIのインターフェースと機能

### 3.1 レイアウト構造

```
┌─────────────────────────────────────────────┐
│  Header (show_clock=True)                    │
├─────────────────────────────────────────────┤
│  Status Bar: [AgentStatusBadge] [TaskCounter]│
├──────────┬──────────────────────────────────┤
│ Sidebar  │  TabbedContent                    │
│          │  ┌────┬─────┬──────┬─────┬──────┐ │
│ 📁 AGENTS│  │Chat│Tasks│Files │Logs │Output│ │
│ 🦊 OWL   │  ├────┴─────┴──────┴─────┴──────┤ │
│ ⚡ Fast  │  │  Tab Content                  │ │
│ 🔍 Review│  │                               │ │
│          │  │                               │ │
│ ⚙️ ACTION│  │                               │ │
│ [Run All]│  │                               │ │
│ [Stop]   │  │                               │ │
│ [Reset]  │  │                               │ │
├──────────┴──────────────────────────────────┤
│  Overall Progress: [████████░░░░░░░░]        │
├─────────────────────────────────────────────┤
│  💬 Command: [________________________]      │
├─────────────────────────────────────────────┤
│  Footer (key bindings)                       │
└─────────────────────────────────────────────┘
```

### 3.2 タブ構成（5つ）

| タブ | ID | 内容 |
|---|---|---|
| 💬 Chat | `chat-tab` | RichLog: エージェントとの対話 |
| 📋 Tasks | `tasks-tab` | DataTable: タスク一覧（ID, Task, Status, Progress, Started） |
| 📂 Files | `files-tab` | Tree: ファイルエクスプローラ |
| 📜 Logs | `logs-tab` | RichLog: システムログ（タイムスタンプ付き） |
| 📄 Output | `output-tab` | Markdown: 最終的なAI応答の整形表示 |

### 3.3 キーバインド

| キー | アクション | 説明 |
|---|---|---|
| `q` | `quit` | アプリ終了 |
| `t` | `toggle_dark` | ダーク/ライト切替 |
| `r` | `run_demo` | デモシミュレーション実行 |
| `s` | `simulate_task` | 新規タスク追加 |
| `c` | `clear_chat` | チャットログクリア |
| `ctrl+l` | `clear_logs` | システムログクリア |

### 3.4 インタラクティブコマンド（入力欄）

| コマンド | 動作 |
|---|---|
| `help` | 利用可能なコマンド一覧を表示 |
| `status` | 現在のエージェント状態を表示 |
| `tasks` | タスク数を表示 |
| `clear` / `cls` | チャットをクリア |
| `demo` | デモシミュレーションを実行 |
| `exit` / `quit` | アプリを終了 |
| その他 | エコー表示（デモ用） |

### 3.5 ボタン操作

- **▶ Run All** (`#run-all-btn`): デモシミュレーションを開始
- **⏹ Stop** (`#stop-btn`): エージェントをIDLEに戻す
- **🔄 Reset** (`#reset-btn`): 全状態を初期化

### 3.6 ファイルツリー

```
📁 root (/home/loser/wsl-projects)
├── 📁 src
│   ├── 📄 app.py
│   ├── 📄 utils.py
│   └── 📄 config.yaml
├── 📁 tests
│   ├── 📄 test_app.py
│   └── 📄 test_utils.py
├── 📄 README.md
├── 📄 LICENSE
└── 📄 .gitignore
```

---

## 4. プログラムの実行フロー

### 4.1 起動フロー

```
1. CLI_Agent_App().run()
2. compose() でUI構築
   ├── Header
   ├── Status Bar (AgentStatusBadge + TaskCounter)
   ├── Main Body
   │   ├── Sidebar (エージェント一覧 + アクションボタン)
   │   └── Right Panel (TabbedContent: 5タブ)
   ├── Progress Bar
   ├── Input Area
   └── Footer
3. on_mount() で初期化
   ├── システムログ出力
   ├── DataTable に5件のシードタスク追加
   ├── File Tree 構築
   ├── TaskCounter 初期値設定
   └── ウェルカムメッセージ表示
```

### 4.2 デモシミュレーションフロー

```
ユーザー操作 (rキー / "demo"コマンド / Run Allボタン)
  ↓
run_demo_simulation()
  ↓
_run_agent_demo()  [@work 非同期開始]
  ↓
agent_status = "WORKING"
active_task_count = 3
  ↓
_demo_messages をループ:
  ├─ thinking → チャットに斜体表示
  ├─ tool → チャットにJSON表示
  └─ response → トークン単位ストリーミング + Markdown更新
  ↓
progress_bar 更新
DataTable 行更新
TaskCounter 更新
  ↓
agent_status = "DONE"
全タスク → "✅ Done" / "100%"
完了メッセージ表示
```

### 4.3 リアクティブ更新フロー

```
agent_status 変更
  ↓
watch_agent_status() 発火
  ↓
AgentStatusBadge.status 更新 → バッジ再描画
システムログ出力

active_task_count 変更
  ↓
watch_active_task_count() 発火
  ↓
AgentStatusBadge.active_tasks 更新 → バッジ再描画
```

---

## 5. 可能な改善点や拡張機能

### 5.1 アーキテクチャ面

| 改善点 | 説明 |
|---|---|
| **実際のLLM連携** | 現在はプリセットメッセージの再生。OpenAI/Anthropic等のAPIと接続し、実際のAI応答をストリーミングする |
| **真のマルチエージェント化** | 3つのエージェントを実際に独立したワーカーとして実装し、タスクを分散処理する |
| **プラグインシステム** | ツール呼び出しをプラグイン形式で拡張可能にする（`file_search`, `run_tests` 等） |
| **状態永続化** | タスク状態やチャット履歴をSQLite等で保存し、再起動時に復元する |
| **設定ファイル** | エージェント設定、APIキー、テーマ等をYAML/JSONで外部設定化する |

### 5.2 UI/UX面

| 改善点 | 説明 |
|---|---|
| **通知システム** | タスク完了時にデスクトップ通知を送信する |
| **検索機能** | チャットログ・システムログに検索フィルタを追加する |
| **タスク詳細パネル** | 選択したタスクの詳細（ログ、出力等）を表示するパネルを追加する |
| **ダーク/ライトテーマ切替** | `t` キーの切替を実際に機能させる（現在はTextual標準の `action_toggle_dark` を呼んでいるが、CSSが固定） |
| **レスポンシブ対応** | ターミナルサイズ変更時のレイアウト最適化 |
| **タブの動的追加** | エージェントごとにチャットタブを動的に生成する |

### 5.3 機能面

| 改善点 | 説明 |
|---|---|
| **タスクの並列実行** | `asyncio.gather()` で複数タスクを並列処理する |
| **タスクの優先度付け** | 優先度列を追加し、ソート・フィルタを可能にする |
| **エラーハンドリング強化** | タスク失敗時のリトライ機構、エラーログの詳細化 |
| **履歴管理** | 過去のセッション履歴を閲覧・再開できる機能 |
| **エクスポート機能** | チャットログやタスク一覧をCSV/Markdownでエクスポートする |
| **MCP連携** | Model Context Protocol (MCP) サーバーとの連携でツールを拡張する |

### 5.4 コード品質面

| 改善点 | 説明 |
|---|---|
| **型ヒントの強化** | `Message` クラスが未定義（`from textual.message import Message` はインポートされているがクラス未使用）。カスタムメッセージ型を定義する |
| **テスト追加** | pytest + Textual のテストユニットで自動テストを構築する |
| **ログレベルの外部化** | `log_system` のレベル定義を enum 化する |
| **定数の抽出** | マジックナンバー（`0.15`, `0.005`, `35` 等）を定数として抽出する |
| **国際化 (i18n)** | 日本語・英語等の多言語対応 |

---

## 6. 技術スタック

| 技術 | 用途 |
|---|---|
| **Python 3.11+** | 型ヒント、async/await |
| **Textual** | TUIフレームワーク（Richベース） |
| **asyncio** | 非同期処理（デモシミュレーション） |
| **Rich** | リッチテキスト表示（Textual経由） |

---

## 7. まとめ

`cli_agent_demo.py` は、Textual フレームワークの機能をフルに活用した見事なTUIデモアプリケーションです。**リアクティブシステム**による状態管理、**非同期バックグラウンドワーカー**によるストリーミング表示、**CSS ベースのスタイリング**など、モダンなTUI開発のベストプラクティスが凝縮されています。

現在の実装はデモ用途に留まりますが、アーキテクチャは十分に拡張可能であり、実際のLLM API連携や真のマルチエージェント化を施すことで、実用的なCLI AIアシスタントへと発展させることができます。