"""Rich terminal UI, live thinking spinner, and interactive /model picker."""

import os
import sys
import threading
import time

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.status import Status
from rich.table import Table
from rich.text import Text

from buddyai.cli.theme import (
    AGENT_STATUS_LABELS,
    MODEL_HINTS,
    RICH_THEME,
    SLASH_COMMANDS,
    build_mascot,
    glyphs_for,
    supports_unicode,
)
from buddyai.config import get_timezone_name
from buddyai.model_catalog import ModelCatalog


class ThinkingIndicator:
    """Context manager showing live agent activity and elapsed seconds."""

    def __init__(self, console, interactive, glyphs):
        self._console = console
        self._interactive = interactive
        self._glyphs = glyphs
        self._lock = threading.Lock()
        self._label = "Thinking…"
        self._agents = []
        self._start = 0.0
        self._elapsed = 0.0
        self._stop_event = threading.Event()
        self._thread = None
        self._status = None

    @property
    def elapsed(self):
        return self._elapsed

    @property
    def agents(self):
        with self._lock:
            return list(self._agents)

    def _formatted_text(self):
        with self._lock:
            label = self._label
        elapsed = time.monotonic() - self._start
        return Text(f" {label} ({elapsed:.1f}s)", style="cyan")

    @staticmethod
    def _label_for(stage, agent):
        if stage == "thinking":
            return "Thinking…"
        if stage == "reading_document":
            return "Reading document…"
        if stage == "searching_web":
            return "Searching the web…"
        if stage == "agent":
            if agent in AGENT_STATUS_LABELS:
                return AGENT_STATUS_LABELS[agent]
            return f"Calling {agent}…" if agent else "Working…"
        return stage

    def update(self, stage, agent=None):
        """Update the spinner status text from a plain stage key and record agents."""
        label = self._label_for(stage, agent) if stage else ""
        with self._lock:
            if label:
                self._label = label
            if agent and agent not in self._agents:
                self._agents.append(agent)
        if self._status is not None:
            self._status.update(self._formatted_text())

    def _tick(self):
        while not self._stop_event.wait(0.15):
            if self._status is not None:
                self._status.update(self._formatted_text())

    def __enter__(self):
        self._start = time.monotonic()
        if self._interactive:
            self._status = Status(
                self._formatted_text(),
                console=self._console,
                spinner="dots",
                spinner_style="cyan",
            )
            self._status.__enter__()
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._tick, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        if self._status is not None:
            self._status.__exit__(exc_type, exc, tb)
            self._status = None
        self._elapsed = time.monotonic() - self._start
        return False


class TerminalUI:
    """Handles all Rich/prompt_toolkit rendering for the BuddyAI CLI."""

    def __init__(self, console=None, interactive=None):
        self._interactive = (
            sys.stdin.isatty() and sys.stdout.isatty()
            if interactive is None
            else bool(interactive)
        )
        self._console = console or Console(
            theme=RICH_THEME,
            highlight=False,
            no_color=bool(os.environ.get("NO_COLOR")),
        )
        stream = getattr(self._console, "file", sys.stdout)
        self._unicode = supports_unicode(stream)
        self._glyphs = glyphs_for(stream)
        self._box = box.ROUNDED if self._unicode else box.ASCII

    @property
    def interactive(self):
        return self._interactive

    @property
    def console(self):
        return self._console

    @property
    def glyphs(self):
        return self._glyphs

    def thinking_context(self):
        """Return a context manager that displays live agent progress."""
        return ThinkingIndicator(self._console, self._interactive, self._glyphs)

    @staticmethod
    def _workspace_counts(app, now):
        """Compute current task, proposal, meeting, and note counts once."""
        return {
            "open_tasks": len(app.workspace.tasks.list_by_priority(now)),
            "proposals": len(app.workspace.tasks.list_proposals()),
            "meetings_today": len(app.workspace.agenda.meetings_on(now)),
            "notes": len(app.workspace.notebook.list_notes()),
        }

    def render_welcome(self, app):
        """Render the compact startup welcome card with the Hover Visor Bot mascot."""
        now = app.toolkit.current_time()
        counts = self._workspace_counts(app, now)
        open_tasks = counts["open_tasks"]
        proposals = counts["proposals"]
        meetings_today = counts["meetings_today"]
        notes_count = counts["notes"]
        tz_name = getattr(now.tzinfo, "key", None) or get_timezone_name()
        dot = self._glyphs["dot"]
        spark = self._glyphs["spark"]

        count_parts = [
            f"{open_tasks} open task{'s' if open_tasks != 1 else ''}",
            f"{meetings_today} meeting{'s' if meetings_today != 1 else ''} today",
            f"{notes_count} note{'s' if notes_count != 1 else ''}",
        ]
        if proposals:
            count_parts.append(
                f"{proposals} proposal{'s' if proposals != 1 else ''}"
            )

        info = Text()
        info.append(f"{spark} BuddyAI", style="buddy.header")
        info.append(f"  {dot}  Personal Executive Assistant\n", style="muted")
        info.append(f"{now.strftime('%a, %b %d')} {dot} {tz_name}\n", style="muted")
        info.append(f" {dot} ".join(count_parts) + "\n\n", style="muted")
        info.append(
            "Type a message, /help for commands, or /model to switch",
            style="muted",
        )

        layout = Table.grid(padding=(0, 3))
        layout.add_column(no_wrap=True)
        layout.add_column()
        layout.add_row(build_mascot(unicode_enabled=self._unicode), info)

        self._console.print(
            Panel(
                layout,
                box=self._box,
                border_style="border",
                padding=(0, 2),
                expand=False,
            )
        )

        startup_note = app.consume_startup_note()
        if startup_note:
            self.render_warn(startup_note)
        elif app.model_catalog.reason_for(app.current_model) == ModelCatalog.DAILY_LIMIT:
            self.render_warn(
                f"{app.current_model} has reached today's free request limit. "
                "Type /model to switch models."
            )

    def render_divider(self):
        """Render a subtle divider between conversation turns."""
        if self._interactive:
            self._console.print(Rule(style="border", characters=self._glyphs["rule"]))

    def render_buddy_reply(self, text, agents=None, elapsed=None):
        """Render BuddyAI's reply in colored cyan text with Markdown formatting."""
        spark = self._glyphs["spark"]
        branch = self._glyphs["branch"]
        dot = self._glyphs["dot"]

        header = Text()
        header.append(f"{spark} BuddyAI", style="buddy.header")
        meta = []
        if agents:
            meta.append(" -> ".join(agents))
        if elapsed is not None and elapsed >= 0.05:
            meta.append(f"{elapsed:.1f}s")
        if meta:
            header.append(f"   {branch} {f' {dot} '.join(meta)}", style="muted")

        self._console.print()
        self._console.print(header)
        cleaned = (text or "").strip()
        if cleaned:
            supports_osc8 = (
                self._console.is_terminal and not self._console.legacy_windows
            )
            self._console.print(
                Padding(
                    Markdown(cleaned, hyperlinks=supports_osc8),
                    (0, 0, 0, 2),
                )
            )
            if supports_osc8 and "](http" in cleaned:
                self._console.print(
                    Padding(
                        Text("Tip: Ctrl+Click a headline to open its link.", style="muted"),
                        (0, 0, 0, 2),
                    )
                )
        self._console.print()

    def render_ok(self, text):
        self._console.print(f"{self._glyphs['ok']} {text}", style="ok")

    def render_warn(self, text):
        self._console.print(f"{self._glyphs['warn']} {text}", style="warn")

    def render_error(self, text):
        self._console.print(f"{self._glyphs['err']} {text}", style="err")

    def render_muted(self, text):
        self._console.print(text, style="muted")

    def pick_model_interactive(self, app):
        """Show an interactive /model selector (or plain list when non-TTY)."""
        app.sync_model_limits()
        catalog = app.model_catalog
        if not self._interactive:
            self._console.print(catalog.describe(), style="buddy.text")
            return None

        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style

        names = catalog.names
        if not names:
            self.render_warn("No models are configured.")
            return None

        state = {
            "index": names.index(app.current_model) if app.current_model in names else 0,
            "result": None,
        }
        prompt_char = self._glyphs["prompt"]

        def _render_rows():
            fragments = [
                (
                    "class:title",
                    "  Select a Gemini model  (↑/↓ move · 1-9 jump · Enter select · Esc cancel)\n\n",
                )
            ]
            for idx, name in enumerate(names):
                selected = idx == state["index"]
                cursor = f"  {prompt_char} " if selected else "    "
                row_style = "class:selected" if selected else "class:item"
                fragments.append((row_style, f"{cursor}{idx + 1}. {name}"))

                badges = []
                if name == app.current_model:
                    badges.append(("class:active", " [active]"))
                hint = MODEL_HINTS.get(name, "")
                if hint:
                    badges.append(("class:hint", f"  {hint}"))
                reason = catalog.reason_for(name)
                if reason:
                    badges.append(("class:limit", f"  [{reason}]"))
                fragments.extend(badges)
                fragments.append(("", "\n"))
            return fragments

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event):
            state["index"] = (state["index"] - 1) % len(names)

        @kb.add("down")
        @kb.add("j")
        def _down(event):
            state["index"] = (state["index"] + 1) % len(names)

        @kb.add("enter")
        def _select(event):
            state["result"] = names[state["index"]]
            event.app.exit()

        @kb.add("escape")
        @kb.add("c-c")
        def _cancel(event):
            state["result"] = None
            event.app.exit()

        for num in range(1, min(len(names), 9) + 1):
            @kb.add(str(num))
            def _pick_digit(event, pos=num - 1):
                state["result"] = names[pos]
                event.app.exit()

        picker_style = Style.from_dict(
            {
                "title": "fg:#94a3b8",
                "selected": "fg:#67e8f9 bold",
                "item": "fg:#e2e8f0",
                "active": "fg:#4ade80 bold",
                "hint": "fg:#64748b",
                "limit": "fg:#fbbf24",
            }
        )
        application = Application(
            layout=Layout(Window(FormattedTextControl(_render_rows))),
            key_bindings=kb,
            style=picker_style,
            full_screen=False,
            erase_when_done=True,
        )
        application.run()
        return state["result"]

    def render_help(self):
        """Render the formatted slash-command reference table."""
        table = Table(
            title=f"{self._glyphs['spark']} Commands",
            title_style="buddy.header",
            box=self._box,
            border_style="border",
            header_style="buddy.header",
        )
        table.add_column("Command", style="bright_white", no_wrap=True)
        table.add_column("Description", style="buddy.text")
        for cmd, desc in SLASH_COMMANDS:
            table.add_row(cmd, desc)
        self._console.print(table)

    def render_status(self, app):
        """Render current session and workspace counts."""
        app.sync_model_limits()
        now = app.toolkit.current_time()
        tz_name = getattr(now.tzinfo, "key", None) or get_timezone_name()
        counts = self._workspace_counts(app, now)
        open_tasks = counts["open_tasks"]
        proposals = counts["proposals"]
        meetings_today = counts["meetings_today"]
        notes_count = counts["notes"]

        reason = app.model_catalog.reason_for(app.current_model)
        model_text = app.current_model + (f" ({reason})" if reason else "")

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="muted")
        grid.add_column(style="buddy.text")
        grid.add_row("Active model:", model_text)
        grid.add_row("Timezone:", tz_name)
        grid.add_row("Open tasks:", str(open_tasks))
        grid.add_row("Pending proposals:", str(proposals))
        grid.add_row("Meetings today:", str(meetings_today))
        grid.add_row("Saved notes:", str(notes_count))
        cal_source = getattr(app, "calendar_source", None)
        if cal_source is not None:
            cal_text = (
                f"{os.path.basename(cal_source.path)} "
                f"({cal_source.loaded_count} events)"
            )
        else:
            cal_text = "none"
        grid.add_row("Calendar file:", cal_text)

        self._console.print(
            Panel(
                grid,
                title=f"{self._glyphs['spark']} Session Status",
                title_align="left",
                box=self._box,
                border_style="border",
                expand=False,
            )
        )

    def render_tasks(self, app):
        """Render open tasks sorted by priority, plus any pending proposals."""
        now = app.toolkit.current_time()
        open_tasks = app.workspace.tasks.list_by_priority(now)
        proposals = app.workspace.tasks.list_proposals()

        if not open_tasks and not proposals:
            self.render_muted("No open tasks or pending proposals.")
            return

        if open_tasks:
            table = Table(
                title=f"{self._glyphs['spark']} Open Tasks",
                title_style="buddy.header",
                box=self._box,
                border_style="border",
                header_style="buddy.header",
            )
            table.add_column("ID", style="muted", no_wrap=True)
            table.add_column("Title", style="buddy.text")
            table.add_column("Priority", style="bright_cyan", no_wrap=True)
            table.add_column("Due", style="muted", no_wrap=True)
            for task in open_tasks:
                due_text = (
                    task.due_date.strftime("%Y-%m-%d %H:%M")
                    if task.due_date is not None
                    else "-"
                )
                table.add_row(task.item_id, task.title, str(task.priority), due_text)
            self._console.print(table)

        if proposals:
            prop_table = Table(
                title="Pending Proposals (waiting for confirmation)",
                title_style="warn",
                box=self._box,
                border_style="border",
                header_style="warn",
            )
            prop_table.add_column("ID", style="muted", no_wrap=True)
            prop_table.add_column("Title", style="buddy.text")
            for task in proposals:
                prop_table.add_row(task.item_id, task.title)
            self._console.print(prop_table)

    def render_brief(self, app, target_now=None, weather_at=None, location=None):
        """Render the daily briefing locally in the same Markdown format as chat replies."""
        now = target_now if target_now is not None else app.toolkit.current_time()
        resolved_weather_at = weather_at if weather_at is not None else now
        if self._interactive:
            with Status(
                Text(" Building daily briefing…", style="cyan"),
                console=self._console,
                spinner="dots",
                spinner_style="cyan",
            ):
                briefing = app.briefing_service.build_briefing(
                    now,
                    location=location,
                    weather_at=resolved_weather_at,
                )
        else:
            briefing = app.briefing_service.build_briefing(
                now,
                location=location,
                weather_at=resolved_weather_at,
            )
        self.render_buddy_reply(briefing.to_text())

    def clear_and_reset(self, app):
        """Clear the terminal and redraw the compact welcome card."""
        if self._interactive:
            self._console.clear()
        self.render_welcome(app)
