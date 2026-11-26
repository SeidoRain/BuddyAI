"""Unit tests for all BuddyToolkit tools and disk persistence."""

from datetime import datetime
import json
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from buddyai.briefing import BriefingService
from buddyai.document_reader import DocumentReader
from buddyai.sources import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def generate_content(self, model, contents, config):
        return _FakeResp(
            json.dumps(
                {
                    "summary": "Budget overview.",
                    "key_points": ["Approve Q4 spend"],
                    "action_items": [
                        {
                            "title": "Approve Q4 budget",
                            "due_date": "2026-11-28",
                            "priority": "high",
                        }
                    ],
                }
            )
        )


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


class TestToolkit(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=MANILA)

    def _make_toolkit(self, tmpdir):
        store = JsonStore(tmpdir)
        ws = Workspace(sources=[store])
        ws.load()
        briefing = BriefingService(ws)
        reader = DocumentReader(model="gemini-4-hydrogen", client=_FakeClient(), clock=lambda: self.now)
        return BuddyToolkit(ws, briefing, reader, clock=lambda: self.now), store

    def test_task_reminder_and_proposal_tools_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tk, store = self._make_toolkit(tmpdir)

            res = tk.add_task("Submit thesis draft", due="2026-11-24", priority="high")
            self.assertEqual(res["status"], "success")
            task_id = res["task"]["item_id"]

            bad_due = tk.add_task("Past task", due="2026-11-20", priority="low")
            self.assertEqual(bad_due["status"], "error")
            self.assertEqual(bad_due["error_type"], "InvalidDueDateError")

            upd = tk.update_task(task_id, title="Submit final thesis draft", priority="medium")
            self.assertEqual(upd["status"], "success")
            self.assertEqual(upd["task"]["title"], "Submit final thesis draft")

            listed = tk.list_tasks()
            self.assertEqual(listed["status"], "success")
            self.assertEqual(len(listed["tasks"]), 1)
            self.assertFalse(listed["tasks"][0]["overdue"])

            rem = tk.add_reminder("Bring draft", "2026-11-24T13:00", repeat="daily")
            self.assertEqual(rem["status"], "success")
            bad_rem = tk.add_reminder("Bad rem", "2026-11-24", repeat="daily")
            self.assertEqual(bad_rem["status"], "error")
            self.assertEqual(bad_rem["error_type"], "InvalidInputError")

            sample_txt = os.path.join(tmpdir, "memo.txt")
            with open(sample_txt, "w", encoding="utf-8") as handle:
                handle.write("Review Q4 budget by Friday.")
            doc_res = tk.summarize_document(sample_txt)
            self.assertEqual(doc_res["status"], "success")
            self.assertEqual(len(doc_res["proposal_ids"]), 1)

            proposals = tk.list_proposals()
            self.assertEqual(proposals["status"], "success")
            self.assertEqual(len(proposals["proposals"]), 1)

            conf = tk.confirm_tasks(doc_res["proposal_ids"])
            self.assertEqual(conf["status"], "success")
            self.assertEqual(conf["tasks"][0]["status"], "open")

            comp = tk.complete_task(task_id)
            self.assertEqual(comp["status"], "success")
            self.assertEqual(comp["task"]["status"], "done")

            with_done = tk.list_tasks(include_done=True)
            self.assertEqual(len(with_done["tasks"]), 2)

            dele = tk.delete_task(task_id)
            self.assertEqual(dele["status"], "success")

            # Verify changes persisted on disk.
            reloaded = Workspace(sources=[store])
            reloaded.load()
            self.assertEqual(len(reloaded.tasks.list_all_tasks()), 1)
            self.assertEqual(len(reloaded.tasks.list_reminders()), 1)
            self.assertEqual(len(reloaded.notebook.list_notes()), 1)

    def test_schedule_notes_briefing_and_unexpected_error_safety(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tk, _ = self._make_toolkit(tmpdir)

            m1 = tk.schedule_meeting(
                "Thesis Meeting",
                "2026-11-25T14:00",
                "2026-11-25T15:00",
                location="Room 101",
                attendees="Prof. Cruz, ana@uni.edu",
            )
            self.assertEqual(m1["status"], "success")
            mtg_id = m1["meeting"]["item_id"]

            conflict = tk.schedule_meeting(
                "Group Call",
                "2026-11-25T14:30",
                "2026-11-25T15:30",
            )
            self.assertEqual(conflict["status"], "error")
            self.assertEqual(conflict["error_type"], "SchedulingConflictError")
            self.assertTrue(conflict["suggested_start"].startswith("2026-11-25T15:00"))

            fc = tk.find_conflicts("2026-11-25T14:30", "2026-11-25T15:30")
            self.assertEqual(fc["status"], "success")
            self.assertEqual(len(fc["conflicts"]), 1)

            slot = tk.find_free_slot("2026-11-25", 60, earliest_time="14:00")
            self.assertEqual(slot["status"], "success")
            self.assertTrue(slot["start"].startswith("2026-11-25T15:00"))

            resched = tk.reschedule_meeting(
                "Thesis Meeting", "2026-11-25T15:00", "2026-11-25T16:00"
            )
            self.assertEqual(resched["status"], "success")

            events_day = tk.list_events("2026-11-25")
            self.assertEqual(events_day["status"], "success")
            self.assertEqual(len(events_day["meetings"]), 1)

            events_upcoming = tk.list_events()
            self.assertEqual(events_upcoming["status"], "success")
            self.assertEqual(len(events_upcoming["meetings"]), 1)

            note = tk.add_note("Sprint Ideas", "Remember atomic writes")
            self.assertEqual(note["status"], "success")
            found = tk.search_notes("atomic")
            self.assertEqual(found["status"], "success")
            self.assertEqual(len(found["notes"]), 1)

            tk.add_task("Today task", due="2026-11-24", priority="high")
            brief_today = tk.get_daily_briefing()
            self.assertEqual(brief_today["status"], "success")
            self.assertIn("Today task", brief_today["briefing_text"])

            brief_day = tk.get_daily_briefing("2026-11-25")
            self.assertEqual(brief_day["status"], "success")
            self.assertIn("Thesis Meeting", brief_day["briefing_text"])

            cancel = tk.cancel_meeting(mtg_id)
            self.assertEqual(cancel["status"], "success")

            # Unexpected internal exceptions must also return an error dict, never raise.
            tk._workspace = None
            crash_safe = tk.list_tasks()
            self.assertEqual(crash_safe["status"], "error")


if __name__ == "__main__":
    unittest.main()
