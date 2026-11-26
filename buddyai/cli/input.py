"""Prompt handling, slash-command autocomplete, and /file path completion."""

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from buddyai.cli.theme import SLASH_COMMANDS, glyphs_for


class BuddyCompleter(Completer):
    """Completes `/` commands and local file paths after `/file `."""

    def __init__(self):
        self._path_completer = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        for path_prefix in ("/file ", "/calendar "):
            if text.lower().startswith(path_prefix):
                remainder = text[len(path_prefix):]
                sub_doc = Document(text=remainder, cursor_position=len(remainder))
                for completion in self._path_completer.get_completions(
                    sub_doc, complete_event
                ):
                    yield completion
                return

        prefix = text.lower()
        for cmd, desc in SLASH_COMMANDS:
            if cmd.startswith(prefix):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=desc,
                )


class BuddyPrompt:
    """White user prompt with bottom status bar, history, and TTY fallback."""

    def __init__(self, get_model_name, interactive=None):
        self._get_model_name = get_model_name
        self._interactive = (
            sys.stdin.isatty() and sys.stdout.isatty()
            if interactive is None
            else bool(interactive)
        )
        self._glyphs = glyphs_for(sys.stdout)
        self._session = None
        if self._interactive:
            style = Style.from_dict(
                {
                    "prompt": "fg:#ffffff bold",
                    "": "fg:#ffffff",
                    "bottom-toolbar": "fg:#8a8a8a bg:default",
                    "completion-menu.completion": "bg:#1e2430 fg:#d8dee9",
                    "completion-menu.completion.current": "bg:#0891b2 fg:#ffffff bold",
                    "completion-menu.meta.completion": "bg:#1e2430 fg:#8a8a8a",
                    "completion-menu.meta.completion.current": "bg:#0891b2 fg:#e0f2fe",
                }
            )
            self._session = PromptSession(
                history=InMemoryHistory(),
                completer=BuddyCompleter(),
                complete_while_typing=True,
                style=style,
                bottom_toolbar=self._bottom_toolbar,
            )

    @property
    def interactive(self):
        return self._interactive

    def _bottom_toolbar(self):
        bar = "|" if self._glyphs["rule"] == "-" else "│"
        dot = self._glyphs["dot"]
        model = self._get_model_name()
        return (
            f"  {model}  {bar}  /model  /file  /brief  /tasks  /help  {bar}  "
            f"Ctrl+C cancel {dot} /quit"
        )

    def read_input(self, default=""):
        """Read and strip a single line of user input, optionally pre-filled."""
        if self._session is not None:
            text = self._session.prompt(
                [("class:prompt", f"\n{self._glyphs['prompt']} ")],
                default=default,
            )
            return text.strip()
        if default:
            return default.strip()
        return input("\nYou> ").strip()
