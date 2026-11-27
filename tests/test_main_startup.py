"""Unit tests for main.py startup error handling on corrupt data files."""

from io import StringIO
import logging
import os
import tempfile
import unittest
from unittest import mock

from rich.console import Console

import main
from buddyai.cli import RICH_THEME, TerminalUI
from buddyai.sources import JsonStore


class TestMainStartupErrors(unittest.TestCase):
    """Checks that damaged data files produce a clear message instead of a traceback."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.buffer = StringIO()
        console = Console(
            file=self.buffer,
            theme=RICH_THEME,
            highlight=False,
            no_color=True,
            width=200,
        )
        self.ui = TerminalUI(console=console, interactive=False)

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_corrupt_tasks_file_returns_one_and_leaves_file_untouched(self):
        tasks_path = os.path.join(self._tmp.name, JsonStore.TASKS_FILE)
        with open(tasks_path, "w", encoding="utf-8") as handle:
            handle.write("{bad json")

        env = {
            "BUDDYAI_DATA_DIR": self._tmp.name,
            "GOOGLE_API_KEY": "test-dummy-key",
        }
        with (
            mock.patch.dict(os.environ, env, clear=False),
            mock.patch.object(main, "load_dotenv"),
            mock.patch.object(main, "TerminalUI", return_value=self.ui),
        ):
            code = main.main()

        output = self.buffer.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("DataSourceError", output)
        self.assertIn("tasks.json", output)
        with open(tasks_path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{bad json")

    def test_invalid_record_in_tasks_file_returns_one_without_traceback(self):
        tasks_path = os.path.join(self._tmp.name, JsonStore.TASKS_FILE)
        with open(tasks_path, "w", encoding="utf-8") as handle:
            handle.write('[{"title": "", "created_at": "not-a-date"}]')

        env = {
            "BUDDYAI_DATA_DIR": self._tmp.name,
            "GOOGLE_API_KEY": "test-dummy-key",
        }
        with (
            mock.patch.dict(os.environ, env, clear=False),
            mock.patch.object(main, "load_dotenv"),
            mock.patch.object(main, "TerminalUI", return_value=self.ui),
        ):
            code = main.main()

        output = self.buffer.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("InvalidInputError", output)

    def test_a_damaged_file_message_says_to_fix_the_file(self):
        with open(os.path.join(self._tmp.name, JsonStore.TASKS_FILE), "w") as handle:
            handle.write("{bad json")
        self.assertEqual(self._run_main(), 1)
        self.assertIn("Fix or remove the file named above", self.buffer.getvalue())

    def test_a_bad_timezone_setting_stops_cleanly_with_a_settings_hint(self):
        self.assertEqual(self._run_main({"BUDDYAI_TIMEZONE": "Asia"}), 1)
        output = self.buffer.getvalue()
        self.assertIn("InvalidInputError: Unknown timezone 'Asia'.", output)
        self.assertIn("Check your settings in buddy_agent/.env", output)
        self.assertNotIn("Fix or remove the file", output)

    def _run_main(self, extra_env=None):
        env = {
            "BUDDYAI_DATA_DIR": self._tmp.name,
            "BUDDYAI_ICS_FILE": "",
            "GOOGLE_API_KEY": "test-dummy-key",
        }
        env.update(extra_env or {})
        with (
            mock.patch.dict(os.environ, env, clear=False),
            mock.patch.object(main, "load_dotenv"),
            mock.patch.object(main, "TerminalUI", return_value=self.ui),
        ):
            return main.main()


class _ScriptedPrompt:
    """Stands in for BuddyPrompt: returns the given lines, then acts like Ctrl+Z."""

    def __init__(self, lines):
        self._lines = list(lines)

    def read_input(self, default=""):
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


class TestMainLoopSafetyNet(unittest.TestCase):
    """Checks that one failing command is reported and the chat keeps going."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.buffer = StringIO()
        console = Console(
            file=self.buffer,
            theme=RICH_THEME,
            highlight=False,
            no_color=True,
            width=200,
        )
        self.ui = TerminalUI(console=console, interactive=False)

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def _run_lines(self, lines, handle_effects):
        """Run main() on scripted lines while CommandRouter.handle gives `handle_effects`."""
        env = {
            "BUDDYAI_DATA_DIR": self._tmp.name,
            "BUDDYAI_ICS_FILE": "",
            "GOOGLE_API_KEY": "test-dummy-key",
        }
        with (
            mock.patch.dict(os.environ, env, clear=False),
            mock.patch.object(main, "load_dotenv"),
            mock.patch.object(main, "TerminalUI", return_value=self.ui),
            mock.patch.object(main, "BuddyPrompt", return_value=_ScriptedPrompt(lines)),
            mock.patch.object(main.CommandRouter, "handle", side_effect=handle_effects),
        ):
            return main.main()

    def test_an_unexpected_error_is_shown_in_one_line_and_the_chat_goes_on(self):
        code = self._run_lines(
            ["/tasks", "/quit"], [RuntimeError("boom"), main.CommandRouter.EXIT]
        )
        self.assertEqual(code, 0)
        output = self.buffer.getvalue()
        self.assertIn("RuntimeError: boom (the details are in buddyai.log)", output)
        self.assertNotIn("Traceback", output)

    def test_ctrl_c_during_a_command_says_cancelled_and_the_chat_goes_on(self):
        code = self._run_lines(
            ["/brief", "/quit"], [KeyboardInterrupt(), main.CommandRouter.EXIT]
        )
        self.assertEqual(code, 0)
        self.assertIn("Cancelled.", self.buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
