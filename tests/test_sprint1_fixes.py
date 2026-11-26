"""Unit tests for the fixes made after the Sprint 1 review.

Each test covers one behaviour, so a failure points at one rule.
"""

import asyncio
from datetime import datetime, time, timedelta
import logging
import os
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from google.adk.models.base_llm import BaseLlm

from buddyai.agents import CoordinatorProfile, TaskAgentProfile
from buddyai.app import BuddyApp
from buddyai.briefing import BriefingService
from buddyai.document_reader import DocumentReader
from buddyai.exceptions import (
    InvalidInputError,
    SchedulingConflictError,
    TaskNotFoundError,
)
from buddyai.managers import Agenda, TaskManager
from buddyai.models import Meeting, Reminder, Task
from buddyai.sources import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 24, 10, 7, tzinfo=MANILA)      # a Tuesday


def _at(day_offset, hour, minute=0):
    day = NOW + timedelta(days=day_offset)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _meeting(title, start, end):
    return Meeting(title=title, created_at=NOW, start=start, end=end)


def _proposal(title):
    return Task(title=title, created_at=NOW, status="proposed")


def _make_toolkit(tmpdir):
    ws = Workspace(sources=[JsonStore(tmpdir)])
    ws.load()
    reader = DocumentReader(model="gemini-4-hydrogen", clock=lambda: NOW)
    return BuddyToolkit(ws, BriefingService(ws), reader, clock=lambda: NOW), ws


class TestAgentInstructions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.toolkit, _ = _make_toolkit(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_time_line_gives_utc_offset_and_zone_name(self):
        instruction = TaskAgentProfile("gemini-4-hydrogen", self.toolkit).instruction()
        self.assertIn("UTC+08:00", instruction)
        self.assertIn("Asia/Manila", instruction)

    def test_time_line_avoids_the_ambiguous_pst_label(self):
        instruction = TaskAgentProfile("gemini-4-hydrogen", self.toolkit).instruction()
        self.assertNotIn("PST", instruction)

    def test_coordinator_owns_the_confirmation_rule(self):
        instruction = CoordinatorProfile("gemini-4-hydrogen", self.toolkit, []).instruction()
        self.assertIn("proposals", instruction)
        self.assertIn("only after the user has said yes", instruction)

    def test_coordinator_is_told_specialists_see_only_the_request(self):
        instruction = CoordinatorProfile("gemini-4-hydrogen", self.toolkit, []).instruction()
        self.assertIn("sees only the request text", instruction)


class TestConfirmAllOrNothing(unittest.TestCase):
    def test_one_bad_id_confirms_nothing(self):
        manager = TaskManager()
        first = manager.propose(_proposal("Send invoice"))
        with self.assertRaises(TaskNotFoundError):
            manager.confirm_all([first.item_id, "task-missing"])
        self.assertEqual(first.status, "proposed")

    def test_an_already_open_task_confirms_nothing(self):
        manager = TaskManager()
        first = manager.propose(_proposal("Send invoice"))
        opened = manager.add_task(Task(title="Open one", created_at=NOW), NOW)
        with self.assertRaises(InvalidInputError):
            manager.confirm_all([first.item_id, opened.item_id])
        self.assertEqual(first.status, "proposed")

    def test_valid_ids_are_all_confirmed(self):
        manager = TaskManager()
        first = manager.propose(_proposal("Send invoice"))
        second = manager.propose(_proposal("Book venue"))
        confirmed = manager.confirm_all([first.item_id, second.item_id, first.item_id])
        self.assertEqual([task.status for task in confirmed], ["open", "open"])

    def test_toolkit_reports_an_error_and_saves_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit, ws = _make_toolkit(tmpdir)
            first = ws.tasks.propose(_proposal("Send invoice"))
            ws.save()
            result = toolkit.confirm_tasks([first.item_id, "task-missing"])
            self.assertEqual(result["status"], "error")
            self.assertEqual(first.status, "proposed")
            reloaded = Workspace(sources=[JsonStore(tmpdir)])
            reloaded.load()
            self.assertEqual(reloaded.tasks.get_task(first.item_id).status, "proposed")


class TestNoSlotsOrMeetingsInThePast(unittest.TestCase):
    def test_free_slot_today_starts_at_the_next_quarter_hour(self):
        slot = Agenda().find_free_slot(NOW.date(), 60, now=NOW)
        self.assertEqual(slot, _at(0, 10, 15))

    def test_free_slot_today_still_honours_a_later_earliest_time(self):
        slot = Agenda().find_free_slot(NOW.date(), 60, earliest=time(13, 0), now=NOW)
        self.assertEqual(slot, _at(0, 13))

    def test_free_slot_moves_to_tomorrow_when_today_has_no_room_left(self):
        late = NOW.replace(hour=17, minute=40)
        slot = Agenda().find_free_slot(NOW.date(), 60, now=late)
        self.assertEqual(slot, _at(1, 8))

    def test_free_slot_without_now_keeps_the_old_behaviour(self):
        self.assertEqual(Agenda().find_free_slot(NOW.date(), 60), _at(0, 8))

    def test_schedule_refuses_a_meeting_that_starts_in_the_past(self):
        with self.assertRaises(InvalidInputError):
            Agenda().schedule(_meeting("Yesterday sync", _at(-1, 9), _at(-1, 10)), NOW)

    def test_restore_still_accepts_a_past_meeting(self):
        agenda = Agenda()
        agenda.restore(_meeting("Last week", _at(-7, 9), _at(-7, 10)))
        self.assertEqual(len(agenda.list_meetings()), 1)

    def test_reschedule_into_the_past_is_refused_and_changes_nothing(self):
        agenda = Agenda()
        meeting = agenda.schedule(_meeting("Thesis meeting", _at(1, 14), _at(1, 15)), NOW)
        with self.assertRaises(InvalidInputError):
            agenda.reschedule(meeting.item_id, _at(-1, 14), _at(-1, 15), NOW)
        self.assertEqual(meeting.start, _at(1, 14))

    def test_conflict_suggestion_is_never_in_the_past(self):
        agenda = Agenda()
        agenda.restore(_meeting("Running now", _at(0, 9), _at(0, 11)))
        with self.assertRaises(SchedulingConflictError) as caught:
            agenda.schedule(_meeting("Clash", _at(0, 10, 30), _at(0, 11, 30)), NOW)
        self.assertGreaterEqual(caught.exception.suggested_start, NOW)

    def test_toolkit_schedule_meeting_in_the_past_returns_an_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit, _ = _make_toolkit(tmpdir)
            result = toolkit.schedule_meeting(
                "Yesterday sync", "2026-11-23T09:00", "2026-11-23T10:00"
            )
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_type"], "InvalidInputError")

    def test_toolkit_find_free_slot_today_is_not_in_the_past(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit, _ = _make_toolkit(tmpdir)
            result = toolkit.find_free_slot("2026-11-24", 30)
            self.assertEqual(result["start"], "2026-11-24T10:15:00+08:00")


class TestNoOneOffRemindersInThePast(unittest.TestCase):
    def test_past_one_off_reminder_is_refused(self):
        reminder = Reminder(title="Old ping", created_at=NOW, remind_at=_at(-4, 9))
        with self.assertRaises(InvalidInputError):
            TaskManager().add_reminder(reminder, NOW)

    def test_repeating_reminder_may_start_in_the_past(self):
        reminder = Reminder(
            title="Daily meds", created_at=NOW, remind_at=_at(-4, 9), repeat="daily"
        )
        self.assertIs(TaskManager().add_reminder(reminder, NOW), reminder)

    def test_restore_still_accepts_a_past_one_off_reminder(self):
        reminder = Reminder(title="Old ping", created_at=NOW, remind_at=_at(-4, 9))
        self.assertIs(TaskManager().restore(reminder), reminder)

    def test_toolkit_add_reminder_in_the_past_returns_an_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            toolkit, _ = _make_toolkit(tmpdir)
            result = toolkit.add_reminder("Old ping", "2026-11-20T09:00")
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_type"], "InvalidInputError")


class _NeverAnswers(BaseLlm):
    """Stand-in model that hangs, like a stalled network call."""

    async def generate_content_async(self, llm_request, stream=False):
        await asyncio.sleep(30)
        yield None


class _FakeApiError(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


class TestApiFailureMessages(unittest.TestCase):
    def test_a_hanging_model_call_times_out_with_a_clear_reply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = BuddyApp(data_dir=tmpdir, model=_NeverAnswers(model="never"))
            app.TURN_TIMEOUT_SECONDS = 0.5
            logging.getLogger("google_adk").setLevel(logging.CRITICAL)   # ADK's own warnings
            self.addCleanup(logging.getLogger("google_adk").setLevel, logging.NOTSET)
            try:
                with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
                    # The app writes the failed request to its log; assertLogs checks it.
                    with self.assertLogs("buddyai.app", level="WARNING") as logged:
                        reply = app.ask("hello")
                self.assertIn("Model request to never failed (TimeoutError)", logged.output[0])
                self.assertIn("is not responding right now, so I switched to", reply)
            finally:
                app.close()

    def test_daily_quota_error_says_the_daily_limit_is_used_up(self):
        error = _FakeApiError(429, "429 RESOURCE_EXHAUSTED. GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        self.assertIn("Today's free request limit", BuddyApp._format_api_error(error))

    def test_per_minute_quota_error_asks_to_wait_a_minute(self):
        error = _FakeApiError(429, "429 RESOURCE_EXHAUSTED. GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
        self.assertIn("wait a minute", BuddyApp._format_api_error(error))

    def test_busy_model_error_suggests_switching_models(self):
        error = _FakeApiError(503, "503 UNAVAILABLE. This model is currently experiencing high demand.")
        self.assertIn("/model next", BuddyApp._format_api_error(error))

    def test_quota_error_is_not_mistaken_for_busy_by_digits_in_the_text(self):
        error = _FakeApiError(429, "429 RESOURCE_EXHAUSTED. PerDay. Please retry in 16503s.")
        self.assertNotIn("busy", BuddyApp._format_api_error(error))


if __name__ == "__main__":
    unittest.main()
