"""Visual theme, slash-command catalog, and terminal capability helpers."""

import sys

from rich.text import Text
from rich.theme import Theme

SLASH_COMMANDS = [
    ("/model", "Switch Gemini model"),
    ("/file", "Attach a PDF, PNG, JPG, or TXT file"),
    ("/calendar", "Load or show a calendar (.ics) file"),
    ("/live", "BuddyAI Live: two-way voice chat (/live barge for headphones)"),
    ("/voice", "Dictate a message into the text prompt (voice-to-text)"),
    ("/task", "add | edit | delete a task, no AI call (type /task for the formats)"),
    ("/meet", "add | move | edit | cancel a meeting, no AI call (type /meet for the formats)"),
    ("/done", "Mark a task done by id or title, no AI call"),
    ("/brief", "Show daily briefing: schedule, weather & top 5 PH news"),
    ("/tasks", "Show open tasks & proposals (instant)"),
    ("/status", "Show session & workspace summary"),
    ("/clear", "Clear screen and show header"),
    ("/help", "Show available commands"),
    ("/quit", "Exit BuddyAI"),
]

# Shown only inside the interactive /model picker.
MODEL_HINTS = {
    "gemini-3.5-flash-lite": "500/day · default",
    "gemini-3.6-flash": "20/day",
    "gemini-3.8-flash": "20/day",
    "gemini-4-hydrogen": "20/day",
    "gemini-3.1-flash-lite": "500/day · backup",
}

# Spinner labels for specialist agents while a chat turn is running.
AGENT_STATUS_LABELS = {
    "task_agent": "Checking tasks…",
    "schedule_agent": "Checking schedule…",
    "notes_agent": "Working with notes…",
    "briefing_agent": "Building daily briefing…",
}

RICH_THEME = Theme(
    {
        "buddy.text": "cyan",
        "buddy.header": "bold bright_cyan",
        "user.prompt": "bold bright_white",
        "user.text": "bright_white",
        "muted": "grey62",
        "border": "grey42",
        "ok": "green",
        "warn": "yellow",
        "err": "red",
        "markdown.paragraph": "cyan",
        "markdown.text": "cyan",
        "markdown.item": "cyan",
        "markdown.item.bullet": "bright_cyan",
        "markdown.item.number": "bright_cyan",
        "markdown.strong": "bold bright_cyan",
        "markdown.em": "italic cyan",
        "markdown.h1": "bold bright_cyan",
        "markdown.h2": "bold bright_cyan",
        "markdown.h3": "bold cyan",
        "markdown.code": "bold cyan on grey19",
        "markdown.code_block": "cyan",
        "markdown.link": "underline bright_cyan",
        "markdown.link_url": "cyan",
    }
)

_UNICODE_GLYPHS = {
    "spark": "✦",
    "prompt": "❯",
    "ok": "✓",
    "warn": "⚠",
    "err": "✕",
    "branch": "↳",
    "dot": "·",
    "rule": "─",
}

_ASCII_GLYPHS = {
    "spark": "*",
    "prompt": ">",
    "ok": "[ok]",
    "warn": "[!]",
    "err": "[x]",
    "branch": "->",
    "dot": "|",
    "rule": "-",
}


def supports_unicode(stream=None):
    """Return True when the output stream encoding supports UTF-8 box/icon glyphs."""
    target = stream if stream is not None else sys.stdout
    encoding = (getattr(target, "encoding", None) or "").lower()
    return "utf" in encoding


def glyphs_for(stream=None):
    """Return Unicode or ASCII fallback glyphs appropriate for `stream`."""
    return dict(_UNICODE_GLYPHS if supports_unicode(stream) else _ASCII_GLYPHS)


def build_mascot(unicode_enabled=True):
    """Return the Hover Visor Bot mascot (a small robot face) as styled Rich Text."""
    mascot = Text(no_wrap=True)
    if unicode_enabled:
        mascot.append("    ▄▀▄    \n", style="bold bright_cyan")
        mascot.append(" ▄███████▄ \n", style="cyan")
        mascot.append("▐█ ", style="cyan")
        mascot.append("▀▀ ▀▀", style="bold bright_white")
        mascot.append(" █▌\n", style="cyan")
        mascot.append(" ▀█▄▄▄▄▄█▀ \n", style="cyan")
        mascot.append("   ▄▄▄▄▄   ", style="dim cyan")
    else:
        mascot.append("    /^\\    \n", style="bold bright_cyan")
        mascot.append("  .-----.  \n", style="cyan")
        mascot.append(" |[ ", style="cyan")
        mascot.append("o o", style="bold bright_white")
        mascot.append(" ]| \n", style="cyan")
        mascot.append("  '-----'  \n", style="cyan")
        mascot.append("    ===    ", style="dim cyan")
    return mascot
