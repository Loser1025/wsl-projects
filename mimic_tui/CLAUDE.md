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
`InteractiveOrchestrator`. It wires logging into `ReactLog`, registers session search/list slash
commands, and sets the per-session JSONL transcript path (`.mimic/sessions/<timestamp>.jsonl`).
Interactive mode hands the resulting context dict to `MimicApp` (Textual app in `app.py`).

### Agent core (`agent.py`)
`OpenRouterAgent` is provider-agnostic despite the name — `self._config` can be an
`OpenRouterConfig`, `GoogleAIConfig`, or `MistralConfig` (all OpenAI-chat-completions-compatible).
Key responsibilities:
- Raw HTTP streaming (`_stream_openrouter_api`) and non-streaming calls via `urllib`, with a
  background thread + queue so Ctrl+C works mid-stream.
- Retry/backoff and context-overflow handling (`_handle_api_exception`, `_trim_messages_smart`,
  `_repair_message_sequence` for orphaned tool_calls).
- Conversation compaction (`_compact_if_needed`) based on `context_length` from config.
- A small LRU tool-result cache (`_tool_cache`) for read-only tools (`_CACHEABLE_TOOLS`),
  invalidated on writes via `_invalidate_cache_for_path`.
- Preserves Gemini `thought_signature` round-trips on tool calls (`_build_tool_call_entry`).
- Three loop variants: `run` (non-streaming), `run_stream`, `run_react` (the last lives in
  `orchestrator.py` and is what the TUI/auto-mode actually use).

### ReAct loop (`orchestrator.py`)
`InteractiveOrchestrator.run_react` is the main Thought→Action→Observation loop
(`MAX_REACT_STEPS = 120`). Per turn it:
1. Takes an `AutoGit` backup snapshot.
2. Streams the model response through `PipelineTypewriter` for live rendering.
3. Executes tool calls — read-only tool calls run in parallel via `ThreadPoolExecutor`; any
   write tool (`write_file`/`edit_file`/`patch_file`/`delete_file`) forces sequential execution
   and triggers an `AutoGit` checkpoint commit on success.
4. Logs every thought/action/observation/final-answer to `ReactLog` (JSONL + markdown).

`BASH_EXECUTOR_GUIDANCE` and `REACT_SYSTEM_PROMPT` (appended to the user's `SYSTEM_PROMPT`) define
the agent's operating rules — notably a "Pipeline-First" policy (prefer `search_in_file` /
`grep_codebase` / `file_info` / `run_pipeline` over `read_file` to save context) and an
"aggressive sub-agent delegation" policy. `EXTREME_REACT_SYSTEM_PROMPT` is an alternate
profile-switching prompt selectable via `/mode`.

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
- Sub-agent delegation: `delegate_to_subagent` / `delegate_to_subagent_parallel` (see below).
- Large tool outputs (>10000 chars) are auto-cached (`cache_tool_output`); the agent is told to
  page through them with `read_tool_cache(cache_key, offset)`.

### Sub-agents (`subagent.py`)
`delegate_to_subagent[_parallel]` spawns a synchronous, sandboxed copy of mimic itself:
- Builds an OverlayFS workroom (`lowerdir`=project read-only, `upperdir`=scratch, `merged`=view).
- Runs `unshare -U -m -r` to mount the overlay in an unprivileged namespace, then launches
  `python3 -m mimic_tui --auto-prompt "<task>"` with `MIMIC_CWD=<merged>` and
  `MIMIC_NO_AUTOGIT=1` (sub-agents never touch git).
- Returns a `SubagentResult` summarizing changed files in `upperdir` as a diff; the parent agent
  must review and apply changes itself via its own file tools, then commit.
- Cleanup is automatic (namespace teardown unmounts overlay; `_force_rmtree` handles the
  mode-0000 overlay `work` dir).

### Safety net (`autogit.py`)
`AutoGit` (used unless `MIMIC_NO_AUTOGIT` is set, in which case `NullAutoGit` is used):
`backup()` before each user turn, `checkpoint()` after each successful write tool, `rollback()`/
`diff()` for recovery — all plain `git` subprocess calls scoped to `agent.cwd`. `ReactLog` (same
file) records the structured JSONL/markdown session transcripts under `.mimic/sessions/`.

### Monitoring (`monitoring.py`, `proc_observer.py`)
`MonitoringToolRegistry` wraps the base tool registry to record per-call timing, CPU%, and RSS
delta (via `proc_observer.ProcessMonitor`) into a `ToolCallLog`, surfaced by the `/stats` command
and the inline `_inline_display` callback in `__main__.py`.

### TUI & commands (`app.py`, `commands.py`)
`MimicApp` (Textual) is a 2-pane app with tabs (Chat / Files / Scratchpad / Log), an Enter-to-send
`ChatInput`, and key bindings F1–F4 for tab switching. Slash commands (`/status`, `/clear`,
`/model`, `/mode`, `/cd`, `/scratchpad`, `/help`, `/search`, `/sessions`) are registered on
`cmd_registry` (in `commands.py`) and routed from `on_chat_input_submit`.

### Shared utilities (`utils.py`)
Color/markdown rendering for the terminal (`C`, `render_markdown*`), the global agent
"scratchpad" (`get_scratchpad`/`set_scratchpad`, used by `update_scratchpad*` tools and injected
into every prompt via `_build_context_header`), `PipelineTypewriter` for streamed output
rendering, `TokenBucket`/rate-limit helpers, and the tool-output cache.

## Notes on code provenance

Most top-level modules carry a header `# Auto-generated by split_v4.py — do not edit manually /
Original: V4.py` — they were mechanically split out of a single legacy `V4.py` script. The split
is historical; these files are actively edited now, but it explains why some cross-module
boundaries (e.g. `agent.py` importing helpers re-used by `orchestrator.py`) are a bit unusual.

## Language

All agent-facing prompts, in-app messages, and log strings are Japanese — keep new user-facing
strings and tool docstrings/descriptions in Japanese for consistency with the existing UI and
system prompts.
