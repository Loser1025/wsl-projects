# mimic_linux → Textual TUI 移行 計画書

> **状態**: ドラフト（未着手）  
> **作成日**: 2026-07-01  
> **Python**: 3.14.4 / **Textual**: 8.2.7（既インストール）  
> **原則**: 既存コードを壊さず、段階的に移植する

---

## 1. スコープと制約

### やること
- `mimic_linux` のコピーを作成し、UI層を Textual TUI に置き換える
- コピー元 (`mimic_linux/`) は **一切変更しない**

### やらないこと
- コピー元のCUI版を変更・削除する
- Textualに入らない機能（ブラウザ自動化等）を無理にTUI化する

### 制約
- コピー元のPythonファイルは **読むだけ**（importして使う）
- 新規作成ファイルのみ書く
- 各フェーズ完了後に動作確認してから次に進む

---

## 2. ディレクトリ構造（完成形）

```
/home/loser/wsl-projects/
├── mimic_linux/              ← コピー元（変更禁止）
│   ├── __main__.py
│   ├── main.py
│   ├── agent.py
│   ├── orchestrator.py
│   ├── config.py
│   ├── tools.py
│   ├── tools_linux.py
│   ├── commands.py
│   ├── monitor.py
│   ├── tmux_orch.py
│   ├── monitoring.py
│   ├── autogit.py
│   ├── utils.py
│   ├── pipeline.py
│   ├── proc_observer.py
│   ├── mcp_server.py
│   ├── pyproject.toml
│   └── run.sh
│
└── mimic_linux_tui/          ← TUI版（新規作成）
    ├── __init__.py           ← 空ファイル（パッケージ化のため）
    ├── __main__.py           ← Textual エントリポイント（新規）
    ├── app.py                ← 【新規】Textual アプリ本体
    ├── pyproject.toml        ← textual 依存追加
    ├── run.sh                ← 起動スクリプト
    └── CLAUDE.md             ← アーキテクチャ概要
```

### 重要な設計判断

| 元のファイル | 扱い | 理由 |
|---|---|---|
| `agent.py` | コピー (`mimic_linux_tui/`) | UI非依存の中核ロジック。コピー後の修正は最小限 |
| `orchestrator.py` | コピー (`mimic_linux_tui/`) | 同上。出力先コールバックをTUI用に差し替え |
| `tools.py` | コピー (`mimic_linux_tui/`) | UI非依存。approval ハンドラの接続先だけ変更 |
| `tools_linux.py` | コピー (`mimic_linux_tui/`) | UI非依存 |
| `commands.py` | コピー+修正 (`mimic_linux_tui/`) | `sys.stdin` 依存部分をTUI向けに差し替え |
| `config.py` | コピー+修正 (`mimic_linux_tui/`) | `select_model_interactively_multi()` をTUI化 |
| `utils.py` | コピー+修正 (`mimic_linux_tui/`) | `safe_print` をTUI出力に繊維 |
| `autogit.py` | コピー (`mimic_linux_tui/`) | UI非依存 |
| `monitoring.py` | コピー (`mimic_linux_tui/`) | UI非依存 |
| `proc_observer.py` | コピー (`mimic_linux_tui/`) | UI非依存 |
| `pipeline.py` | コピー (`mimic_linux_tui/`) | UI非依存 |
| `monitor.py` | **削除** | tmux専用。TUI内で代替 |
| `tmux_orch.py` | **削除** | tmux専用。TUI内で代替 |
| `mcp_server.py` | コピー (`mimic_linux_tui/`) | UI非依存（MCPクライアント側が起動） |

---

## 3. フェーズ分割

各フェーズは **独立して動作確認可能** にし、問題があれば前のフェーズに戻れるようにする。

---

### Phase 0: プロジェクト準備

**目的**: 空の `mimic_linux_tui/` ディレクトリを作成し、依存関係を整える

**手順**:
1. `mimic_linux_tui/` ディレクトリを作成
2. UI非依存ファイル（`agent.py`, `tools.py` 等）を `cp` でコピー（内容は触らない）
3. `pyproject.toml` を新規作成（`textual>=8.0` を依存に追加）
4. `run.sh` を新規作成
5. `python -m mimic_linux_tui` でエラーなく起動することを確認（何も起きなくてOK）

**完了条件**:
```
$ cd mimic_linux_tui && ./run.sh
# ImportError や SyntaxError なく起動すること
```

---

### Phase 1: Textual アプリの骨格

**目的**: 最小限のTextualアプリを起動し、画面レイアウトを確認する

**新規作成ファイル**: `app.py`

**画面**:
```
┌──────────────────────────────────────────┐
│  Header: mimic_linux TUI                 │
├──────────────────────────────────────────┤
│  (空のチャット領域)                        │
│                                          │
│                                          │
├──────────────────────────────────────────┤
│  > _                                      │ ← Input
└──────────────────────────────────────────┘
```

**実装内容**:
- `MimicApp(App)` クラス
- Header（タイトル表示）
- ScrollableContainer（チャットログ）
- Input（プロンプト）
- `Ctrl+C`, `Ctrl+Q` で終了

**完了条件**: 画面が表示され、文字入力 → Enter → 入力が受け取れること

---

### Phase 2: エージェント接続（ダミー）

**目的**: 入力したテキストをそのままチャットに表示する（エージェント呼び出しはまだ行わない）

**実装内容**:
- Enter で入力をチャット領域に追加
- `/exit`, `/quit` でアプリ終了
- `/help` コマンドでコマンド一覧表示

**完了条件**:
- "Hello" 入力 → チャットに "Hello" 表示
- `/exit` → アプリ終了

---

### Phase 3: エージェント統合（ReActコール）

**目的**: 入力したプロンプトを `OpenRouterAgent` に渡し、結果をチャットに表示する

**修正ファイル**: `app.py`, `__main__.py`

**実装内容**:
- `__main__.py` で agent を初期化（コピー元の `main()` を簡略化）
- `app.py` の `on_input_submitted` で agent を呼び出し
- ツール呼び出し結果をチャットに表示
- `/mode interactive|plan` 切り替え
- Ctrl+C で中断

**完了条件**:
- "今日の日付は？" 入力 → 回答がチャットに表示される

---

### Phase 4: コマンド実装

**目的**: スラッシュコマンドをTextual TUIで動作させる

**修正ファイル**: `commands.py`（コピー側）, `app.py`

**実装内容**:
- `/status` → ステータスをチャットに表示
- `/model` → モデル選択ダイアログ表示（Phase 5）
- `/undo` → AutoGit rollback
- `/cd` → 作業ディレクトリ変更
- `/clear` → チャットクリア + 会話履歴リセット
- `/sessions` → セッション一覧表示
- `/stats` → ツール統計表示
- `/mode interactive|plan` → モード切替表示

**完了条件**: 全コマンドがTUI内で動作すること

---

### Phase 5: モーダルダイアログ

**目的**: 書き込み承認・モデル選択等をダイアログで行う

**修正ファイル**: `app.py`, `commands.py`

**ダイアログ一覧**:
| ダイアログ | トリガー | 操作 |
|---|---|---|
| `ApprovalDialog` | ファイル書き込み時 | Y/n キー |
| `ModelSelectDialog` | `/model` | ↑↓キー + Enter |
| `SessionDetailDialog` | `/sessions <番号>` | スクロール + qで閉じる |

**完了条件**: 書き込み承認ダイアログが表示され、Y → 実行 / n → キャンセル が動作

---

### Phase 6: Plan-and-Execute 表示

**目的**: プランモード時のステップ進捗をリアルタイム表示する

**修正ファイル**: `app.py`, `orchestrator.py`（コピー側）

**実装内容**:
- PlanStep のステータス変更をリアルタイム表示
- ステップ完了/失敗のアイコン切替
- 最終結果の表示

**完了条件**: プランモードでステップが逐次表示されること

---

### Phase 7: ステータスバー・UX改善

**目的**: CPU/メモリ表示、エラーハンドリング、キーバインド追加

**実装内容**:
- フッターステータスバー（CPU%, MEM%, ツール呼び出し数）
- エラー時のリトライ表示
- 読み取り専用モード（閲覧のみ）
- スクロール操作（PageUp/Down）

**完了条件**: ステータスバーがリアルタイム更新されること

---

### Phase 8: 最終調整・クリーンアップ

**目的**: 不要コードの削除、ドキュメント更新

**手順**:
1. `monitor.py` 削除（tmux専用）
2. `tmux_orch.py` 削除（tmux専用）
3. 未使用 import / 関数の整理
4. `CLAUDE.md` 更新
5. `pyproject.toml` 整理

---

## 4. フェーズ間の安全確認

各フェーズ完了時に以下を確認する:

- [ ] `python -m mimic_linux_tui --help` が動作する
- [ ] 通常起動で TUI 画面が表示される
- [ ] `Ctrl+C` または `/exit` で正常終了する
- [ ] 例外が発生してもクラッシュせず、エラー表示して復帰する
- [ ] コピー元 `mimic_linux/` のファイルが一切変更されていない

問題があれば、該当フェーズの修正前に `git commit`（初期状態への戻し）を行う。

---

## 5. リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| `agent.run()` が同期呼び出し（ブロッキング） | TUIの描画が止まる | `asyncio.to_thread()` or `worker_thread` で非同期化 |
| `sys.stdin` 依存のコードが残る | TUI上で入力ができない | Phase 4で完全に差し替え |
| Textualのバージョン差異 | APIが変わって動かない可能性 | 現在のバージョン (8.2.7) のAPIに合わせる |
| 大規模ファイルのコピーで差異が出る | バグの原因になる | コピー直後は `diff` で確認し、最小限の修正のみ |
| ReActループ中の途中切断 | 状態不整合 | Ctrl+C ハンドラで安全に中断 |

---

## 6. 確認事項（判断を要するもの）

1. **tmuxダッシュボード廃止の方針**: Phase 8 で `monitor.py` と `tmux_orch.py` を完全に削除しても問題ないか？
2. **同時起動の可能性**: CUI版とTUI版を同じホストで同時使用するか？（ポート競合等）
3. **MCP連携**: `mcp_server.py` のTUI版対応は必要か？
