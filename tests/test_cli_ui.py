"""Unit tests for the revamped BuddyAI CLI UI, completer, and status hooks."""

from datetime import datetime, timedelta
from io import StringIO
import logging
import os
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from buddyai.app import BuddyApp, CommandReply
from buddyai.cli import (
    BuddyCompleter,
    CommandRouter,
    RICH_THEME,
    TerminalUI,
    build_mascot,
)
from buddyai.exceptions import DataSourceError
from buddyai.models import Meeting, Task
from buddyai.web_lookup import WebLookup

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=MANILA)


class _StatusTestLlm(BaseLlm):
    """Fake LLM that returns a plain text answer."""

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=f"ok from {llm_request.model}")],
            )
        )


def _capture_ui(force_terminal=False, no_color=True, interactive=False):
    buf = StringIO()
    console = Console(
        file=buf,
        theme=RICH_THEME,
        highlight=False,
        force_terminal=force_terminal,
        color_system="truecolor" if (force_terminal and not no_color) else None,
        no_color=no_color,
        width=100,
    )
    return TerminalUI(console=console, interactive=interactive), buf


class TestBuddyAppCliHooks(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)      # keeps ADK's own warnings out of the test output
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_ask_accepts_on_status_and_works_without_it(self):
        app = BuddyApp(
            data_dir=self._tmp.name,
            model=_StatusTestLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
        )
        try:
            events = []
            reply = app.ask("hi", on_status=lambda stage, agent=None: events.append((stage, agent)))
            self.assertEqual(reply, "ok from gemini-3.5-flash-lite")
            self.assertGreaterEqual(len(events), 1)
            self.assertEqual(events[0], ("thinking", None))
            self.assertEqual(app.ask("hi again"), "ok from gemini-3.5-flash-lite")
        finally:
            app.close()

    def test_consume_startup_note_leaves_startup_notice_intact(self):
        app = BuddyApp(
            data_dir=self._tmp.name,
            model=_StatusTestLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
        )
        try:
            self.assertEqual(
                app.startup_notice(),
                "Model: gemini-3.5-flash-lite (type /model to switch)",
            )
            self.assertEqual(app.consume_startup_note(), "")
        finally:
            app.close()


class TestTerminalUI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app = BuddyApp(
            data_dir=self._tmp.name,
            model=_StatusTestLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
            web_lookup=WebLookup(fetcher=self._offline_fetcher),
        )

    @staticmethod
    def _offline_fetcher(url):
        raise DataSourceError("offline in unit test")

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()

    def test_welcome_card_hides_other_models(self):
        ui, buf = _capture_ui()
        ui.render_welcome(self.app)
        output = buf.getvalue()
        self.assertIn("BuddyAI", output)
        self.assertIn("open task", output)
        self.assertIn("o o", output)
        for hidden_model in (
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-4-hydrogen",
            "gemini-3.1-flash-lite",
        ):
            self.assertNotIn(hidden_model, output)

    def test_mascot_supports_unicode_and_ascii_fallback(self):
        unicode_art = build_mascot(unicode_enabled=True).plain
        self.assertIn("▄▀▄", unicode_art)
        self.assertIn("▐█ ▀▀ ▀▀ █▌", unicode_art)
        self.assertIn("▄▄▄▄▄", unicode_art)

        ascii_art = build_mascot(unicode_enabled=False).plain
        self.assertIn("/^\\", ascii_art)
        self.assertIn("|[ o o ]|", ascii_art)
        self.assertIn("===", ascii_art)

    def test_reply_renders_header_trace_and_ansi_color_when_enabled(self):
        colored_ui, colored_buf = _capture_ui(force_terminal=True, no_color=False)
        colored_ui.render_buddy_reply(
            "Hello **world**\n\n- item one",
            agents=["task_agent"],
            elapsed=1.2,
        )
        colored_out = colored_buf.getvalue()
        self.assertIn("BuddyAI", colored_out)
        self.assertIn("task_agent", colored_out)
        self.assertIn("1.2s", colored_out)
        self.assertIn("\x1b[", colored_out)

        plain_ui, plain_buf = _capture_ui(force_terminal=False, no_color=True)
        plain_ui.render_buddy_reply("Plain **reply**")
        plain_out = plain_buf.getvalue()
        self.assertIn("BuddyAI", plain_out)
        self.assertIn("Plain reply", plain_out)
        self.assertNotIn("\x1b[", plain_out)

    def test_help_status_tasks_and_brief_render_cleanly(self):
        self.app.workspace.tasks.add_task(
            Task(title="Submit report", created_at=NOW, due_date=NOW + timedelta(hours=3), priority=1),
            NOW,
        )
        self.app.workspace.tasks.propose(
            Task(title="Review notes", created_at=NOW, status="proposed")
        )
        self.app.workspace.agenda.schedule(
            Meeting(
                title="Team sync",
                created_at=NOW,
                start=NOW + timedelta(hours=1),
                end=NOW + timedelta(hours=2),
            ),
            NOW,
        )

        ui, buf = _capture_ui()
        ui.render_help()
        ui.render_status(self.app)
        ui.render_tasks(self.app)
        ui.render_brief(self.app)
        output = buf.getvalue()

        self.assertIn("/model", output)
        self.assertIn("/brief", output)
        self.assertIn("Session Status", output)
        self.assertIn("Submit report", output)
        self.assertIn("Review notes", output)
        self.assertIn("Team sync", output)

    def test_render_brief_emits_osc8_clickable_links_on_modern_terminal(self):
        def _live_fetcher(url):
            if "geocoding-api.open-meteo.com" in url:
                return '{"results": [{"name": "Manila", "admin1": "Metro Manila", "country": "Philippines", "latitude": 14.6, "longitude": 120.98}]}'
            if "api.open-meteo.com" in url:
                return (
                    '{"timezone": "Asia/Manila",'
                    ' "current": {"time": "2026-11-26T10:00", "temperature_2m": 29.0,'
                    '  "apparent_temperature": 32.0, "relative_humidity_2m": 65,'
                    '  "weather_code": 1, "wind_speed_10m": 8.0},'
                    ' "daily": {"time": ["2026-11-26"], "temperature_2m_max": [34.0],'
                    '  "temperature_2m_min": [25.0], "precipitation_probability_max": [30]}}'
                )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<rss version="2.0"><channel>'
                '<item><title>Top PH Story - Inquirer</title><link>https://example.com/story1</link><source>Inquirer</source></item>'
                '</channel></rss>'
            )

        app = BuddyApp(
            data_dir=self._tmp.name,
            model=_StatusTestLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
            web_lookup=WebLookup(fetcher=_live_fetcher),
        )
        try:
            buf = StringIO()
            console = Console(
                file=buf,
                theme=RICH_THEME,
                highlight=False,
                force_terminal=True,
                color_system="truecolor",
                legacy_windows=False,
                width=120,
            )
            ui = TerminalUI(console=console, interactive=False)
            ui.render_brief(app)
            brief_output = buf.getvalue()
            self.assertIn("\x1b]8;", brief_output)
            self.assertIn("https://example.com/story1", brief_output)
            self.assertIn("Top PH Story - Inquirer", brief_output)
            self.assertIn("Ctrl+Click", brief_output)

            # Asking in chat renders the exact same Markdown briefing format as /brief.
            chat_buf = StringIO()
            chat_console = Console(
                file=chat_buf,
                theme=RICH_THEME,
                highlight=False,
                force_terminal=True,
                color_system="truecolor",
                legacy_windows=False,
                width=120,
            )
            chat_ui = TerminalUI(console=chat_console, interactive=False)
            chat_ui.render_buddy_reply(app.toolkit.get_daily_briefing()["briefing_text"])
            self.assertEqual(
                brief_output.replace("id=", "").split("https://")[1:],
                chat_buf.getvalue().replace("id=", "").split("https://")[1:],
            )
        finally:
            app.close()

    def test_pick_model_interactive_non_tty_lists_models_and_returns_none(self):
        ui, buf = _capture_ui(interactive=False)
        chosen = ui.pick_model_interactive(self.app)
        self.assertIsNone(chosen)
        output = buf.getvalue()
        self.assertIn("1. gemini-3.5-flash-lite", output)
        self.assertIn("2. gemini-3.1-flash-lite", output)
        self.assertIn("5. gemini-4-hydrogen", output)


class TestBuddyCompleter(unittest.TestCase):
    def test_completes_slash_commands_and_file_paths(self):
        completer = BuddyCompleter()
        event = CompleteEvent()

        root_matches = [c.text for c in completer.get_completions(Document("/"), event)]
        self.assertIn("/model", root_matches)
        self.assertIn("/brief", root_matches)

        mo_matches = [c.text for c in completer.get_completions(Document("/mo"), event)]
        self.assertEqual(mo_matches, ["/model"])

        with tempfile.TemporaryDirectory() as tmpdir:
            sample = os.path.join(tmpdir, "agenda.txt")
            with open(sample, "w", encoding="utf-8") as handle:
                handle.write("test")
            prefix = os.path.join(tmpdir, "ag")
            file_matches = [
                c.text
                for c in completer.get_completions(Document(f"/file {prefix}"), event)
            ]
            self.assertTrue(any("enda.txt" in text for text in file_matches))

    def test_completes_task_and_meet_but_not_their_arguments(self):
        completer = BuddyCompleter()
        event = CompleteEvent()

        for typed, expected in (("/ta", ["/task", "/tasks"]), ("/me", ["/meet"])):
            matches = [c.text for c in completer.get_completions(Document(typed), event)]
            self.assertEqual(matches, expected)

        after_command = completer.get_completions(Document("/task add Buy milk"), event)
        self.assertEqual(list(after_command), [])


class TestCommandReplyAndStatusMapping(unittest.TestCase):
    """Checks CommandReply severity levels and ThinkingIndicator stage-to-label mapping."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.app = BuddyApp(
            data_dir=self._tmp.name,
            model=_StatusTestLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
            ics_file="",
        )

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_run_model_command_returns_info_level_when_listing_models(self):
        reply = self.app.run_model_command("/model")
        self.assertIsInstance(reply, CommandReply)
        self.assertEqual(reply.level, "info")
        self.assertIn("gemini-3.5-flash-lite", reply.text)

    def test_run_model_command_returns_ok_level_on_valid_switch(self):
        reply = self.app.run_model_command("/model 2")
        self.assertEqual(reply.level, "ok")
        self.assertIn("Switched to", reply.text)

    def test_run_model_command_returns_warn_level_for_daily_limited_model(self):
        self.app._limit_log.record("gemini-3.6-flash")
        reply = self.app.run_model_command("/model gemini-3.6-flash")
        self.assertEqual(reply.level, "warn")

    def test_run_model_command_returns_error_level_for_unknown_model(self):
        reply = self.app.run_model_command("/model nonexistent-xyz")
        self.assertEqual(reply.level, "error")

    def test_router_renders_model_switch_using_reply_level(self):
        ui, _ = _capture_ui(interactive=False)
        router = CommandRouter(self.app, ui)
        with (
            patch.object(ui, "render_ok") as mock_ok,
            patch.object(ui, "render_warn") as mock_warn,
            patch.object(ui, "render_error") as mock_err,
        ):
            router.handle("/model 2")
            mock_ok.assert_called_once()
            self.app._limit_log.record("gemini-3.8-flash")
            router.handle("/model gemini-3.8-flash")
            mock_warn.assert_called_once()
            router.handle("/model nonexistent-xyz")
            mock_err.assert_called_once()

    def test_thinking_indicator_maps_stage_keys_to_ui_labels(self):
        ui, _ = _capture_ui(interactive=False)
        with ui.thinking_context() as indicator:
            indicator.update("agent", "task_agent")
            self.assertEqual(indicator._label, "Checking tasks…")
            self.assertEqual(indicator.agents, ["task_agent"])
            indicator.update("reading_document", "notes_agent")
            self.assertEqual(indicator._label, "Reading document…")
            self.assertEqual(indicator.agents, ["task_agent", "notes_agent"])


if __name__ == "__main__":
    unittest.main()
