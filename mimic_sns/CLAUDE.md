# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このディレクトリについて

`mimic_tui` をベースにしたSNS運用特化エージェントです(`cp -r`によるコピー由来)。
元の `mimic_tui` は変更していません。このディレクトリで開発してください。
パッケージ名は `mimic_sns`、コンソールスクリプトは `mimic-sns`(元の `mimic` コマンドと衝突しないよう変更)。

## ローカルMCPサーバー（mcp_server/）

`mcp_server/` は `mimic_sns` 本体とは独立したMCPエンドポイント。Instagram/Threadsツールを
MCP経由で呼べるようにするためのもので、`tools_sns.py`/`tools_threads.py`のロジックを
`sns_logic.py`に移植し、`api/mcp.py`（`BaseHTTPRequestHandler`）でJSON-RPC 2.0として公開
している。

**運用方針**: 以前はVercelにサーバーレス関数としてデプロイしていたが、
（`@vercel/python`ビルダーが毎回`uv`をpipでインストールしようとしシステムPythonの
externally-managed-environment保護に阻まれて`vercel dev`がローカルで動かない、トークン
失効時の`vercel env`更新・再デプロイの手間が大きい等の理由から）Vercelデプロイは廃止し、
**ローカル運用のみ**に切り替えた。Vercelプロジェクト（旧URL: `mcpserver-drab.vercel.app`）
は削除済み。

`api/mcp.py`の`handler`は標準ライブラリのみに依存する`BaseHTTPRequestHandler`なので、
Vercelのビルダーを介さず`local_run.py`から直接`http.server.ThreadingHTTPServer`で起動できる。

### 起動方法

```bash
cd mimic_sns/mcp_server
python3 local_run.py [port]   # デフォルト 8787、.env を自動読み込み
# → http://localhost:8787/api/mcp
```

### 接続情報

- ローカルURL: `http://localhost:8787/api/mcp`（ポートは起動時引数で変更可）
- 認証: `Authorization: Bearer <MCP_AUTH_TOKEN>` ヘッダー、または `?token=<MCP_AUTH_TOKEN>`
  クエリパラメータのいずれかが必須（ヘッダー優先）。トークンは `mcp_server/.env` に保存
  （`.gitignore`で除外済み、Gitにはコミットされない）。

### 疎通確認コマンド

```bash
# tools/list
curl -X POST http://localhost:8787/api/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# tools/call（例: Threadsアカウント概要取得）
curl -X POST http://localhost:8787/api/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_threads_account_summary","arguments":{}}}'
```

### 利用可能なツール（10個）

Instagram:
- `get_instagram_account_summary` — IGアカウント概要
- `get_instagram_recent_posts` — IG直近投稿一覧
- `get_instagram_insights` — IG投稿インサイト
- `post_to_instagram` — IG投稿実行（成功時、theme/strategy/hashtags指定の有無に関わらず
  SQLiteへ自動記録。`save_post_record`を別途呼ぶ必要なし）
- `save_post_record` — IG投稿記録の手動保存（下書き記録用、`status='draft'`）
- `load_past_posts` — IG過去投稿取得（`mcp_server/data/sns_posts.db`）

Threads:
- `get_threads_account_summary` — Threadsアカウント概要
- `get_threads_recent_posts` — Threads直近投稿一覧
- `get_threads_insights` — Threads投稿インサイト
- `post_to_threads` — Threads投稿実行（成功時、strategy指定の有無に関わらずSQLiteへ自動記録）

### データ保存先

`mcp_server/data/sns_posts.db`（`.gitignore`で除外済み）。以前はVercelの`/tmp`（実行ごとに
揮発する一時領域）に置いていたが、ローカル常駐プロセスに切り替えたタイミングで永続パスに
変更した。サーバー再起動・PC再起動を挟んでもデータは保持される。

### トークンのローテーション

`INSTAGRAM_ACCESS_TOKEN`/`INSTAGRAM_ACCOUNT_ID`/`THREADS_ACCESS_TOKEN`/`THREADS_USER_ID`/
`MCP_AUTH_TOKEN`はすべて`mcp_server/.env`に保存。値を更新したらサーバーを再起動するだけで
反映される（`local_run.py`は起動時に`.env`を読み込む）。

```bash
# サーバー再起動（既存プロセスをCtrl+Cまたはkillしてから）
cd mimic_sns/mcp_server
python3 local_run.py
```

**トークン自動更新（任意）**: `.env`に`APP_SECRET`（Meta App Secret）を設定すると、各
Instagram/Threadsツール呼び出しの冒頭で（プロセス内キャッシュにより1時間に1回まで）
`debug_token`で残り有効期限を確認し、7日を切っていたら`fb_exchange_token`/
`th_exchange_token`で自動的に60日トークンへ交換し、新しいトークンを`.env`にも書き戻す
（`sns_logic.py`の`_maybe_refresh_instagram_token`/`_maybe_refresh_threads_token`）。
`APP_SECRET`未設定の場合は何もせず黙ってスキップし、従来通り手動ローテーションが必要。

## SNS特化の追加ファイル

- `sns_data.py` — SQLite CRUD(投稿記録・インサイト保存)。標準ライブラリのみ。`data/sns_posts.db`
  に保存し、import時に`init_db()`を自動実行してテーブルを保証する(`.gitignore`で`data/`を除外)。
- `tools_sns.py` — Instagram Graph API ツール群(`get_instagram_insights` /
  `get_account_recent_posts` / `post_to_instagram` / `save_post_record` / `load_past_posts`)。
  `@tools.register()`で既存の`tools`レジストリに登録される。`tools.py`の末尾(`tools_linux`/
  `pipeline`と同じ場所)から`from . import tools_sns`でimportされるため、`__main__.py`は
  無変更でも対話・pipe・auto-prompt・Workerの全モードで自動的に登録される。
  `INSTAGRAM_ACCESS_TOKEN`/`INSTAGRAM_ACCOUNT_ID`未設定時は例外を投げず、各ツールが
  `"...が未設定です"`という文字列を返す。
- `tools_threads.py` — Threads API ツール群(`get_threads_account_summary` /
  `get_threads_recent_posts` / `get_threads_insights` / `post_to_threads` /
  `save_threads_record`)。`tools_sns.py`と同じパターンで`@tools.register()`登録、`tools.py`末尾
  (`tools_sns`の直後)から`from . import tools_threads`でimportされる。
  `THREADS_ACCESS_TOKEN`/`THREADS_USER_ID`未設定時も例外を投げず文字列でエラーを返す。

## 環境変数(.envに設定)

- `INSTAGRAM_ACCESS_TOKEN` — Instagram Graph API アクセストークン
- `INSTAGRAM_ACCOUNT_ID` — InstagramビジネスアカウントID
- `THREADS_ACCESS_TOKEN` — Threads API アクセストークン
- `THREADS_USER_ID` — Threads ユーザーID
- `GEMINI_KEY_1` — Gemini API キー(無料枠 1500 req/日、15 RPM。`RPM_LIMIT=15`と合わせて設定)

## Threads追加ツール(tools_threads.py)

- `get_threads_account_summary` — Threadsアカウント概要(id, username, threads_profile_picture_url, threads_biography)
- `get_threads_recent_posts` — 直近投稿一覧(id, text, timestamp, like_count)
- `get_threads_insights` — 投稿インサイト取得(views, likes, replies, reposts, quotes)
- `post_to_threads` — Threads投稿実行(テキスト・画像対応、コンテナ作成→公開の2ステップ)
- `save_threads_record` — 投稿記録をSQLiteの`threads_posts`テーブルに保存

### 典型的な使い方(Threads)

```bash
mimic-sns --auto-prompt "Threadsの直近20投稿を分析して、今日の投稿戦略ブリーフィングシートを出力して"
```

```bash
mimic-sns --auto-prompt "
戦略: [戦略メモをここに貼る]
以下のテキストでThreadsに投稿して：[テキスト内容]
投稿前に確認を求めること"
```

## 典型的な使い方(ハイブリッド運用)

### ① 分析フェーズ(mimic_snsが自動実行)
```bash
mimic-sns --auto-prompt "直近20投稿を分析して、今日の戦略立案用ブリーフィングシートを出力して"
```

### ② 戦略決定(人間がClaudeに手動で投げる)
ブリーフィングシートをClaudeに貼って戦略を決定する。

### ③ 画像生成(人間が手動で実施)
Canva / Adobe Firefly / Gemini AI Studio などで画像を生成する。

### ④ 投稿フェーズ(mimic_snsが自動実行)
```bash
mimic-sns --auto-prompt "
戦略: [Claudeの出力をここに貼る]
画像パス: ./assets/today.png
この内容でキャプションとハッシュタグを生成して、確認後に投稿して
"
```

## What this is

`mimic_tui` is a Python/Textual TUI for a self-contained ReAct coding agent ("mimic"). It talks
directly to OpenRouter / Google AI Studio (Gemini) / Mistral chat-completions APIs over raw
`urllib` (no SDKs), runs an agentic tool-call loop, and can spin up sandboxed sub-agents of itself.

## Running

```bash
python -m mimic_tui                       # interactive TUI (prompts for model selection)
python -m mimic_tui --prompt "..."        # one-shot pipe mode, prints final answer to stdout
python -m mimic_tui --auto-prompt "..."   # autonomous mode, no approvals/intervention (used by sub-agents / MCP)
python -m mimic_tui --status              # print active provider/model/key count and exit
```

Installed as a console script `mimic` via `pyproject.toml` (`mimic_tui.__main__:main`).
Requires Python >= 3.10. Dependencies: `watchdog`, `textual` (+ `rich`, optional `playwright` for
browser tools — degrades gracefully if not installed).

Configuration lives in `.env` (gitignored) at the package root: API keys for up to 3 providers
(`OPENROUTER_KEY_*`, `GEMINI_KEY_*`, `MISTRAL_KEY_*`), model selection, RPM limits, `MAX_TOKENS`,
`SYSTEM_PROMPT`, `ENABLE_CONFIDENCE_CHECK`, `GEMINI_THINKING_LEVEL`
(`none`/`minimal`/`low`/`medium`/`high`, mapped to `reasoning_effort` in the OpenAI-compatible
payload — see `GoogleAIConfig.thinking_setting` / `_build_openrouter_payload` in `agent.py`).
Parsed in `config.py::load_config`.

There is no test suite, linter, or build step configured for this project.

## Architecture

### Entry point & wiring (`__main__.py`)
`_build_components()` is the composition root: loads config, builds the `OpenRouterAgent`
(wrapped by `MonitoringToolRegistry` around the base `tools` registry), `AutoGit`, and the
`InteractiveOrchestrator`. It wires logging into `ReactLog`, registers session search/list/viewer
slash commands, and sets the per-session JSONL transcript path (`.mimic/sessions/<timestamp>.jsonl`).
Interactive mode hands the resulting context dict to `MimicApp` (Textual app in `app.py`).
On every startup it also calls `utils.prune_old_sessions(sessions_dir, keep=200)` to delete the
oldest session `.md`/`.jsonl` pairs beyond the most recent 200, and warns (via `safe_print`) if
`team.list_orphaned_delegations()` has any entry whose `started_at` is more than 24h old, pointing
the user at `/delegations` to inspect/discard it.

**Extreme React mode** (`/mode extreme`): An alternate tool registry `extreme_tools` is built at
startup with write tools, shell tools, and all read/search tools removed
(`_EXTREME_EXCLUDED_TOOLS`). In this mode the agent is forced to route all code changes and
research through `delegate_to_team`/`delegate_to_team_parallel` and `delegate_research`.

### Agent core (`agent.py`)
`OpenRouterAgent` is provider-agnostic despite the name — `self._config` can be an
`OpenRouterConfig`, `GoogleAIConfig`, or `MistralConfig` (all OpenAI-chat-completions-compatible).
Key responsibilities:
- Raw HTTP streaming (`_stream_openrouter_api`) and non-streaming calls via `urllib`, with a
  background thread + queue so Ctrl+C works mid-stream.
- `<think>/<thought>` tag budget enforcement: if an unclosed thinking tag exceeds
  `_THINK_BUDGET_CHARS = 15,000` characters, the stream is forcibly cancelled.
- Retry/backoff and context-overflow handling (`_handle_api_exception`, `_trim_messages_smart`,
  `_repair_message_sequence` for orphaned tool_calls).
- Conversation compaction (`_compact_if_needed`) based on `context_length` from config.
- A small LRU tool-result cache (`_tool_cache`, max 128 entries) for read-only tools
  (`_CACHEABLE_TOOLS`), invalidated on writes via `_invalidate_cache_for_path`.
- Preserves Gemini `thought_signature` round-trips on tool calls (`_build_tool_call_entry`).
- Three loop variants: `run` (non-streaming), `run_stream`, and `run_react` in `orchestrator.py`
  (the last is what the TUI/auto-mode actually uses).

### ReAct loop (`orchestrator.py`)
`InteractiveOrchestrator.run_react` is the main Thought→Action→Observation loop
(`MAX_REACT_STEPS = 120`). Per turn it:
1. Takes an `AutoGit` backup snapshot.
2. Checks for a `.mimic_checkpoint.json` in the cwd (Worker/sub-agent only) and resumes from
   it if present, appending a system resume note to the messages.
3. Streams the model response through `PipelineTypewriter` for live rendering.
4. **XML tool call rescue**: if `tool_calls` is empty but the text contains XML-format tool
   invocations (`<tool_call>`, `<function=...>`, `<invoke>`, etc.), `_parse_xml_tool_calls`
   attempts to parse them and injects the result as `tool_calls`. Handles Qwen/Hermes JSON
   format (A), `<function=NAME><parameter=K>V</parameter>` format (B/C), and fallbacks.
   If parsing fails, the model is prompted up to `_MAX_XML_TOOL_RETRIES = 3` times to resend
   using the API's `tool_calls` mechanism.
5. Executes tool calls — read-only tool calls run in parallel via `ThreadPoolExecutor`; any
   write tool (`write_file`/`edit_file`/`patch_file`/`delete_file`) forces sequential execution
   and triggers an `AutoGit` checkpoint commit on success.
6. **Stale observation invalidation**: when a file is written, all prior `read_file` observations
   for that path in the current turn's messages are overwritten with `"[このread結果は後で上書き
   されました—省略]"` to prevent the model from acting on stale content.
7. Observations are truncated to `_OBS_MAX_CHARS = 2000` chars in the conversation messages;
   full output is separately accessible via the tool output cache (`cache_obs`).
8. Saves a `.mimic_checkpoint.json` after each step (Worker only, via `MIMIC_NO_AUTOGIT` env
   check). On loop limit or normal completion, the checkpoint is deleted.
9. On final answer: **squashes** all per-write checkpoint commits into a single commit
   (`auto_git.squash()`) so the git log stays clean.
10. Logs every thought/action/observation/final-answer to `ReactLog` (JSONL + markdown).

`BASH_EXECUTOR_GUIDANCE` and `REACT_SYSTEM_PROMPT` (appended to the user's `SYSTEM_PROMPT`) define
the agent's operating rules — notably a "Pipeline-First" policy (prefer `search_in_file` /
`grep_codebase` / `file_info` / `run_pipeline` over `read_file` to save context) and an
"aggressive team delegation" policy (`delegate_to_team[_parallel]`, see below).
`WORKER_COMPLETION_GUIDANCE` is additionally appended for sub-agents started with
`MIMIC_NO_AUTOGIT=1`, instructing them to report completion and exit cleanly.
`EXTREME_REACT_SYSTEM_PROMPT` is an alternate prompt selectable via `/mode extreme` (Director-only
mode, described above).

### Tools (`tools.py`, `tools_linux.py`, `pipeline.py`)
`ToolRegistry` (in `tools.py`) holds all tool specs/functions; tools self-register via
`@tools.register(...)`. Categories:
- File ops: `read_file`, `write_file`, `edit_file`, `patch_file`, `read_tool_cache`,
  `get_repo_map`. Writes go through `_request_write_approval` (a hookable approval callback set
  via `set_write_approval_handler`; raises `UserRejectedWriteError` on rejection) and warn if the
  file wasn't `read_file`'d this turn (`_check_read_warning`).
- Shell/search (`tools_linux.py`): `run_bash` (pty-based), `file_info`, `search_in_file`,
  `grep_codebase`, `smart_read`. `grep_codebase`'s recursive mode excludes common noise
  directories/files (`node_modules`, `.git`, `.venv`, `dist`, lockfiles, etc. —
  `_GREP_EXCLUDE_DIRS`/`_GREP_EXCLUDE_FILES`) and truncates each matched line to
  `_GREP_MAX_LINE_CHARS = 300` to avoid blowing context on minified files.
- `run_pipeline` (`pipeline.py`): non-pty streaming shell execution for high-volume output
  (registers itself onto the same `tools` registry from `tools.py`).
- Web/browser: `web_search`, `fetch_webpage`, and Playwright-backed `browser_*` tools (no-op if
  `playwright` isn't installed; toggled via `enable_browser_tools`/`disable_browser_tools`).
- Team delegation: `delegate_to_team`, `delegate_to_worker`, `delegate_to_team_parallel`,
  `delegate_research`, `get_delegation_trace` (see below). **These are removed from the Worker's
  registry** when started with `MIMIC_NO_AUTOGIT=1` to prevent infinite sub-agent recursion.
- Large tool outputs (>10000 chars) are auto-cached (`cache_tool_output`); the agent is told to
  page through them with `read_tool_cache(cache_key, offset)`.

### Sub-agents & team delegation (`subagent.py`, `team.py`)

#### `delegate_to_team` — Researcher → Worker → verify loop
`team.py::run_team_task` runs a Researcher, then a Worker with automated verify retry:

1. **Researcher** (`run_research` / `_run_isolated` with `role="Researcher"`): runs once. A fresh,
   history-less agent with `_build_researcher_registry` (read-only tools + `web_search`/
   `fetch_webpage`, `_RESEARCHER_MAX_ROUNDS = 12`) investigates the Director's task and produces
   a detailed Markdown "design workflow" (target file paths, current code, step-by-step changes,
   code samples, completion criteria) prepended to the Worker's task as
   `[Researcherによる設計ワークフロー]`. Logged as `team_research_done`.
   If no `verify_cmd` was provided by the Director, the Researcher may suggest one via
   `[推奨verify_cmd] <cmd>` at the end of its output; `_extract_suggested_verify_cmd()` parses
   this and auto-adopts it.

2. **Worker** (`subagent.py::run_subagent_reviewable`): a synchronous, sandboxed copy of mimic
   itself. Builds an OverlayFS workroom (`lowerdir`=project read-only, `upperdir`=scratch,
   `merged`=view), runs `unshare -U -m -r` in an unprivileged namespace, then launches
   `python3 -m mimic_tui --auto-prompt "<task>"` with `MIMIC_NO_AUTOGIT=1`. Its stdout is streamed
   live (prefixed `[Worker:<label>]`). The Worker inherits the Director's provider/model via
   `MIMIC_PROVIDER`/`MIMIC_MODEL` environment variables.
   - **Crash recovery**: if the Worker exits unexpectedly without printing `===MIMIC_FINAL===`
     and a `.mimic_checkpoint.json` exists in the merged dir, up to `_MAX_RESUME_ATTEMPTS = 3`
     re-launches are attempted with the same overlay (continuing from the saved state).
   - Timeout: `_TIMEOUT_SEC = 1800` (30 min); a watchdog thread sends `SIGKILL` on expiry.
   - `verify_cmd`: after the Worker exits, runs `timeout 300 bash -c <verify_cmd>` inside the
     same overlay; exit code and output are stored in `SubagentResult.verify_exit/verify_output`.

3. **Verify retry loop** (`MAX_VERIFY_RETRIES = 3`, shared via `_run_delegation_core`): if
   `verify_exit != 0`, `_build_verify_retry_task()` builds a new task string that includes the
   original task, the verify failure output (up to 3000 chars), and an instruction to fix the
   error. It then re-runs `run_subagent_reviewable` with the **same `base`** (so `upper` carries
   forward all previous changes — this is a continuation, not a restart). Repeats until verify
   passes, retries are exhausted, or a retry itself errors out. **Aborts immediately** (no retry)
   if `verify_exit` is `2`/`126`/`127` (bash syntax error / permission denied / command not
   found) since these indicate a broken `verify_cmd` the Worker cannot fix. On retry error the
   previous `base` is already cleaned up by the sub-process; the loop breaks and reports the
   error.

4. **Apply**: if `result.changed_files` is non-empty, `apply_subagent_changes()` copies the
   `upperdir` diff onto the real project dir (including deletions via overlay whiteout markers,
   excluding the internal `.mimic_checkpoint.json` via `_APPLY_EXCLUDED_PATHS`), serialized
   through `_apply_lock`. Then `_get_team_autogit().checkpoint()` commits the changes.
   Changes are applied regardless of final verify status (so partial work is not lost); the
   status label shows `✓検証通過` or `✗検証失敗(exit=N, 3回試行後)`. The Worker's own final-answer
   text (captured from stdout after the `===MIMIC_FINAL===` marker in `subagent.py`) is prepended
   to the summary as `[Workerの最終回答]`, so read-only/no-diff tasks still surface an answer to
   the Director. The temp dir is always cleaned up via `cleanup_subagent(base)`.

#### `delegate_to_worker` — Worker only (no Researcher)
`run_worker_once` skips the Researcher phase and runs one Worker directly. Shares the same
`_run_delegation_core` (verify retry loop, apply, inflight bookkeeping) as `delegate_to_team`.
Useful for self-contained tasks where the target file and change are already known.

#### Orphaned delegation recovery (`/delegations`, `team.py` inflight manifest)
If the Director process itself crashes/is killed mid-delegation, the Worker's overlay `base`
dir is orphaned with no record of its existence. To make this recoverable, `team.py` maintains
a JSON manifest at `.mimic/inflight_delegations.json` (`_register_inflight`/`_unregister_inflight`,
guarded by `_INFLIGHT_LOCK`): the `base` is created and registered with `trace_id` *before*
`run_subagent_reviewable` is called, and unregistered once `_run_delegation_core` reaches its
`finally` — so an entry surviving in the manifest after a restart means that delegation never
finished and is offered for recovery. `__main__.py` checks this manifest at every startup and
prints a warning if any entry's `started_at` is older than 24h (see Entry point & wiring above).
- `list_orphaned_delegations()` returns manifest entries whose `base` still exists (pruning stale
  ones), annotated with `checkpoint_age_sec` (mtime of `merged/.mimic_checkpoint.json`, a proxy
  for "might still be running").
- The TUI `/delegations` command (`commands.py::register_delegations_command`, Director-only —
  never registered for Worker sub-processes) lists these and supports
  `/delegations resume <番号>` (`resume_delegation`: re-enters `_run_delegation_core` with the
  saved `base`/task/verify_cmd, relying on `orchestrator.py`'s existing
  `.mimic_checkpoint.json`-resume logic) and `/delegations discard <番号>` (`discard_delegation`:
  `cleanup_subagent(base)` + unregister, no changes applied).

#### Verifying what a Worker actually did (`get_delegation_trace`)
Every `delegate_to_team`/`delegate_to_worker` result string includes its `trace_id`. The
`get_delegation_trace` tool (`tools.py`, backed by `viewer.py::get_session_trace_text`) looks up
the Worker's own session JSONL (matched via `session_start.trace_id`, set from `MIMIC_TRACE_ID`
in `__main__.py`) and renders its Thought/Action/Observation/final-answer trace (capped at
`max_steps`, default 20) — for when a diff summary alone isn't enough to confirm the Worker
followed the intended steps. Researcher runs (`_run_isolated`) have no session JSONL and are not
coverable by this tool.

#### `delegate_to_team_parallel`
`run_team_tasks_parallel` runs independent tasks in batches of `_MAX_PARALLEL_TEAM_TASKS = 3`
threads, each calling `run_team_task`. `_apply_lock` serializes the apply/commit step across
threads.

#### `delegate_research`
`run_research_qa` is a lighter one-shot delegation for Q&A-style research (e.g. looking up
external API docs). Reuses `_build_researcher_registry` and `RESEARCH_QA_SYSTEM_PROMPT`. Logged
as `research_qa_done`. The Director is told to use this instead of calling `web_search`/
`fetch_webpage` itself for multi-step research — keeping page contents out of its context.

#### AutoGit sharing
`set_team_autogit(auto_git)` shares the Orchestrator's `AutoGit` instance with `team.py` so
that `delegate_to_team` checkpoint commits land on the same instance tracked by the per-turn
squash logic. Without this, `auto_git.squash()` would miss delegate commits.

### Safety net (`autogit.py`)
`AutoGit` (used unless `MIMIC_NO_AUTOGIT` is set, in which case `NullAutoGit` is used):
- `backup()` before each user turn (stash/branch)
- `checkpoint()` after each successful write tool (incremental commit)
- `squash()` at turn end — collapses all checkpoint commits of the turn into one with the
  message `"🤖 task: <first 72 chars of user message>"`. No-ops if no checkpoints were made.
- `rollback()` / `diff()` for recovery

`ReactLog` (same file) records structured JSONL/markdown session transcripts under
`.mimic/sessions/`. Its in-memory `entries` list is capped at `_MAX_REACT_LOG_ENTRIES = 3000`
(`_enforce_cap()`, called after every append and JSONL load) since older entries are already
durable on disk — only the in-RAM copy is trimmed, keeping the leading `session_start` entry.

### Monitoring (`monitoring.py`, `proc_observer.py`)
`MonitoringToolRegistry` wraps the base tool registry to record per-call timing, CPU%, and RSS
delta (via `proc_observer.ProcessMonitor`) into a `ToolCallLog`, surfaced by the `/stats` command
and the inline `_inline_display` callback in `__main__.py`.

### TUI & commands (`app.py`, `commands.py`)
`MimicApp` (Textual) is a 2-pane app with tabs (Chat / Files / Scratchpad / Log), an Enter-to-send
`ChatInput`, and key bindings F1–F4 for tab switching. Slash commands (`/status`, `/clear`,
`/model`, `/mode`, `/cd`, `/scratchpad`, `/help`, `/search`, `/sessions`, `/viewer`, `/stats`,
`/delegations`) are registered on `cmd_registry` (in `commands.py`) and routed from
`on_chat_input_submit`.
`/viewer` opens a session tree viewer showing past sessions with execution status badges.

### Shared utilities (`utils.py`)
Color/markdown rendering for the terminal (`C`, `render_markdown*`), the global agent
"scratchpad" (`get_scratchpad`/`set_scratchpad`, used by `update_scratchpad*` tools and injected
into every prompt via `_build_context_header`), `PipelineTypewriter` for streamed output
rendering, `TokenBucket`/rate-limit helpers, and the tool-output cache. `emit_team_event` /
`set_team_event_sink` pipe team delegation events to `ReactLog`. `setup_logger()` writes
`mimic.log` via a `RotatingFileHandler` (5MB × 3 backups) instead of an unbounded plain file, and
`prune_old_sessions()` deletes stale `.mimic/sessions/*.md`/`*.jsonl` pairs beyond the most recent
`keep` (called with `keep=200` at startup — see Entry point & wiring) — both exist to keep
long-running installs from growing disk usage without bound.

## Notes on code provenance

Most top-level modules carry a header `# Auto-generated by split_v4.py — do not edit manually /
Original: V4.py` — they were mechanically split out of a single legacy `V4.py` script. The split
is historical; these files are actively edited now, but it explains why some cross-module
boundaries (e.g. `agent.py` importing helpers re-used by `orchestrator.py`) are a bit unusual.

## Language

All agent-facing prompts, in-app messages, and log strings are Japanese — keep new user-facing
strings and tool docstrings/descriptions in Japanese for consistency with the existing UI and
system prompts.
