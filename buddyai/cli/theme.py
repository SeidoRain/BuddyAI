"""Visual theme, slash-command catalog, and terminal capability helpers."""

import sys

from rich.theme import Theme

SLASH_COMMANDS = [
    ("/model", "Switch Gemini model"),
    ("/file", "Attach a PDF, PNG, JPG, or TXT file"),
    ("/brief", "Show today's daily briefing (instant)"),
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

THEME = RICH_THEME

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
