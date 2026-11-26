"""Unit tests for ADK AgentProfiles, BuddyApp, and side-effect-free imports."""

from datetime import datetime
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
from buddyai.sources import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")


class TestProfilesAndApp(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 15, tzinfo=MANILA)

    def test_profiles_tools_instructions_and_adk_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(sources=[JsonStore(tmpdir)])
            tk = BuddyToolkit(
                ws,
                BriefingService(ws),
                DocumentReader(model="gemini-4-hydrogen", clock=lambda: self.now),
                clock=lambda: self.now,
            )
            task_p = TaskAgentProfile("gemini-4-hydrogen", tk)
            sched_p = ScheduleAgentProfile("gemini-4-hydrogen", tk)
            notes_p = NotesAgentProfile("gemini-4-hydrogen", tk)
            brief_p = BriefingAgentProfile("gemini-4-hydrogen", tk)
            coord_p = CoordinatorProfile(
                "gemini-4-hydrogen", tk, [task_p, sched_p, notes_p, brief_p]
            )

            self.assertEqual(
                [fn.__name__ for fn in task_p.tools()],
                [
                    "add_task",
                    "update_task",
                    "complete_task",
                    "delete_task",
                    "list_tasks",
                    "add_reminder",
                    "list_proposals",
                    "confirm_tasks",
                ],
            )
            self.assertEqual(
                [fn.__name__ for fn in sched_p.tools()],
                [
                    "schedule_meeting",
                    "reschedule_meeting",
                    "cancel_meeting",
                    "find_conflicts",
                    "find_free_slot",
                    "list_events",
                ],
            )
            self.assertEqual(
                [fn.__name__ for fn in notes_p.tools()],
                ["add_note", "search_notes", "summarize_document"],
            )
            self.assertEqual(
                [fn.__name__ for fn in brief_p.tools()],
                ["get_daily_briefing"],
            )
            self.assertEqual(coord_p.tools(), [])

            for profile in (coord_p, task_p, sched_p, notes_p, brief_p):
                instr = profile.instruction()
                self.assertIn("2026-11-24", instr)
                self.assertIn("10:15", instr)
                self.assertIn("Tuesday", instr)

            root_agent = coord_p.build()
            self.assertEqual(root_agent.name, "buddy_coordinator")
            self.assertEqual(len(root_agent.sub_agents), 4)
            for sub in root_agent.sub_agents:
                self.assertEqual(sub.mode, "single_turn")

    def test_buddy_app_offline_behavior(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = BuddyApp(data_dir=tmpdir, clock=lambda: self.now)
            try:
                self.assertEqual(app.root_agent.name, "buddy_coordinator")

                bad_file = os.path.join(tmpdir, "bad.exe")
                with open(bad_file, "wb") as handle:
                    handle.write(b"x")
                reply_bad = app.ask("Summarize this", files=[bad_file])
                self.assertIn("Unsupported file type", reply_bad)

                reply_missing = app.ask("Summarize", files=[os.path.join(tmpdir, "nope.pdf")])
                self.assertIn("File not found", reply_missing)

                with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}, clear=False):
                    reply_no_key = app.ask("Hello BuddyAI")
                    self.assertIn("GOOGLE_API_KEY", reply_no_key)

                with self.assertRaises(NotImplementedError):
                    app.start_voice_session()
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
