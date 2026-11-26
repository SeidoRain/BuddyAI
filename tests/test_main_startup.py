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


if __name__ == "__main__":
    unittest.main()
