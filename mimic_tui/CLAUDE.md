# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
`SYSTEM_PROMPT`, `ENABLE_CONFIDENCE_CHECK`. Parsed in `config.py::load_config`.

There is no test suite, linter, or build step configured for this project.

## Architecture

### Entry point & wiring (`__main__.py`)
`_build_components()` is the composition root: loads config, builds the `OpenRouterAgent`
(wrapped by `MonitoringToolRegistry` around the base `tools` registry), `AutoGit`, and the
`InteractiveOrchestrator`. It wires logging into `ReactLog`, registers session search/list/viewer
slash commands, and sets the per-session JSONL transcript path (`.mimic/sessions/<timestamp>.jsonl`).
Interactive mode hands the resulting context dict to `MimicApp` (Textual app in `app.py`).

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
  `grep_codebase`, `smart_read`.
- `run_pipeline` (`pipeline.py`): non-pty streaming shell execution for high-volume output
  (registers itself onto the same `tools` registry from `tools.py`).
- Web/browser: `web_search`, `fetch_webpage`, and Playwright-backed `browser_*` tools (no-op if
  `playwright` isn't installed; toggled via `enable_browser_tools`/`disable_browser_tools`).
- Team delegation: `delegate_to_team`, `delegate_to_worker`, `delegate_to_team_parallel`,
  `delegate_research` (see below). **These are removed from the Worker's registry** when started
  with `MIMIC_NO_AUTOGIT=1` to prevent infinite sub-agent recursion.
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

3. **Verify retry loop** (`MAX_VERIFY_RETRIES = 3`): if `verify_exit != 0`, `run_team_task`
   calls `_build_verify_retry_task()` to build a new task string that includes the original task,
   the verify failure output (up to 3000 chars), and an instruction to fix the error. It then
   re-runs `run_subagent_reviewable` with the **same `base`** (so `upper` carries forward all
   previous changes — this is a continuation, not a restart). Repeats until verify passes,
   retries are exhausted, or a retry itself errors out. On retry error the previous `base` is
   already cleaned up by the sub-process; the loop breaks and reports the error.

4. **Apply**: if `result.changed_files` is non-empty, `apply_subagent_changes()` copies the
   `upperdir` diff onto the real project dir (including deletions via overlay whiteout markers),
   serialized through `_apply_lock`. Then `_get_team_autogit().checkpoint()` commits the changes.
   Changes are applied regardless of final verify status (so partial work is not lost); the
   status label shows `✓検証通過` or `✗検証失敗(exit=N, 3回試行後)`.
   The temp dir is always cleaned up via `cleanup_subagent(base)`.

#### `delegate_to_worker` — Worker only (no Researcher)
`run_worker_once` skips the Researcher phase and runs one Worker directly. Has the same
verify retry loop (`MAX_VERIFY_RETRIES = 3`) as `delegate_to_team`. Useful for self-contained
tasks where the target file and change are already known.

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
`.mimic/sessions/`.

### Monitoring (`monitoring.py`, `proc_observer.py`)
`MonitoringToolRegistry` wraps the base tool registry to record per-call timing, CPU%, and RSS
delta (via `proc_observer.ProcessMonitor`) into a `ToolCallLog`, surfaced by the `/stats` command
and the inline `_inline_display` callback in `__main__.py`.

### TUI & commands (`app.py`, `commands.py`)
`MimicApp` (Textual) is a 2-pane app with tabs (Chat / Files / Scratchpad / Log), an Enter-to-send
`ChatInput`, and key bindings F1–F4 for tab switching. Slash commands (`/status`, `/clear`,
`/model`, `/mode`, `/cd`, `/scratchpad`, `/help`, `/search`, `/sessions`, `/viewer`, `/stats`)
are registered on `cmd_registry` (in `commands.py`) and routed from `on_chat_input_submit`.
`/viewer` opens a session tree viewer showing past sessions with execution status badges.

### Shared utilities (`utils.py`)
Color/markdown rendering for the terminal (`C`, `render_markdown*`), the global agent
"scratchpad" (`get_scratchpad`/`set_scratchpad`, used by `update_scratchpad*` tools and injected
into every prompt via `_build_context_header`), `PipelineTypewriter` for streamed output
rendering, `TokenBucket`/rate-limit helpers, and the tool-output cache. `emit_team_event` /
`set_team_event_sink` pipe team delegation events to `ReactLog`.

## Notes on code provenance

Most top-level modules carry a header `# Auto-generated by split_v4.py — do not edit manually /
Original: V4.py` — they were mechanically split out of a single legacy `V4.py` script. The split
is historical; these files are actively edited now, but it explains why some cross-module
boundaries (e.g. `agent.py` importing helpers re-used by `orchestrator.py`) are a bit unusual.

## Language

All agent-facing prompts, in-app messages, and log strings are Japanese — keep new user-facing
strings and tool docstrings/descriptions in Japanese for consistency with the existing UI and
system prompts.
