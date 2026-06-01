"""🦊 CLI Agent TUI Demo - Built with Textual
===========================================================
A demo of a modern CLI Agent Text-User-Interface showcasing
the latest Textual design patterns:

  • TabbedContent (Agent Chat / Task Tree / System Logs)
  • RichLog      → streaming AI responses in real-time
  • DataTable    → agent task queue
  • Markdown     → formatted AI replies
  • Tree         → file explorer
  • ProgressBar  → running task progress
  • Reactive     → live-updating status counters
  • CSS          → dark-theme styling
  • Work (async) → background task simulation
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    ProgressBar,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.tree import TreeNode

# ─────────────────────────────────────────────
# Custom Widgets
# ─────────────────────────────────────────────

class AgentStatusBadge(Static):
    """Live-updating agent status badge."""

    status = reactive("IDLE")
    active_tasks = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._update_content()

    def render(self) -> str:
        color_map = {"IDLE": "grey", "WORKING": "yellow", "DONE": "green", "ERROR": "red"}
        color = color_map.get(self.status, "white")
        return f" Agent Status: [{color}]{self.status}[/{color}] | Active Tasks: {self.active_tasks} "

    def watch_status(self, old, new):
        self._update_content()

    def watch_active_tasks(self, old, new):
        self._update_content()

    def _update_content(self):
        self.refresh()


class TaskCounter(Static):
    """Shows completed / total tasks."""

    done = reactive(0)
    total = reactive(0)

    def render(self) -> str:
        return f"✅ {self.done} / {self.total} tasks completed"


class LogPanel(RichLog):
    """RichLog with a slight border effect."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_subtitle = "SYSTEM LOG"


# ─────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────

class CLI_Agent_App(App):
    """CLI Agent TUI Demo Application."""

    TITLE = "◉ OWL CLI Agent"
    SUB_TITLE = "Terminal AI Assistant"

    CSS = """
    /* ── Global ── */
    Screen {
        layout: vertical;
        background: $surface-darken-1;
    }

    /* ── Header / Footer ── */
    Header {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    Footer {
        background: $primary-darken-2;
    }

    /* ── Status Bar ── */
    #status-bar {
        height: 2;
        padding: 0 2;
        background: $surface;
        border-bottom: solid $primary;
    }

    /* ── Main Body ── */
    #main-body {
        height: 1fr;
    }

    /* ── Left Sidebar ── */
    #sidebar {
        width: 28;
        min-width: 24;
        max-width: 36;
        border-right: solid $primary-darken-2;
        padding: 0 1;
    }

    #sidebar Label {
        text-style: bold;
        color: $accent;
    }

    /* ── Right Panel ── */
    #right-panel {
        width: 1fr;
    }

    /* ── Task Table ── */
    DataTable {
        height: 1fr;
        border: round $primary-darken-2;
        margin: 0 1;
    }

    DataTable > .datatable--cursor {
        background: $accent 30%;
    }

    /* ── RichLog panels ── */
    RichLog {
        border: round $primary-darken-2;
        height: 1fr;
        margin: 1;
    }

    /* ── Markdown panel ── */
    #md-output {
        border: solid $accent;
        padding: 1 2;
        height: 1fr;
        margin: 1;
        text-align: left;
    }

    /* ── Progress Bar ── */
    #overall-progress {
        padding: 0 2;
        height: 3;
        background: $surface;
    }

    /* ── Input area ── */
    #input-area {
        height: 5;
        padding: 0 2;
        background: $surface;
        border-top: solid $primary;
    }

    #cmd-input {
        border: tall $accent;
        margin: 1 0;
    }

    /* ── File Tree ── */
    #file-tree {
        height: 1fr;
        border: round $primary-darken-2;
        margin: 1;
    }

    /* ── Tab overrides ── */
    TabbedContent ContentSwitcher {
        height: 1fr;
    }

    /* ── Log panel ── */
    .log-line-info     { color: $text; }
    .log-line-success   { color: $success; }
    .log-line-warn      { color: $warning; }
    .log-line-error     { color: $error; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("t", "toggle_dark", "Toggle Dark"),
        ("r", "run_demo", "Run Demo"),
        ("s", "simulate_task", "New Task"),
        ("c", "clear_chat", "Clear"),
        ("ctrl+l", "clear_logs", "Clear Logs"),
    ]

    # ── Reactive state ──
    agent_status = reactive("IDLE")
    active_task_count = reactive(0)
    completed_tasks = reactive(0)

    # ── Internal ──
    _demo_messages: list[tuple[str, str]] = [
        ("thinking", "  Analyzing project structure...\n  Reading configuration files..."),
        (
            "tool",
            ' ```json\n {\n   "tool": "file_search",\n   "action": "find_python_files",\n   "pattern": "**/*.py"\n }\n ```',
        ),
        (
            "response",
            "Found **3 Python files** in the project:\n\n"
            "| File | Lines | Purpose |\n"
            "|------|-------|---------|\n"
            "| `app.py` | 120 | Main application entry |\n"
            "| `utils.py` | 45 | Utility helpers |\n"
            "| `tests/test_app.py` | 88 | Unit tests |\n\n"
            "The codebase is well-structured. Shall I proceed with analysis?",
        ),
        (
            "tool",
            ' ```json\n {\n   "tool": "run_tests",\n   "command": "pytest tests/ -q",\n   "timeout": 30\n }\n ```',
        ),
        ("thinking", "  Running test suite...\n  Waiting for pytest output..."),
        (
            "response",
            "✅ All **12 tests passed** in 2.3s\n\n"
            "```\n"
            "tests/test_app.py::test_create_app PASSED\n"
            "tests/test_app.py::test_compose PASSED\n"
            "tests/test_app.py::test_bindings PASSED\n"
            "... 9 more passed\n"
            "```\n\n"
            "The application is production-ready.",
        ),
    ]

    def compose(self) -> ComposeResult:
        # ── Header ──
        yield Header(show_clock=True)

        # ── Status Bar ──
        with Container(id="status-bar"):
            yield AgentStatusBadge(id="agent-status")
            yield Static("", id="spacer-status")
            yield TaskCounter(id="task-counter")

        # ── Main Body ──
        with Horizontal(id="main-body"):
            # ── Left Sidebar ──
            with Vertical(id="sidebar"):
                yield Label("📁 AGENTS")
                yield Static("🦊 1. OWL Agent")
                yield Static("⚡ 2. Fast Runner")
                yield Static("🔍 3. Code Reviewer")
                yield Static("")
                yield Label("⚙️ ACTIONS")
                yield Button("▶ Run All", variant="success", id="run-all-btn")
                yield Button("⏹ Stop", variant="error", id="stop-btn")
                yield Button("🔄 Reset", id="reset-btn")

            # ── Right Panel ──
            with Vertical(id="right-panel"):
                # ── Tabbed Content ──
                with TabbedContent(initial="chat-tab"):
                    # Chat tab
                    with TabPane("💬 Chat", id="chat-tab"):
                        yield RichLog(id="chat-log", markup=True, auto_scroll=True)

                    # Tasks tab
                    with TabPane("📋 Tasks", id="tasks-tab"):
                        yield DataTable(id="task-table")

                    # Files tab
                    with TabPane("📂 Files", id="files-tab"):
                        yield Tree("root", id="file-tree")

                    # Logs tab
                    with TabPane("📜 Logs", id="logs-tab"):
                        yield RichLog(id="sys-log", markup=True, auto_scroll=True)

                    # Output tab
                    with TabPane("📄 Output", id="output-tab"):
                        yield Markdown(id="md-output")

        # ── Progress Bar ──
        with Container(id="overall-progress"):
            yield Label("Overall Progress:")
            yield ProgressBar(total=100, id="progress-bar", show_eta=False)

        # ── Input Area ──
        with Container(id="input-area"):
            yield Label("💬 Command (press Enter to send):")
            yield Input(placeholder="Type a command or question for the agent...", id="cmd-input")

        # ── Footer ──
        yield Footer()

    # ── Lifecycle ──

    def on_mount(self) -> None:
        """Initialize widgets on startup."""
        self.log_system("🦊 OWL CLI Agent started", level="success")
        self.log_system(f"Session: {datetime.now():%Y-%m-%d %H:%M:%S}", level="info")
        self.log_system("Press [r] to run demo, [s] to simulate new task", level="info")

        # ── Set up DataTable columns ──
        table = self.query_one("#task-table", DataTable)
        table.add_columns("ID", "Task", "Status", "Progress", "Started")
        table.cursor_type = "row"
        table.zebra_stripes = True

        # Cache ColumnKey objects for Status and Progress columns
        # (DataTable.update_cell requires ColumnKey, not string labels)
        self._status_col_key = None
        self._progress_col_key = None
        for ck, col in table.columns.items():
            if str(col.label) == "Status":
                self._status_col_key = ck
            elif str(col.label) == "Progress":
                self._progress_col_key = ck

        # Seed initial tasks
        seed_tasks = [
            ("T-001", "Initialize project", "✅ Done", "100%", "00:00"),
            ("T-002", "Analyze dependencies", "⏳ Pending", "0%", "--:--"),
            ("T-003", "Run test suite", "🔄 Running", "60%", "00:02"),
            ("T-004", "Generate documentation", "⏳ Pending", "0%", "--:--"),
            ("T-005", "Deploy to staging", "❌ Failed", "30%", "00:05"),
        ]
        for row in seed_tasks:
            table.add_row(*row, key=row[0])

        # ── Set up File Tree ──
        tree = self.query_one("#file-tree", Tree)
        root = tree.root
        root.data = "/home/loser/wsl-projects"

        src = root.add("src", data="src")
        src.add_leaf("app.py")
        src.add_leaf("utils.py")
        src.add_leaf("config.yaml")

        tests = root.add("tests", data="tests")
        tests.add_leaf("test_app.py")
        tests.add_leaf("test_utils.py")

        root.add_leaf("README.md", data="README.md")
        root.add_leaf("LICENSE", data="LICENSE")
        root.add_leaf(".gitignore", data=".gitignore")

        root.expand()
        src.expand()
        tests.expand()

        # ── Set initial counter ──
        counter = self.query_one("#task-counter", TaskCounter)
        counter.total = 5
        counter.done = 1

        # ── Welcome message ──
        chat = self.query_one("#chat-log", RichLog)
        chat.write("[bold cyan]🦊 OWL Agent:[/bold cyan] Hello! I am your CLI Agent assistant.")
        chat.write("[dim]Type a command or press [r] to run the demo simulation.[/dim]")

    # ── Keyboard / Action Handlers ──

    @on(Input.Submitted, "#cmd-input")
    def handle_command_input(self, event: Input.Submitted) -> None:
        """Handle user pressing Enter in the command input."""
        text = event.input.value.strip()
        if not text:
            return

        event.input.clear()
        self.log_system(f"Sent command: {text}", level="info")

        # Show user message in chat
        chat = self.query_one("#chat-log", RichLog)
        chat.write(f"[bold green]You:[/bold green] {text}")

        # Simple echo / command processing
        if text.lower() in ("exit", "quit"):
            self.exit()
        elif text.lower() == "help":
            chat.write(
                "[bold cyan]🦊 Agent:[/bold cyan]\n"
                "Available commands: `help`, `status`, `tasks`, `clear`, `demo`, `exit`"
            )
        elif text.lower() == "status":
            chat.write(f"[bold cyan]Status:[/bold cyan] {self.agent_status} | Active: {self.active_task_count}")
        elif text.lower() == "tasks":
            table = self.query_one("#task-table", DataTable)
            chat.write(f"[bold cyan]📋 {table.row_count} tasks in queue[/bold cyan]")
        elif text.lower() in ("clear", "cls"):
            chat.clear()
            self.log_system("Chat cleared by user", level="warn")
        elif text.lower() == "demo":
            self.run_demo_simulation()
        else:
            chat.write(f"[bold cyan]🦊 Agent:[/bold cyan] Received: `{text}`")
            chat.write("[dim]  (This is a demo — the agent will process your request in a real implementation.)[/dim]")

    def action_run_demo(self) -> None:
        """Run the demo simulation."""
        self.run_demo_simulation()

    def action_simulate_task(self) -> None:
        """Add a new simulated task to the table."""
        self._add_simulated_task()

    def action_clear_chat(self) -> None:
        """Clear the chat log."""
        self.query_one("#chat-log", RichLog).clear()

    def action_clear_logs(self) -> None:
        """Clear the system log."""
        self.query_one("#sys-log", RichLog).clear()

    @on(Button.Pressed, "#run-all-btn")
    def on_run_all(self, event: Button.Pressed) -> None:
        self.log_system("User pressed 'Run All'", level="info")
        self.run_demo_simulation()

    @on(Button.Pressed, "#stop-btn")
    def on_stop_all(self, event: Button.Pressed) -> None:
        self.log_system("User pressed 'Stop'", level="warn")
        self.agent_status = "IDLE"

    @on(Button.Pressed, "#reset-btn")
    def on_reset(self, event: Button.Pressed) -> None:
        self.log_system("User pressed 'Reset'", level="warn")
        self.agent_status = "IDLE"
        self.active_task_count = 0
        self.completed_tasks = 0
        self.query_one("#task-counter", TaskCounter).done = 0
        self.query_one("#task-counter", TaskCounter).total = 5

    @on(DataTable.RowSelected, "#task-table")
    def on_task_selected(self, event: DataTable.RowSelected) -> None:
        """Handle clicking a task row."""
        table = self.query_one("#task-table", DataTable)
        row = table.get_row(event.row_key)
        self.log_system(f"Selected task: {row[0]} - {row[1]} ({row[2]})", level="info")

    @on(Tree.NodeSelected, "#file-tree")
    def on_file_selected(self, event: Tree.NodeSelected) -> None:
        """Handle clicking a file node."""
        node = event.node
        label = str(node.label)
        self.log_system(f"File selected: {label}", level="info")

    # ── Reactive watcher ──

    def watch_agent_status(self, old: str, new: str) -> None:
        """Update the badge whenever agent_status changes."""
        badge = self.query_one("#agent-status", AgentStatusBadge)
        badge.status = new
        self.log_system(f"Agent status changed: {old} → {new}", level="info")

    def watch_active_task_count(self, old: int, new: int) -> None:
        """Update badge on active task count change."""
        badge = self.query_one("#agent-status", AgentStatusBadge)
        badge.active_tasks = new

    # ── Background Work ──

    def run_demo_simulation(self) -> None:
        """Kick off the async demo in the background."""
        if self._demo_messages:
            self._run_agent_demo()

    @work(exclusive=True, thread=False)
    async def _run_agent_demo(self) -> None:
        """Simulate an agent processing tasks with streaming output.

        Uses thread=False so all UI calls happen on the asyncio event loop,
        avoiding cross-thread issues with Textual's reactive system.
        """
        # Initialize reactive state (safe on same thread)
        self.agent_status = "WORKING"
        self.active_task_count = 3
        self.log_system("🚀 Demo simulation started", level="success")

        chat = self.query_one("#chat-log", RichLog)
        md = self.query_one("#md-output", Markdown)
        progress = self.query_one("#progress-bar", ProgressBar)

        progress.progress = 0
        md.update("")

        for i, (kind, content) in enumerate(self._demo_messages, 1):
            # Stream a small delay
            await asyncio.sleep(0.6 + random.random() * 0.4)

            if kind == "thinking":
                chat.write(f"[italic dim]* {content.strip()} *[/italic dim]")
            elif kind == "tool":
                chat.write(f"[bold yellow]🔧 Tool Call:[/bold yellow]\n{content}")
            elif kind == "response":
                chat.write(f"[bold cyan]🦊 Agent:[/bold cyan]")
                # Stream tokens one at a time
                tokens = content.split(" ")
                accumulated = ""
                for token in tokens:
                    accumulated += token + " "
                    # Use call_later to schedule on the main loop
                    partial = accumulated.strip()
                    chat.clear()
                    chat.write(partial)
                    await asyncio.sleep(0.02)
                chat.write("")  # newline separator

                # Also update the Markdown output tab
                md.update(content)

            # Update progress bar
            progress.progress = int((i / len(self._demo_messages)) * 100)

            # Update a task row (T-002..T-006; T-001 is already Done)
            table = self.query_one("#task-table", DataTable)
            row_key = f"T-00{i + 1}"
            status_options = ["✅ Done", "✅ Done", "🔄 Running"]
            # Check by looking up row; update_cell accepts string keys
            try:
                table.get_row(row_key)
                table.update_cell(row_key, "Status", status_options[i % 3])
                table.update_cell(row_key, "Progress", f"{min(i * 35, 100)}%")
            except KeyError:
                pass  # Row doesn't exist yet, skip silently

            # Update reactive counter on the UI thread directly
            counter = self.query_one("#task-counter", TaskCounter)
            new_done = min(i // 2, counter.total)
            if counter.done != new_done:
                counter.done = new_done

        await asyncio.sleep(0.3)
        # Final status
        self.agent_status = "DONE"
        self.active_task_count = 0
        self.completed_tasks += 1
        progress.progress = 100

        chat.write("")
        chat.write(
            "[bold green]✅ Demo complete![/bold green] "
            "All tasks processed successfully."
        )
        self.log_system("✅ Demo simulation finished", level="success")

        # Reset all task rows to show completion
        table = self.query_one("#task-table", DataTable)
        # Iterate over the known task IDs that were seeded
        all_task_ids = ["T-001", "T-002", "T-003", "T-004", "T-005"]
        for row_key in all_task_ids:
            try:
                table.get_row(row_key)
                table.update_cell(row_key, "Status", "✅ Done")
                table.update_cell(row_key, "Progress", "100%")
            except KeyError:
                pass
        # Final counter update (avoid no-op assignment)
        counter = self.query_one("#task-counter", TaskCounter)
        if counter.done != counter.total:
            counter.done = counter.total

    def _add_simulated_task(self) -> None:
        """Add a simulated task to the table."""
        table = self.query_one("#task-table", DataTable)
        task_id = f"T-{table.row_count + 1:03d}"
        tasks = [
            ("Code review PR #42", "⏳ Pending"),
            ("Update README", "⏳ Pending"),
            ("Fix failing test", "🔄 Running"),
            ("Optimize imports", "⏳ Pending"),
        ]
        task_name, status = random.choice(tasks)
        table.add_row(task_id, task_name, status, "0%", datetime.now().strftime("%H:%M"))

        counter = self.query_one("#task-counter", TaskCounter)
        counter.total += 1

        self.log_system(f"New task added: {task_id} - {task_name}", level="info")

    # ── Helpers ──

    def log_system(self, message: str, level: str = "info") -> None:
        """Write a timestamped log entry."""
        log = self.query_one("#sys-log", RichLog)
        ts = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "info": "white",
            "success": "green",
            "warn": "yellow",
            "error": "red",
        }
        color = color_map.get(level, "white")
        icon = {"info": "ℹ️", "success": "✅", "warn": "⚠️", "error": "❌"}.get(level, "•")
        log.write(f"[{color}]{ts} {icon} {message}[/{color}]")


# ── Entry Point ──
if __name__ == "__main__":
    app = CLI_Agent_App()
    app.run()
