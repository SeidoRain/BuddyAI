"""Unit tests for the /calendar terminal command, completer, and status display."""

from datetime import datetime
from io import StringIO
import logging
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from google.adk.models.base_llm import BaseLlm
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from buddyai.app import BuddyApp
from buddyai.cli import BuddyCompleter, CommandRouter, RICH_THEME, TerminalUI
from sample_data.make_sample_data import write_calendar_file

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=MANILA)


class _DummyLlm(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        if False:
            yield


class TestCalendarCommand(unittest.TestCase):
    """Verifies /calendar routing, quotes, errors, unloading, status, and completion."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self._tmp.name, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.ics_path = write_calendar_file(self._tmp.name, NOW.date())

        self.app = BuddyApp(
            data_dir=self.data_dir,
            model=_DummyLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
            ics_file="",
        )
        self.buffer = StringIO()
        console = Console(
            file=self.buffer,
            theme=RICH_THEME,
            highlight=False,
            no_color=True,
            width=200,
        )
        self.ui = TerminalUI(console=console, interactive=False)
        self.router = CommandRouter(self.app, self.ui)

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def output(self):
        return self.buffer.getvalue()

    def test_calendar_with_no_argument_and_none_loaded_shows_hint(self):
        self.assertEqual(self.router.handle("/calendar"), CommandRouter.HANDLED)
        self.assertIn("No calendar file loaded", self.output())

    def test_calendar_with_path_loads_events_and_prints_counts(self):
        self.assertEqual(
            self.router.handle(f"/calendar {self.ics_path}"), CommandRouter.HANDLED
        )
        out = self.output()
        self.assertIn("5 events loaded", out)
        self.assertIn("1 recurring, first occurrence only", out)
        self.assertIn("1 all-day events skipped", out)
        self.assertIn("1 skipped as unreadable", out)
        self.assertIsNotNone(self.app.calendar_source)

    def test_calendar_with_quoted_path_containing_spaces_loads_file(self):
        spaced_dir = os.path.join(self._tmp.name, "my calendar folder")
        spaced_ics = write_calendar_file(spaced_dir, NOW.date())
        self.assertEqual(
            self.router.handle(f'/calendar "{spaced_ics}"'), CommandRouter.HANDLED
        )
        self.assertIn("5 events loaded", self.output())
        self.assertEqual(self.app.calendar_source.path, os.path.abspath(spaced_ics))

    def test_calendar_with_missing_path_shows_error_and_keeps_previous_calendar(self):
        self.router.handle(f"/calendar {self.ics_path}")
        self.buffer.truncate(0)
        self.buffer.seek(0)

        missing = os.path.join(self._tmp.name, "does_not_exist.ics")
        self.router.handle(f"/calendar {missing}")
        self.assertIn("DataSourceError", self.output())
        self.assertIsNotNone(self.app.calendar_source)
        self.assertEqual(self.app.calendar_source.path, os.path.abspath(self.ics_path))
        self.assertEqual(len(self.app.workspace.agenda.list_meetings()), 5)

    def test_calendar_off_removes_loaded_calendar(self):
        self.router.handle(f"/calendar {self.ics_path}")
        self.buffer.truncate(0)
        self.buffer.seek(0)

        self.router.handle("/calendar off")
        self.assertIsNone(self.app.calendar_source)
        self.assertEqual(self.app.workspace.agenda.list_meetings(), [])
        self.assertIn("Calendar file removed", self.output())

    def test_status_shows_calendar_file_row(self):
        self.router.handle("/status")
        self.assertIn("Calendar file:", self.output())
        self.assertIn("none", self.output())

        self.buffer.truncate(0)
        self.buffer.seek(0)
        self.router.handle(f"/calendar {self.ics_path}")
        self.router.handle("/status")
        self.assertIn("sample_calendar.ics (5 events)", self.output())

    def test_completer_offers_paths_after_calendar_command(self):
        completer = BuddyCompleter()
        prefix = os.path.join(self._tmp.name, "sample")
        doc = Document(text=f"/calendar {prefix}", cursor_position=len(f"/calendar {prefix}"))
        results = list(completer.get_completions(doc, CompleteEvent()))
        self.assertTrue(any("calendar.ics" in c.text for c in results))


if __name__ == "__main__":
    unittest.main()
