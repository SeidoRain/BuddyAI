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


class _ToolkitTestCase(unittest.TestCase):
    """Builds a BuddyToolkit over a temporary JsonStore with a fixed clock."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        self.store = JsonStore(self._tmp.name)
        self.ws = Workspace(sources=[self.store])
        self.ws.load()
        reader = DocumentReader(
            model="gemini-4-hydrogen",
            client=_FakeClient(),
            clock=lambda: self.now,
        )
        self.tk = BuddyToolkit(
            self.ws, BriefingService(self.ws), reader, clock=lambda: self.now
        )

    def tearDown(self):
        self._tmp.cleanup()


class TestToolkitTasksAndProposals(_ToolkitTestCase):
    """Checks task, reminder, document proposal, and persistence tool outcomes."""

    def test_add_task_succeeds_for_future_due_date(self):
        res = self.tk.add_task("Submit thesis draft", due="2026-11-24", priority="high")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["task"]["title"], "Submit thesis draft")

    def test_add_task_with_past_due_date_returns_invalid_due_date_error(self):
        res = self.tk.add_task("Past task", due="2026-11-20", priority="low")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_type"], "InvalidDueDateError")

    def test_update_task_changes_title_and_priority(self):
        task_id = self.tk.add_task("Draft", due="2026-11-24", priority="high")["task"]["item_id"]
        upd = self.tk.update_task(task_id, title="Submit final thesis draft", priority="medium")
        self.assertEqual(upd["status"], "success")
        self.assertEqual(upd["task"]["title"], "Submit final thesis draft")

    def test_list_tasks_returns_open_tasks_with_overdue_flag(self):
        self.tk.add_task("Submit thesis draft", due="2026-11-24", priority="high")
        listed = self.tk.list_tasks()
        self.assertEqual(listed["status"], "success")
        self.assertEqual(len(listed["tasks"]), 1)
        self.assertFalse(listed["tasks"][0]["overdue"])

    def test_add_reminder_succeeds_with_date_and_time(self):
        rem = self.tk.add_reminder("Bring draft", "2026-11-24T13:00", repeat="daily")
        self.assertEqual(rem["status"], "success")

    def test_add_reminder_without_time_returns_invalid_input_error(self):
        bad = self.tk.add_reminder("Bad rem", "2026-11-24", repeat="daily")
        self.assertEqual(bad["status"], "error")
        self.assertEqual(bad["error_type"], "InvalidInputError")

    def test_summarize_document_returns_proposal_ids_and_list_proposals_shows_them(self):
        sample_txt = os.path.join(self._tmp.name, "memo.txt")
        with open(sample_txt, "w", encoding="utf-8") as handle:
            handle.write("Review Q4 budget by Friday.")
        doc_res = self.tk.summarize_document(sample_txt)
        self.assertEqual(doc_res["status"], "success")
        self.assertEqual(len(doc_res["proposal_ids"]), 1)

        proposals = self.tk.list_proposals()
        self.assertEqual(proposals["status"], "success")
        self.assertEqual(len(proposals["proposals"]), 1)

    def test_confirm_tasks_opens_a_proposed_task(self):
        sample_txt = os.path.join(self._tmp.name, "memo.txt")
        with open(sample_txt, "w", encoding="utf-8") as handle:
            handle.write("Review Q4 budget by Friday.")
        proposal_ids = self.tk.summarize_document(sample_txt)["proposal_ids"]

        conf = self.tk.confirm_tasks(proposal_ids)
        self.assertEqual(conf["status"], "success")
        self.assertEqual(conf["tasks"][0]["status"], "open")

    def test_complete_task_and_list_tasks_with_include_done(self):
        id1 = self.tk.add_task("Task one", due="2026-11-24")["task"]["item_id"]
        self.tk.add_task("Task two", due="2026-11-25")
        comp = self.tk.complete_task(id1)
        self.assertEqual(comp["status"], "success")
        self.assertEqual(comp["task"]["status"], "done")

        with_done = self.tk.list_tasks(include_done=True)
        self.assertEqual(len(with_done["tasks"]), 2)

    def test_delete_task_removes_the_task(self):
        task_id = self.tk.add_task("Delete me", due="2026-11-24")["task"]["item_id"]
        dele = self.tk.delete_task(task_id)
        self.assertEqual(dele["status"], "success")
        self.assertEqual(self.tk.list_tasks(include_done=True)["tasks"], [])

    def test_toolkit_changes_persist_on_disk_after_reload(self):
        self.tk.add_task("Persist task", due="2026-11-25")
        self.tk.add_reminder("Persist rem", "2026-11-24T13:00", repeat="daily")
        self.tk.add_note("Persist note", "Body text")

        reloaded = Workspace(sources=[self.store])
        reloaded.load()
        self.assertEqual(len(reloaded.tasks.list_all_tasks()), 1)
        self.assertEqual(len(reloaded.tasks.list_reminders()), 1)
        self.assertEqual(len(reloaded.notebook.list_notes()), 1)


class TestToolkitScheduleNotesAndBriefing(_ToolkitTestCase):
    """Checks schedule, notes, briefing tools, and unexpected-error safety."""

    def _schedule_thesis_meeting(self):
        return self.tk.schedule_meeting(
            "Thesis Meeting",
            "2026-11-25T14:00",
            "2026-11-25T15:00",
            location="Room 101",
            attendees="Prof. Cruz, ana@uni.edu",
        )

    def test_schedule_meeting_succeeds(self):
        res = self._schedule_thesis_meeting()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["meeting"]["title"], "Thesis Meeting")

    def test_schedule_meeting_conflict_returns_suggested_start(self):
        self._schedule_thesis_meeting()
        conflict = self.tk.schedule_meeting(
            "Group Call", "2026-11-25T14:30", "2026-11-25T15:30"
        )
        self.assertEqual(conflict["status"], "error")
        self.assertEqual(conflict["error_type"], "SchedulingConflictError")
        self.assertTrue(conflict["suggested_start"].startswith("2026-11-25T15:00"))

    def test_find_conflicts_returns_overlapping_meetings(self):
        self._schedule_thesis_meeting()
        fc = self.tk.find_conflicts("2026-11-25T14:30", "2026-11-25T15:30")
        self.assertEqual(fc["status"], "success")
        self.assertEqual(len(fc["conflicts"]), 1)

    def test_find_free_slot_returns_next_open_slot(self):
        self._schedule_thesis_meeting()
        slot = self.tk.find_free_slot("2026-11-25", 60, earliest_time="14:00")
        self.assertEqual(slot["status"], "success")
        self.assertTrue(slot["start"].startswith("2026-11-25T15:00"))

    def test_reschedule_meeting_moves_meeting(self):
        self._schedule_thesis_meeting()
        resched = self.tk.reschedule_meeting(
            "Thesis Meeting", "2026-11-25T15:00", "2026-11-25T16:00"
        )
        self.assertEqual(resched["status"], "success")

    def test_list_events_returns_meetings_for_day_and_for_upcoming(self):
        self._schedule_thesis_meeting()
        events_day = self.tk.list_events("2026-11-25")
        self.assertEqual(events_day["status"], "success")
        self.assertEqual(len(events_day["meetings"]), 1)

        events_upcoming = self.tk.list_events()
        self.assertEqual(events_upcoming["status"], "success")
        self.assertEqual(len(events_upcoming["meetings"]), 1)

    def test_add_note_and_search_notes(self):
        note = self.tk.add_note("Sprint Ideas", "Remember atomic writes")
        self.assertEqual(note["status"], "success")
        found = self.tk.search_notes("atomic")
        self.assertEqual(found["status"], "success")
        self.assertEqual(len(found["notes"]), 1)

    def test_get_daily_briefing_for_today_and_for_another_day(self):
        self._schedule_thesis_meeting()
        self.tk.add_task("Today task", due="2026-11-24", priority="high")

        brief_today = self.tk.get_daily_briefing()
        self.assertEqual(brief_today["status"], "success")
        self.assertIn("Today task", brief_today["briefing_text"])

        brief_day = self.tk.get_daily_briefing("2026-11-25")
        self.assertEqual(brief_day["status"], "success")
        self.assertIn("Thesis Meeting", brief_day["briefing_text"])

    def test_cancel_meeting_removes_meeting(self):
        mtg_id = self._schedule_thesis_meeting()["meeting"]["item_id"]
        cancel = self.tk.cancel_meeting(mtg_id)
        self.assertEqual(cancel["status"], "success")
        self.assertEqual(self.tk.list_events()["meetings"], [])

    def test_unexpected_internal_error_returns_error_dict_without_raising(self):
        self.tk._workspace = None
        with self.assertLogs("buddyai.toolkit", level="ERROR"):
            crash_safe = self.tk.list_tasks()
        self.assertEqual(crash_safe["status"], "error")


if __name__ == "__main__":
    unittest.main()
