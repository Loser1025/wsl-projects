# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`mimic_tui` is a Python/Textual TUI for a self-contained ReAct coding agent ("mimic"). It talks
directly to OpenRouter / Google AI Studio (Gemini) / Mistral chat-completions APIs over raw
`urllib` (no SDKs), runs an agentic tool-call loop, and can spin up sandboxed sub-agents of itself.
It also speaks two external-ecosystem protocols directly (no SDKs there either): Claude Code's
`SKILL.md` format (`skills.py`) and MCP (`mcp_client.py`, stdio + remote Streamable HTTP) — see
their sections under Architecture below.

**Project thesis**: mimic's core bet is that a weak/free-tier LLM API, wrapped in a sufficiently
rigid and well-engineered harness (tool loop, delegation, verification scaffolding, session
logging), can be driven to match or exceed the practical output quality of commercial coding
agents built on frontier models. Harness rigor is the lever, not model strength — design/review
decisions in this repo should be weighed against that goal.

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
`SYSTEM_PROMPT`, `GEMINI_THINKING_LEVEL`
(`none`/`minimal`/`low`/`medium`/`high`, mapped to `reasoning_effort` in the OpenAI-compatible
payload — see `GoogleAIConfig.thinking_setting` / `_build_openrouter_payload` in `agent.py`).
Parsed in `config.py::load_config`.

There is no linter or build step configured for this project. There is a narrow, deliberately
**non**-comprehensive test suite (`tests/`, stdlib `unittest` only, no new dependency) covering only
the safety-boundary behavior of `skills.py`/`mcp_client.py` — see their Architecture sections below
for what's tested. Run it with:

```bash
python -m unittest discover -s mimic_tui/tests -t .   # from the repo root, one level above mimic_tui/
```

There's also a benchmarking script (`mimic_bench.py`) that aggregates the harness's own runtime
logs (not a synthetic eval suite) — see the Architecture section below.

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

**Two agent modes** (`/mode <name>`, `app.py::_cmd_mode`). There is no "extreme" mode — an earlier
extreme-mode design was consolidated into `specialist`; only these two exist in the current code:

- **Interactive** (`/mode interactive`, aliases `react`/`i`): the full tool registry
  (`mon_tools`), including write tools, shell tools, and delegation tools. Described as the
  fallback/退避用 mode.
- **Specialist** (`/mode specialist`, aliases `spec`/`s`, and the default via
  `MIMIC_DEFAULT_MODE`, default value `"specialist"`): write tools, shell tools, `smart_read`,
  `get_repo_map`, `web_search`/`fetch_webpage`, and the fixed-role delegation tools
  (`delegate_to_team[_parallel]`, `delegate_to_worker`, `delegate_research`) are all removed
  (`__main__.py::_SPECIALIST_EXCLUDED_TOOLS`), leaving `delegate_to_specialist` as the only
  delegation path. `read_file`/`grep_codebase`/`file_info` remain available as "peek" tools, but
  their observations are truncated to `_PEEK_OBS_MAX_CHARS` so deep reading still has to go
  through a delegated specialist. On switching to this mode, `team.load_saved_roles_section()` is
  appended to the system prompt to surface previously successful role definitions from
  `.mimic/roles/*.json` (see `delegate_to_specialist` below).

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
7. Observations are truncated to `_OBS_MAX_CHARS = 2000` chars in the conversation messages
   (delegation tool results get a larger `_DELEGATION_OBS_MAX_CHARS = 6000` budget since they
   may be the Director's only information source); full output is separately accessible via
   the tool output cache (`cache_obs`).
8. Saves a `.mimic_checkpoint.json` after each step (Worker only, via `MIMIC_NO_AUTOGIT` env
   check). On loop limit or normal completion, the checkpoint is deleted.
9. **Loop breaker**: identical tool calls (same name + normalized args) that fail
   `_MAX_IDENTICAL_TOOL_FAILURES = 3` times are refused without execution (a warning is
   injected at the 2nd failure); more than `_MAX_LOOP_REFUSALS = 5` refusals in a turn raises
   `ToolLoopBreakError` and aborts the turn.
10. **Final-answer gates** (each bounces at most once per turn, via `_skip_save` messages):
    Gate A (`_detect_command_offload`) rejects answers that ask the user to run commands or
    edit files while the agent still has `run_bash`/delegation tools (exempt if the text
    mentions login/auth/interactive needs); Gate B (`_detect_unverified_claim`) rejects
    "完了/解決" claims when the turn contained a delegation result marked `※未検証`.
11. On final answer: **squashes** all per-write checkpoint commits into a single commit
    (`auto_git.squash()`) so the git log stays clean.
12. Logs every thought/action/observation/final-answer to `ReactLog` (JSONL + markdown).

Context support for weak models: `_compact_if_needed` (agent.py) replaces old conversation
with a deletion note **plus a mechanically extracted digest** (`_build_compaction_digest`:
user instructions, tool calls with primary args, per-call OK/失敗 status — no LLM involved),
and `_build_context_header` prepends a "ハーネス自動記録" section (current task goal, files
written this session tracked in `agent._recent_writes`, last 3 delegation outcomes via
`team.get_delegation_history_brief`) so the model's own scratchpad discipline is not the only
memory mechanism.

`BASH_EXECUTOR_GUIDANCE` and `REACT_SYSTEM_PROMPT` (appended to the user's `SYSTEM_PROMPT`) define
the agent's operating rules — notably a "Pipeline-First" policy (prefer `search_in_file` /
`grep_codebase` / `file_info` / `run_pipeline` over `read_file` to save context) and an
"aggressive team delegation" policy (`delegate_to_team[_parallel]`, see below).
`WORKER_COMPLETION_GUIDANCE` is additionally appended for sub-agents started with
`MIMIC_NO_AUTOGIT=1`, instructing them to report completion and exit cleanly.
`SPECIALIST_REACT_SYSTEM_PROMPT` (`orchestrator.py`) is appended in place of `REACT_SYSTEM_PROMPT`
when switching to Specialist mode (`app.py::_cmd_mode`, described above).
`WORKER_REACT_SYSTEM_PROMPT` is the variant used for sub-agent Workers — it omits any mention of
delegation tools entirely, since Workers have them stripped from their registry.

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
- Skills: `load_skill`, `list_skills` (see below). MCP: `mcp__<server>__<tool>`, dynamically
  registered per connected server (see below).

### Skills — Claude Code-compatible `SKILL.md` support (`skills.py`)
Reads `SKILL.md` (YAML frontmatter + Markdown body) directly from `~/.claude/skills/` and
`<cwd>/.claude/skills/` — the same format and directories Claude Code uses, so skill libraries are
shared with zero conversion. **Progressive disclosure**: only `name`/`description` are loaded into
the context header at all times (`SkillRegistry.context_header_section()`, capped at
`_SUMMARY_TOTAL_MAX_CHARS = 1500` total); the full body is fetched only when the model explicitly
calls `load_skill(name)` (capped at `_BODY_MAX_CHARS = 6000`, overflow paged via the existing
`cache_tool_output`/`read_tool_cache` mechanism). `SKILL.md` files are never written to — trust
tracking lives entirely in `.mimic/skill_trust.json` (`record_outcome`), which is separate,
non-destructive bookkeeping.
- Tool-name alias hints: `load_skill`'s response appends a short "read as" note when the body
  mentions Claude Code-native tool names (`Read`, `Edit`, `Bash`, `Grep`, etc. — `_TOOL_ALIASES` in
  `skills.py`), mapped to Mimic's equivalents (`read_file`, `edit_file`, `run_bash`, ...). The hint
  only appears when a match is found, so unrelated skills aren't padded with noise.
- Usage tracking feeds trust scoring: `load_skill` calls `mark_loaded()` (thread-local) so
  in-process runs (Director, `_run_isolated` read-only Specialist — both added to
  `_RESEARCHER_TOOLS` in `team.py`) can attribute skill usage to their own verify/completion
  outcome. Worker subprocess runs are attributed by scanning the Worker's own session JSONL for
  `load_skill` actions via `trace_id` (`find_session_skill_usages`, same trace-id linkage
  `viewer.get_session_trace_text` uses) — trust is only recorded when a `verify_cmd` actually ran
  (unverified applies don't move the score, matching the "don't trust self-report" principle used
  elsewhere in this repo).
- `/skills` (`commands.py::register_mcp_command`'s sibling `register_skills_command`) lists
  skills with a trust badge and supports `/skills reload`.

### MCP (Model Context Protocol) client (`mcp_client.py`)
Connects to servers declared in `.mcp.json`'s `mcpServers` key (same format/keys as Claude Code;
read from `~/.mcp.json` then `<cwd>/.mcp.json`, latter wins on name collision) and registers each
server's tools into the base `ToolRegistry` as `mcp__<server>__<tool>`. Two transports, dispatched
by whether a config entry has `"command"` (stdio) or `"url"` (remote):
- **stdio** (`McpServerProcess`): `subprocess.Popen` + newline-delimited JSON-RPC
  (`initialize` → `notifications/initialized` → `tools/list` → `tools/call`), one in-flight
  request per server (`_lock`), lazy respawn on crash/timeout.
- **Remote / Streamable HTTP** (`McpHttpServerProcess`, P2): stateless POST-per-call via `urllib`
  only (no SDK, consistent with `agent.py`'s raw-HTTP policy), carries the `Mcp-Session-Id`
  response header on subsequent requests, and does a minimal `data:`-line SSE parse if the server
  responds with `text/event-stream`.

**Trust boundary (unlike Skills, MCP servers execute real code, not just text the model reads):**
every MCP tool call goes through the existing `_request_write_approval` hook by default — MCP's
own `readOnlyHint` annotations are not trusted. The only way to skip approval is an explicit
`/mcp trust <server> read-only`, persisted to `.mimic/mcp_policy.json` (never written into
`.mcp.json` itself). `connect_all(readonly_only=...)` is the single entry point used everywhere:
- **Director** (`_build_components` in `__main__.py`, plus the `--auto-prompt` path when
  `MIMIC_NO_AUTOGIT` is *not* set — i.e. standalone autonomous mode, not a Worker):
  `readonly_only=False`, connects to every configured server.
- **Worker** (`--auto-prompt` with `MIMIC_NO_AUTOGIT=1`): `readonly_only=True`. Workers can't share
  the Director's live subprocess/HTTP session across the process boundary, so a Worker connects to
  MCP servers itself — but since Workers run with no write-approval handler installed at all
  (`_write_approval_handler` stays `None`, so `_request_write_approval` is a silent no-op there),
  "approval required" would be no protection in that context. The only real safety boundary for
  Workers is therefore at *connection time*: only servers already marked `read-only` in
  `.mimic/mcp_policy.json` are ever connected/registered for a Worker.
- **Specialist mode** (`__main__.py`): all `mcp__`-prefixed tools are excluded from
  `_specialist_registry` outright (P0/P1 has no allowlist mechanism yet — see design doc for the
  planned per-tool whitelist).
- `/mcp` (`commands.py::register_mcp_command`): status list, `/mcp reconnect <server>`,
  `/mcp trust <server> [read-only|off]`. All MCP servers are shut down via `atexit` hooks
  registered in both the Director and `--auto-prompt` entry points.

### Benchmark aggregation (`mimic_bench.py`)
Not a synthetic eval suite — it reads the harness's own already-existing runtime logs
(`.mimic/skill_trust.json`, `.mimic/mcp_policy.json`, `.mimic/verify_cmds.json`,
`.mimic/sessions/*.jsonl`) and turns them into a Markdown report (`collect_all()` → `build_report()`).
`run()` also writes a dated snapshot to `.mimic/bench_history/<YYYY-MM-DD>.json` and diffs the
current numbers against the most recent prior snapshot (`load_previous_snapshot()`) to show
pass-rate deltas (`前回比 ±Npt`). Sample counts under `_MIN_SAMPLE = 5` are flagged as
"reference only" (`low_sample`) rather than trusted outright — a single pass/fail shouldn't be read
as a trend. `collect_session_usage()` fills the one real gap in the existing logs: it scans session
JSONL `action` entries for `load_skill`/`mcp__*` calls to get raw usage counts, since
`mcp_policy.json` doesn't track per-tool pass/fail the way `skill_trust.json` does for Skills (a
known, explicitly-noted gap — MCP has no verify-outcome-based trust scoring yet). Invoked via
`/bench` (`commands.py::register_bench_command`) or `python -m mimic_tui.mimic_bench` directly.

### Tests (`tests/`)
Deliberately narrow: only the safety-boundary behavior of `skills.py` and `mcp_client.py` is
tested, not the rest of the codebase (the project's "no test suite" stance elsewhere is
unchanged — these two modules are the exception because they mediate trust/approval boundaries
where a silent regression would be dangerous, not just wrong). No new dependency —
plain `unittest`, run via `python -m unittest discover -s mimic_tui/tests -t .` from one level
above the package. `tests/fixtures/fake_mcp_server.py` / `fake_mcp_http_server.py` are minimal
stdio/HTTP MCP servers (not the shipped product) used to exercise a real JSON-RPC handshake rather
than mocking it. Covers: SKILL.md non-destructiveness, the `_BODY_MAX_CHARS` truncation budget,
the tool-name alias hint only firing on an actual match, `find_session_skill_usages` trace-id
matching, MCP write-approval actually blocking on rejection, `read-only` trust actually skipping
approval, and — the one that matters most — `connect_all(readonly_only=True)` (the Worker path)
only ever connecting servers already marked `read-only` in `.mimic/mcp_policy.json`.

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

4. **Apply**: if `result.changed_files` is non-empty (and `apply_changes` is not False),
   `apply_subagent_changes()` copies the `upperdir` diff onto the real project dir (including
   deletions via overlay whiteout markers, excluding the internal `.mimic_checkpoint.json` via
   `_APPLY_EXCLUDED_PATHS`), serialized through `_apply_lock`. Then
   `_get_team_autogit().checkpoint()` commits the changes. Files whose real-project mtime is
   newer than the delegation's start time are flagged in the summary as potential conflicts
   (apply is last-writer-wins). All delegation Worker subprocesses (team/worker/specialist,
   including resumes) share `_DELEGATION_SEMAPHORE` (`_MAX_DELEGATION_CONCURRENCY = 3`), so
   parallel `delegate_to_specialist` calls from the orchestrator's parallel tool path cannot
   spawn unbounded Workers.
   Changes are applied regardless of final verify status (so partial work is not lost); the
   status label shows `✓検証通過` or `✗検証失敗(exit=N, 3回試行後)`. The Worker's own final-answer
   text (captured from stdout after the `===MIMIC_FINAL===` marker in `subagent.py`) is prepended
   to the summary as `[Workerの最終回答]`, so read-only/no-diff tasks still surface an answer to
   the Director. The temp dir is always cleaned up via `cleanup_subagent(base)`.

#### `delegate_to_worker` — Worker only (no Researcher)
`run_worker_once` skips the Researcher phase and runs one Worker directly. Shares the same
`_run_delegation_core` (verify retry loop, apply, inflight bookkeeping) as `delegate_to_team`.
Useful for self-contained tasks where the target file and change are already known.
Accepts `apply_changes=False` to run the Worker in the overlay but discard its changes
(used by `delegate_to_specialist(can_execute=True)`).

#### `delegate_to_specialist` — dynamic-role delegation
`run_specialist_task` runs an agent whose system prompt is built at runtime from a free-form
`role` string (`_build_dynamic_system_prompt`). The `role` is validated at the tool boundary
(`validate_specialist_role`: ≥20 chars and must contain the literal "完了基準"; otherwise the
call is rejected with a fill-in template, without spawning a Worker). Three permission tiers:
default (read-only, in-process `_run_isolated` with the Researcher registry — which also
includes the `browser_*` tools copied from `_browser_registry` for observing deployed pages;
`max_rounds` scales 12→18→24 with role+task length via `_rounds_for_specialist`),
`can_execute=True` (full overlay Worker, but changes are discarded — for test/build/diagnosis
roles), and `can_write=True` (overlay Worker with apply+commit, verify retry included; optional
`expected_files` triggers a harness warning when files outside the list were changed).

Harness-side controls (none of these rely on the model's self-report):
- If `can_write=True` and no `verify_cmd` was given, `_suggest_verify_cmd` runs a cheap
  read-only pass (max 6 rounds) to auto-procure one; if none is found the result is labeled
  `※未検証（verify_cmd未指定・Workerの自己申告のみ）`.
- A `can_write` delegation whose overlay diff is empty gets a `⚠ ハーネス判定 … 未遂の可能性`
  warning appended.
- Every delegation is recorded in a ring buffer (last 5; `_record_delegation` /
  `render_delegation_history`) and the rendered history is auto-prepended to the next
  delegation's task inside `_run_delegation_core_inner` (and to read-only specialist prompts),
  so Workers see what previous Workers did without relying on the Director copying context.
- **Write interlock** (`check_write_interlock`): 3 consecutive write delegations whose changed
  files overlap (and which did not pass verify) block further write delegations until one
  read-only delegation completes; `/clear` and `/mode` switches reset it
  (`clear_delegation_history`).
- Role definitions persist to `.mimic/roles/*.json` (`_save_specialist_role`, capped at
  `_ROLES_KEEP=30`) **only when the delegation passed machine verification** (`✓検証通過` for
  write/execute; read-only roles save on any completed answer);
  `load_saved_roles_section()` renders the most recent 10 for prompt injection on
  `/mode specialist`.
- Specialist final answers must use the 4-heading template (【結論】【変更・実施内容】【残課題】
  【次の推奨】, `STRUCTURED_ANSWER_GUIDANCE`); read-only runs re-request the format once if
  missing (`_run_isolated(require_structured=True)`).

Available in all modes, but it is the only delegation tool in Specialist mode. If
`_run_isolated` exhausts its rounds it returns an explicit `[ラウンド上限到達・調査未完了]`
message (with the last partial output) instead of an empty string, so the Director can
distinguish "incomplete" from "no findings".

Worker sandbox boundary: when running as a Worker (`MIMIC_NO_AUTOGIT=1`), `write_file`/
`edit_file`/`patch_file` refuse paths outside the process cwd (= the overlay `merged` dir;
`_check_worker_write_boundary` in tools.py), and `run_bash`/`run_pipeline` append a warning
when a command redirects/copies to an absolute path outside it
(`_worker_outside_write_warning` in tools_linux.py) — otherwise such writes silently escape
the overlay and never appear in `changed_files`.

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
  saved `base`/task/verify_cmd/role_prompt/apply_changes — specialist role prompts and the
  execute-only discard flag survive a Director crash — relying on `orchestrator.py`'s existing
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
