"""Prompt handling, slash-command autocomplete, and @path file completion."""

import sys
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from buddyai.cli.theme import SLASH_COMMANDS, glyphs_for


class BuddyCompleter(Completer):
    """Completes `/` commands, and file paths after `@`, `/file ` or `/calendar `."""

    def __init__(self):
        self._path_completer = PathCompleter(expanduser=True)

    @staticmethod
    def _mention_before_cursor(text):
        """Return the path typed after an @ that starts the last word, or None."""
        at = text.rfind("@")
        if at == -1 or (at > 0 and not text[at - 1].isspace()):
            return None
        typed = text[at + 1:]
        if typed.startswith('"'):
            # Inside quotes a path may hold spaces, until the closing quote.
            return None if typed.count('"') > 1 else typed[1:]
        return None if " " in typed else typed

    def _complete_path(self, typed, complete_event):
        sub_doc = Document(text=typed, cursor_position=len(typed))
        yield from self._path_completer.get_completions(sub_doc, complete_event)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        mention = self._mention_before_cursor(text)
        if mention is not None:
            yield from self._complete_path(mention, complete_event)
            return
        if not text.startswith("/"):
            return

        for path_prefix in ("/file ", "/calendar "):
            if text.lower().startswith(path_prefix):
                yield from self._complete_path(text[len(path_prefix):], complete_event)
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
    """White user prompt with a dim model line underneath, history, and TTY fallback."""

    # How long the line under the prompt says which model BuddyAI switched from.
    SWITCH_NOTE_SECONDS = 30

    def __init__(self, get_model_name, interactive=None, clock=None):
        self._get_model_name = get_model_name
        self._clock = clock if clock is not None else time.monotonic
        self._shown_model = None
        self._switched_from = ""
        self._switched_at = None
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
                    # prompt_toolkit draws the toolbar in reverse video by
                    # default, which made it a solid bar; noreverse keeps it dim text.
                    "bottom-toolbar": "noreverse fg:#6c6c6c bg:default",
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
                bottom_toolbar=self.toolbar_text,
                # Redraw once a second so the switch note goes away on time.
                refresh_interval=1.0,
            )

    @property
    def interactive(self):
        return self._interactive

    def toolbar_text(self):
        """Return the line under the prompt: the model, plus a note after a switch.

        Commands are not listed here: /help and the autocomplete menu show them.
        """
        model = self._get_model_name()
        now = self._clock()
        if self._shown_model is not None and model != self._shown_model:
            self._switched_from = self._shown_model
            self._switched_at = now
        self._shown_model = model
        if (
            self._switched_at is not None
            and now - self._switched_at < self.SWITCH_NOTE_SECONDS
        ):
            return f"  {model} {self._glyphs['dot']} switched from {self._switched_from}"
        return f"  {model}"

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
