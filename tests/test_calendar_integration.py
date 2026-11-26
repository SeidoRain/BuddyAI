"""Integration tests for IcsCalendarSource with Workspace, Agenda, Toolkit, and BuddyApp."""

from datetime import datetime
import json
import logging
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from google.adk.models.base_llm import BaseLlm

from buddyai.agents.profiles import ScheduleAgentProfile
from buddyai.app import BuddyApp
from buddyai.exceptions import DataSourceError, ReadOnlySourceError
from buddyai.models import Meeting
from buddyai.sources import IcsCalendarSource, JsonStore
from buddyai.web_lookup import WebLookup
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 26, 9, 0, tzinfo=MANILA)


class _DummyLlm(BaseLlm):
    """Offline stand-in model so BuddyApp can be built with no API key."""

    async def generate_content_async(self, llm_request, stream=False):
        if False:
            yield


def _sample_ics():
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//BuddyAI//Test//EN",
            "BEGIN:VEVENT",
            "UID:dept-meeting@example.com",
            "SUMMARY:Department meeting",
            "DTSTART;TZID=Asia/Manila:20261127T100000",
            "DTEND;TZID=Asia/Manila:20261127T110000",
            "LOCATION:Room 204",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:standup-ext@example.com",
            "SUMMARY:Standup",
            "DTSTART;TZID=Asia/Manila:20261127T080000",
            "DTEND;TZID=Asia/Manila:20261127T090000",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


class TestCalendarIntegration(unittest.TestCase):
    """Verifies B7 behaviours across BuddyApp, BuddyToolkit, Agenda, and Workspace."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self._tmp.name, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.ics_path = os.path.join(self._tmp.name, "cal.ics")
        with open(self.ics_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(_sample_ics())
        self.app = BuddyApp(
            data_dir=self.data_dir,
            model=_DummyLlm(model="gemini-3.5-flash-lite"),
            clock=lambda: NOW,
            ics_file=self.ics_path,
            web_lookup=WebLookup(fetcher=self._offline_fetcher),
        )

    @staticmethod
    def _offline_fetcher(url):
        raise DataSourceError("offline in unit test")

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_imported_meetings_appear_in_list_events_with_calendar_file_source(self):
        by_day = self.app.toolkit.list_events(day="2026-11-27")
        self.assertEqual(by_day["status"], "success")
        titles = [m["title"] for m in by_day["meetings"]]
        self.assertIn("Department meeting", titles)
        for record in by_day["meetings"]:
            self.assertEqual(record["source"], Meeting.SOURCE_CALENDAR_FILE)

        upcoming = self.app.toolkit.list_events()
        self.assertEqual(upcoming["status"], "success")
        self.assertIn(
            "Department meeting", [m["title"] for m in upcoming["meetings"]]
        )

    def test_scheduling_over_imported_meeting_returns_conflict_and_free_slot_skips_it(self):
        conflict = self.app.toolkit.schedule_meeting(
            "Call", "2026-11-27T10:30", "2026-11-27T11:30"
        )
        self.assertEqual(conflict["status"], "error")
        self.assertEqual(conflict["error_type"], "SchedulingConflictError")
        self.assertIn("Department meeting", conflict["message"])
        self.assertTrue(conflict["suggested_start"].startswith("2026-11-27T11:00"))

        found = self.app.toolkit.find_conflicts("2026-11-27T10:15", "2026-11-27T10:45")
        self.assertEqual(found["status"], "success")
        self.assertEqual(found["conflicts"][0]["title"], "Department meeting")

        slot = self.app.toolkit.find_free_slot(
            day="2026-11-27", minutes=60, earliest_time="10:00"
        )
        self.assertEqual(slot["status"], "success")
        self.assertTrue(slot["start"].startswith("2026-11-27T11:00"))

    def test_daily_briefing_includes_imported_meeting_tagged_calendar_file(self):
        brief = self.app.toolkit.get_daily_briefing(day="2026-11-27")
        self.assertEqual(brief["status"], "success")
        self.assertIn("Department meeting", brief["briefing_text"])
        self.assertIn("[calendar file]", brief["briefing_text"])

    def test_saving_local_task_never_writes_imported_meetings_to_meetings_json(self):
        added = self.app.toolkit.add_task("Write report", due="2026-11-28", priority="high")
        self.assertEqual(added["status"], "success")

        meetings_file = os.path.join(self.data_dir, JsonStore.MEETINGS_FILE)
        tasks_file = os.path.join(self.data_dir, JsonStore.TASKS_FILE)
        with open(meetings_file, "r", encoding="utf-8") as handle:
            meetings_data = json.load(handle)
        with open(tasks_file, "r", encoding="utf-8") as handle:
            tasks_data = json.load(handle)

        self.assertEqual(meetings_data, [])
        self.assertEqual(len(tasks_data), 1)
        self.assertEqual(tasks_data[0]["title"], "Write report")

    def test_reschedule_and_cancel_refuse_imported_meeting_by_title_and_id(self):
        events = self.app.toolkit.list_events(day="2026-11-27")["meetings"]
        dept = [m for m in events if m["title"] == "Department meeting"][0]

        for identifier in (dept["title"], dept["item_id"]):
            res = self.app.toolkit.reschedule_meeting(
                identifier, "2026-11-27T14:00", "2026-11-27T15:00"
            )
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "ReadOnlySourceError")

            can = self.app.toolkit.cancel_meeting(identifier)
            self.assertEqual(can["status"], "error")
            self.assertEqual(can["error_type"], "ReadOnlySourceError")

        after = self.app.toolkit.list_events(day="2026-11-27")["meetings"]
        dept_after = [m for m in after if m["item_id"] == dept["item_id"]][0]
        self.assertEqual(dept_after["start"], dept["start"])

    def test_local_meeting_sharing_title_with_imported_meeting_can_be_rescheduled(self):
        added = self.app.toolkit.schedule_meeting(
            "Standup", "2026-11-27T14:00", "2026-11-27T14:30"
        )
        self.assertEqual(added["status"], "success")

        moved = self.app.toolkit.reschedule_meeting(
            "Standup", "2026-11-27T15:00", "2026-11-27T15:30"
        )
        self.assertEqual(moved["status"], "success")
        self.assertTrue(moved["meeting"]["start"].startswith("2026-11-27T15:00"))

    def test_broken_startup_ics_file_sets_calendar_error_without_crashing(self):
        missing = os.path.join(self._tmp.name, "missing.ics")
        bad_file = os.path.join(self._tmp.name, "not_ics.txt")
        with open(bad_file, "w", encoding="utf-8") as handle:
            handle.write("not a calendar")

        for path in (missing, self._tmp.name, bad_file):
            app = BuddyApp(
                data_dir=self.data_dir,
                model=_DummyLlm(model="gemini-3.5-flash-lite"),
                clock=lambda: NOW,
                ics_file=path,
            )
            try:
                self.assertTrue(app.calendar_error)
                self.assertIsNone(app.calendar_source)
                self.assertEqual(app.workspace.agenda.list_meetings(), [])
            finally:
                app.close()

    def test_agenda_get_and_find_meeting_raise_read_only_for_external(self):
        agenda = self.app.workspace.agenda
        dept = [m for m in agenda.list_meetings() if m.title == "Department meeting"][0]

        with self.assertRaises(ReadOnlySourceError):
            agenda.get_meeting(dept.item_id)
        with self.assertRaises(ReadOnlySourceError):
            agenda.find_meeting("Department meeting")
        with self.assertRaises(ReadOnlySourceError):
            agenda.find_meeting("department")

    def test_workspace_replace_source_and_remove_source(self):
        ws = Workspace(sources=[JsonStore(self.data_dir)])
        src1 = IcsCalendarSource(self.ics_path, clock=lambda: NOW)
        src2 = IcsCalendarSource(self.ics_path, clock=lambda: NOW)

        ws.replace_source(src1)
        self.assertEqual(len(ws.sources), 2)
        ws.replace_source(src2)
        self.assertEqual(len(ws.sources), 2)
        self.assertIs(ws.sources[-1], src2)

        self.assertTrue(ws.remove_source(IcsCalendarSource.DEFAULT_NAME))
        self.assertFalse(ws.remove_source(IcsCalendarSource.DEFAULT_NAME))
        self.assertEqual(len(ws.sources), 1)

    def test_schedule_agent_instruction_mentions_calendar_file(self):
        profile = ScheduleAgentProfile(
            model=_DummyLlm(model="gemini-3.5-flash-lite"),
            toolkit=self.app.toolkit,
        )
        self.assertIn("calendar_file", profile.instruction())


if __name__ == "__main__":
    unittest.main()
