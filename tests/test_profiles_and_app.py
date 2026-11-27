"""Unit tests for ADK AgentProfiles and BuddyApp offline behaviour."""

from datetime import datetime
import logging
import os
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from buddyai.agents import (
    BriefingAgentProfile,
    CoordinatorProfile,
    NotesAgentProfile,
    ScheduleAgentProfile,
    TaskAgentProfile,
)
from buddyai.app import BuddyApp
from buddyai.briefing import BriefingService
from buddyai.document_reader import DocumentReader
from buddyai.exceptions import UnsupportedFileTypeError
from buddyai.sources import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")


class TestAgentProfiles(unittest.TestCase):
    """Checks tool wiring, dynamic time instructions, and ADK agent tree build."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.now = datetime(2026, 11, 24, 10, 15, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        ws = Workspace(sources=[JsonStore(self._tmp.name)])
        self.tk = BuddyToolkit(
            ws,
            BriefingService(ws),
            DocumentReader(model="gemini-4-hydrogen", clock=lambda: self.now),
            clock=lambda: self.now,
        )
        self.task_p = TaskAgentProfile("gemini-4-hydrogen", self.tk)
        self.sched_p = ScheduleAgentProfile("gemini-4-hydrogen", self.tk)
        self.notes_p = NotesAgentProfile("gemini-4-hydrogen", self.tk)
        self.brief_p = BriefingAgentProfile("gemini-4-hydrogen", self.tk)
        self.coord_p = CoordinatorProfile(
            "gemini-4-hydrogen",
            self.tk,
            [self.task_p, self.sched_p, self.notes_p, self.brief_p],
        )

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_task_profile_exposes_only_task_and_reminder_tools(self):
        self.assertEqual(
            [fn.__name__ for fn in self.task_p.tools()],
            [
                "add_task",
                "update_task",
                "complete_task",
                "delete_task",
                "list_tasks",
                "add_reminder",
                "list_reminders",
                "delete_reminder",
                "list_proposals",
                "confirm_tasks",
            ],
        )

    def test_schedule_profile_exposes_only_schedule_tools(self):
        self.assertEqual(
            [fn.__name__ for fn in self.sched_p.tools()],
            [
                "schedule_meeting",
                "reschedule_meeting",
                "update_meeting",
                "cancel_meeting",
                "find_conflicts",
                "find_free_slot",
                "list_events",
            ],
        )

    def test_notes_profile_exposes_only_notes_and_document_tools(self):
        self.assertEqual(
            [fn.__name__ for fn in self.notes_p.tools()],
            ["add_note", "search_notes", "delete_note", "summarize_document"],
        )

    def test_briefing_profile_exposes_only_daily_briefing_tool(self):
        self.assertEqual(
            [fn.__name__ for fn in self.brief_p.tools()],
            ["get_daily_briefing"],
        )

    def test_briefing_profile_instruction_mentions_weather_time_and_headlines(self):
        instr = self.brief_p.instruction()
        self.assertIn("at_time", instr)
        self.assertIn("weather", instr.lower())
        self.assertIn("five", instr.lower())
        self.assertIn("[Title](url)", instr)

    def test_coordinator_instruction_notes_briefing_agent_covers_weather_and_headlines(self):
        instr = self.coord_p.instruction()
        self.assertIn("briefing_agent", instr)
        self.assertIn("five Philippine headlines", instr)
        self.assertIn("[Title](url)", instr)

    def test_coordinator_profile_exposes_web_lookup_tools(self):
        self.assertEqual(
            [fn.__name__ for fn in self.coord_p.tools()],
            ["search_web", "get_weather"],
        )

    def test_every_profile_instruction_includes_current_date_time_and_weekday(self):
        for profile in (
            self.coord_p,
            self.task_p,
            self.sched_p,
            self.notes_p,
            self.brief_p,
        ):
            with self.subTest(profile=profile.name):
                instr = profile.instruction()
                self.assertIn("2026-11-24", instr)
                self.assertIn("10:15", instr)
                self.assertIn("Tuesday", instr)

    def test_built_root_agent_has_four_single_turn_sub_agents(self):
        root_agent = self.coord_p.build()
        self.assertEqual(root_agent.name, "buddy_coordinator")
        self.assertEqual(len(root_agent.sub_agents), 4)
        for sub in root_agent.sub_agents:
            with self.subTest(sub_agent=sub.name):
                self.assertEqual(sub.mode, "single_turn")


class TestBuddyAppOffline(unittest.TestCase):
    """Checks BuddyApp construction, file checks, missing-key guard, and voice stub."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.now = datetime(2026, 11, 24, 10, 15, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        self.app = BuddyApp(data_dir=self._tmp.name, clock=lambda: self.now, ics_file="")

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_root_agent_is_named_buddy_coordinator(self):
        self.assertEqual(self.app.root_agent.name, "buddy_coordinator")

    def test_ask_with_unsupported_file_returns_unsupported_file_type(self):
        bad_file = os.path.join(self._tmp.name, "bad.exe")
        with open(bad_file, "wb") as handle:
            handle.write(b"x")
        reply = self.app.ask("Summarize this", files=[bad_file])
        self.assertIn("Unsupported file type", reply)

    def test_check_file_returns_the_absolute_path_of_a_supported_file(self):
        notes = os.path.join(self._tmp.name, "notes.txt")
        with open(notes, "w", encoding="utf-8") as handle:
            handle.write("notes")
        self.assertEqual(self.app.check_file(notes), os.path.abspath(notes))

    def test_check_file_rejects_an_unsupported_type_before_any_model_request(self):
        with self.assertRaises(UnsupportedFileTypeError):
            self.app.check_file(os.path.join(self._tmp.name, "report.doc"))

    def test_ask_with_missing_file_returns_file_not_found(self):
        reply = self.app.ask(
            "Summarize", files=[os.path.join(self._tmp.name, "nope.pdf")]
        )
        self.assertIn("File not found", reply)

    def test_ask_without_api_key_mentions_google_api_key(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False):
            reply = self.app.ask("Hello BuddyAI")
        self.assertIn("GOOGLE_API_KEY", reply)

    def test_start_voice_session_returns_a_voice_session(self):
        from buddyai.voice import AudioDevice, VoiceSession

        class _StubAudio(AudioDevice):
            def open(self): pass
            def close(self): pass
            def read_chunk(self): return b""
            def play(self, chunk): pass
            def clear_playback(self): pass

        session = self.app.start_voice_session(audio_device=_StubAudio())
        self.assertIsInstance(session, VoiceSession)


if __name__ == "__main__":
    unittest.main()
