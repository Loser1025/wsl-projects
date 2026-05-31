# mimic_linux → Textual TUI 移行 計画書

> **状態**: 実装待ち  
> **Python**: 3.14 / **Textual**: インストール済み  
> **原則**: `mimic_linux/` は一切変更しない。バックエンドはそのまま流用する。

---

## 1. なぜ CUI に描画バグが多いか

コードを読んで確認した根本原因:

| 原因 | 場所 | 詳細 |
|---|---|---|
| スレッド競合 | `PipelineTypewriter._run()` | 500文字/秒で1文字ずつ stdout に書きながら、別スレッドの `safe_print` が割り込む |
| readline との競合 | `main.py:_rl()` | ANSI コードを `\001...\002` で囲む処理と tmux 描画の干渉 |
| stdin ブロック中の stdout 出力 | `_react_approval_handler` | タイムアウト待ちスレッド中に他スレッドが出力する |
| tmux ペイン更新と stdout の競合 | `monitor.py` | `tmux send-keys` 経由の描画が端末状態を破壊 |

TUI に移行することで全てのスレッドが Textual のイベントループ経由でウィジェットを更新するため、これらの競合が解消される。

---

## 2. ファイル対応表（完成形）

| 元ファイル (`mimic_linux/`) | TUI版の扱い | 変更内容 |
|---|---|---|
| `agent.py` | **コピー** | 変更なし（UI非依存） |
| `orchestrator.py` | **コピー** | 変更なし（callback は外から注入） |
| `tools.py` | **コピー** | 変更なし |
| `tools_linux.py` | **コピー** | 変更なし |
| `pipeline.py` | **コピー** | 変更なし |
| `autogit.py` | **コピー** | 変更なし |
| `monitoring.py` | **コピー** | 変更なし |
| `proc_observer.py` | **コピー** | 変更なし |
| `mcp_server.py` | **コピー** | 変更なし |
| `config.py` | **コピー+修正** | `select_model_interactively_multi` のTUI化 |
| `commands.py` | **コピー+修正** | `sys.stdin.readline()` 依存をTUI向けに差し替え |
| `utils.py` | **コピー+修正** | `safe_print` にTUIコールバック追加、`PipelineTypewriter` にTUI出力モード追加 |
| `main.py` | **コピー+修正** | `interactive_loop` を削除。`pipe_mode`/`auto_mode` はそのまま保持 |
| `__main__.py` | **新規** | readline を削除し Textual App を起動 |
| `app.py` | **新規** | Textual アプリ本体 |
| `monitor.py` | **削除** | tmux 専用。TUI が代替 |
| `tmux_orch.py` | **削除** | tmux 専用。TUI が代替 |
| `pyproject.toml` | **修正** | `textual` 依存を追加 |
| `run.sh` | **修正** | パッケージ名を `mimic_linux_tui` に変更 |

---

## 3. コアアーキテクチャ設計

### 3-1. `safe_print` のリダイレクト（最重要）

`safe_print` は `agent.py`, `orchestrator.py`, `commands.py`, `tools.py` など全ファイルで使われている。
これを `utils.py` の `safe_print` にコールバック差し込み口を追加することで、**他のファイルを一切変えずに**出力先を TUI ウィジェットに切り替える。

```python
# utils.py に追加する差分

_tui_callback: Optional[Callable[[str], None]] = None

def set_tui_output(fn: Optional[Callable[[str], None]]) -> None:
    global _tui_callback
    _tui_callback = fn

def safe_print(*args, **kwargs):
    text = " ".join(str(a) for a in args)
    end = kwargs.get("end", "\n")
    flush = kwargs.get("flush", False)
    if _tui_callback is not None:
        # TUI モード: ウィジェットに送る（end を加味）
        full = text if not end or text.endswith(end) else text + end
        _tui_callback(full)
    else:
        # CLI フォールバック
        with _print_lock:
            print(*args, **kwargs)
```

### 3-2. `PipelineTypewriter` のTUI対応

現在の実装: `_run()` スレッドが 500文字/秒で stdout に書く（これが主な描画バグ源）。

TUI版: `feed()` で受け取ったチャンクをそのまま `set_tui_output` のコールバックに渡す。
タイプライター演出は不要（Textual の `RichLog` が Rich 形式でスムーズに表示する）。

```python
# utils.py の PipelineTypewriter に TUI モードを追加

class PipelineTypewriter:
    def __init__(self, auto_mode=False, renderer=None, tui_mode=False):
        self._tui_mode = tui_mode  # TUI時はTrue
        # 既存の初期化 ...

    def start(self):
        if self._auto_mode or self._tui_mode:
            return  # スレッド不要
        # 既存のスレッド起動 ...

    def feed(self, chunk: str):
        if not chunk:
            return
        self._full.append(chunk)
        if self._auto_mode or self._tui_mode:
            # TUI: ANSI付きテキストをそのまま tui_callback へ
            if _tui_callback is not None:
                _tui_callback(chunk)
            else:
                sys.stdout.write(chunk); sys.stdout.flush()
            return
        # 既存の ThinkAwareBuffer/disp_q 処理 ...
```

`InteractiveOrchestrator.run_react()` が呼ぶ `PipelineTypewriter(auto_mode=...)` を
`PipelineTypewriter(tui_mode=True)` に差し替えるのは `app.py` 側でモンキーパッチするか、
`__main__.py` の初期化時に `set_tui_mode(True)` フラグを立てる。

### 3-3. エージェント呼び出しのスレッド化

現在: `interactive_loop` の `while True:` の中で直接 `interactive_orch.run_react()` を呼ぶ（ブロッキング）。

TUI版: Textual の `@work(thread=True)` でバックグラウンドスレッドに移す。
スレッドから UI の更新は `app.call_from_thread()` を使う。

```python
# app.py の中核

class MimicApp(App):

    @work(thread=True)
    def _run_agent(self, user_input: str) -> None:
        """バックグラウンドスレッドでエージェントを実行する。"""
        # safe_print → self._on_output() が自動的に呼ばれる
        self.interactive_orch.run_react(user_input)
        # 完了後に入力欄を再有効化
        self.call_from_thread(self._on_agent_done)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        event.input.disabled = True  # 実行中は入力を受け付けない
        self._run_agent(text)
```

### 3-4. 書き込み承認ダイアログ

現在: `main.py:_react_approval_handler()` が `sys.stdin.readline()` をタイムアウト付きスレッドで待つ。

TUI版: `ModalScreen` を表示し、`threading.Event` でエージェントスレッドをブロック。

```python
# app.py

class WriteApprovalModal(ModalScreen[bool]):
    """ファイル書き込み確認ダイアログ (Y/n)"""
    def __init__(self, tool_name, path, preview):
        super().__init__()
        self._tool_name = tool_name
        self._path = path
        self._preview = preview

    def compose(self) -> ComposeResult:
        yield Static(f"書き込み確認\nツール: {self._tool_name}\nファイル: {self._path}")
        yield Static(self._preview[:500])
        yield Button("承認 [Y]", id="yes", variant="success")
        yield Button("拒否 [n]", id="no",  variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


def _make_tui_approval_handler(app: "MimicApp"):
    """エージェントスレッドから呼ばれる承認ハンドラを生成する。"""
    def handler(tool_name, args, preview) -> bool:
        result = [False]
        ev = threading.Event()
        async def _push():
            result[0] = await app.push_screen_wait(
                WriteApprovalModal(tool_name, args.get("path","?"), preview)
            )
            ev.set()
        app.call_from_thread(lambda: asyncio.run_coroutine_threadsafe(
            _push(), app._loop
        ))
        ev.wait(timeout=30)
        return result[0]
    return handler
```

### 3-5. モデル選択ダイアログ

現在: `config.py:select_model_interactively_multi()` が `input()` でモデルを選ぶ。

TUI版: `app.py` に `ModelSelectScreen(ModalScreen)` を定義し、`/model` コマンドで `push_screen_wait()` を呼ぶ。
`commands.py` の `cmd_model` は、TUI版では `app.py` でオーバーライドして Modal を開く。

---

## 4. 画面レイアウト

```
┌─ Header: MIMIC TUI ─ gemini-2.0-flash ─ /home/user ───────┐
│                                                             │
│  ┌─ ChatLog (RichLog, スクロール可) ─────────────────────┐ │
│  │  [AutoGit] バックアップ完了                            │ │
│  │  ─────────────────────────────────────────────────    │ │
│  │  ❯ ファイルを一覧してください                         │ │
│  │                                                        │ │
│  │  ╭─ 💭 思考中 ─────────────────────────────────────  │ │
│  │  │ ファイル一覧を確認します...                        │ │
│  │  ╰────────────────────────────────────────────────    │ │
│  │                                                        │ │
│  │  ⚙ list_directory(path='/home/user')                  │ │
│  │  👁 app.py, agent.py, utils.py ...                    │ │
│  │                                                        │ │
│  │  以下のファイルがあります:                             │ │
│  │  • app.py                                              │ │
│  │  • agent.py                                            │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌─ Input ──────────────────────────────────────────────┐  │
│  │  ⚡ ❯ _                                               │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─ Footer: [Ctrl+Q] 終了  [/mode] モード  [/help] ヘルプ ────┘
```

---

## 5. フェーズ分割

各フェーズは単独で動作確認してから次へ進む。

---

### Phase 0: ディレクトリ準備

**手順**:
1. `cp -r mimic_linux mimic_linux_tui`
2. `mimic_linux_tui/monitor.py` と `tmux_orch.py` を削除
3. `pyproject.toml` を編集してパッケージ名を `mimic_linux_tui` に、`textual>=0.70` 依存を追加
4. `run.sh` を編集してモジュール名を変更
5. `pip install -e .` で依存をインストール

**完了確認**: `python -m mimic_linux_tui --status` でエラーなく起動する

---

### Phase 1: `utils.py` 改修（safe_print ブリッジ）

**変更内容**:
- `_tui_callback` グローバル変数と `set_tui_output()` 関数を追加
- `safe_print()` に TUI コールバック分岐を追加
- `PipelineTypewriter` に `tui_mode` パラメータを追加

**完了確認**: `set_tui_output(print)` を設定しても従来と同じ動作をすること

---

### Phase 2: `app.py` 骨格作成

**実装**:
- `MimicApp(App)` クラス
- `Header`, `RichLog`, `Input`, `Footer` ウィジェット
- `on_mount()` で `set_tui_output()` に RichLog への書き込み関数を設定
- `on_input_submitted()` でテキストを受け取り RichLog に表示（エージェントはまだ繋がない）
- `Ctrl+C` / `Ctrl+Q` / `/exit` / `/quit` で終了

**完了確認**: 画面が表示され、文字を入力して Enter するとログに追記される

---

### Phase 3: `__main__.py` 作成

**実装**:
- `readline` 関連を全て削除
- `agent`, `orchestrator`, `interactive_orch`, `auto_git` を初期化（既存コードをそのまま移植）
- `--prompt` / `--auto-prompt` / `--status` モードの分岐はそのまま保持
- 通常起動では `MimicApp` を生成して起動

**完了確認**: `python -m mimic_linux_tui` でTUI画面が起動する

---

### Phase 4: エージェント統合

**実装**:
- `app.py` の `on_input_submitted()` で `@work(thread=True)` によりエージェントを非同期呼び出し
- `PipelineTypewriter(tui_mode=True)` を使うよう `InteractiveOrchestrator` の生成時に注入
  （`InteractiveOrchestrator` 自体は変えず、`run_react` が内部で作る `PipelineTypewriter` を差し替える）
- エージェント実行中は Input を `disabled=True`、完了後に `disabled=False` & フォーカス復帰
- Ctrl+C でエージェントスレッドに `KeyboardInterrupt` を送る

**`PipelineTypewriter` の差し替え方法**:  
`orchestrator.py` の `_run_react_inner()` が `PipelineTypewriter(auto_mode=...)` を直接生成している。
`utils.py` に `_tui_mode_global = False` フラグを持たせ、`PipelineTypewriter.__init__()` でそれを参照する。
`app.py` の `on_mount` で `utils.set_tui_mode(True)` を呼ぶだけでよい。

**完了確認**: プロンプトを入力するとエージェントが動き、ツール呼び出しと応答がログに表示される

---

### Phase 5: 書き込み承認ダイアログ

**実装**:
- `app.py` に `WriteApprovalModal(ModalScreen[bool])` を定義
- `_make_tui_approval_handler(app)` を `app.py` に実装
- `app.on_mount()` で `set_write_approval_handler(handler)` を呼ぶ

**完了確認**: ファイル書き込みが必要な操作で確認ダイアログが表示され、Y/n が機能する

---

### Phase 6: スラッシュコマンド

**実装**:
- `on_input_submitted()` で `/` 始まりの入力を `cmd_registry.route()` に渡す
- `cmd_search` の `sys.stdin.readline()` 部分を `app.py` の `SearchInjectModal` に置き換え
- `/model` は `ModelSelectModal` を開く
- `/sessions` は `SessionListModal` を開く
- `/mode`, `/status`, `/clear`, `/cd`, `/undo`, `/stats`, `/help`, `/scratchpad` はそのまま動く（`safe_print` 経由でログに出力）

**stdin 依存の差し替え一覧**:

| コマンド | 場所 | 現在 | TUI版 |
|---|---|---|---|
| 書き込み承認 | `main.py` | `sys.stdin.readline()` | `WriteApprovalModal` |
| `/search` 注入確認 | `commands.py` | `sys.stdin.readline()` | `SearchInjectModal` |
| `/model` 選択 | `commands.py` | `select_model_interactively_multi()` = `input()` | `ModelSelectModal` |

**完了確認**: 全スラッシュコマンドがTUI内で正常動作する

---

### Phase 7: Plan-and-Execute 表示

**実装**:
- `orchestrator.py` の `run_with_plan()` が受け取る `on_plan`, `on_step`, `on_token` コールバックを活用
- `app.py` にプランステップを表示するウィジェット（`DataTable` または `RichLog` への追記）を実装
- ステップ状態（pending/running/done/failed）をリアルタイム更新

**完了確認**: `/mode plan` でプランが表示され、ステップが逐次完了マークされる

---

### Phase 8: UX 改善・クリーンアップ

**実装**:
- フッターにステータス表示（モード、モデル名、ツール呼び出し数）
- `proc_observer.SystemMonitor` でCPU/MEM をフッターに表示（オプション）
- エラー時にフッターに赤字で短く表示
- `CLAUDE.md` を TUI版の構成に更新

---

## 6. 主要リスクと対策

| リスク | 詳細 | 対策 |
|---|---|---|
| `PipelineTypewriter` の差し替え | `orchestrator.py` の深い場所で直接 `new PipelineTypewriter()` している | `utils.py` にグローバルフラグを持たせ、コンストラクタ内で自動的に `tui_mode=True` にする |
| `call_from_thread()` と `asyncio` の混在 | Textual のイベントループとスレッドの境界が複雑 | 承認ダイアログは `threading.Event` でブロックし、UI更新のみ `call_from_thread()` に限定する |
| `stdin` 依存の抜け漏れ | `grep -r "sys.stdin\|readline\|input(" mimic_linux_tui/` で確認 | Phase 6 完了後に全 `stdin` 参照をゼロにする |
| `safe_print` の `end=""` / `flush=True` | `safe_print(C.purple(t), end="", flush=True)` がストリーミング出力に多用される | TUI コールバックでは `end` を無視し、チャンクをそのまま RichLog に `write()` |
| ANSI コードの表示 | `C` クラスが生成する ANSI コードを RichLog で表示する必要がある | `Text.from_ansi(text)` を使って Rich Text に変換してから `log.write()` に渡す |

---

## 7. 確認コマンド一覧

```bash
# Phase 0 完了確認
python -m mimic_linux_tui --status

# stdin 依存チェック（Phase 6 後にゼロになること）
grep -rn "sys.stdin\|input(" mimic_linux_tui/ --include="*.py" | grep -v "# "

# オリジナル未変更確認
git diff mimic_linux/

# TUI起動
python -m mimic_linux_tui
```

---

## 8. 実装しない事項

- `monitor.py` / `tmux_orch.py` の移植（tmux専用のため廃止）
- `--tmux` 起動モード（TUI自体がダッシュボードを内包するため不要）
- CUI の `PipelineTypewriter` のタイプライター演出（Textual のスクロールで代替）
