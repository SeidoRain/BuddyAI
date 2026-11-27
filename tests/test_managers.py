"""Unit tests for TaskManager, Agenda, and Notebook."""

from datetime import date, datetime, time, timedelta
import unittest
from zoneinfo import ZoneInfo

from buddyai.exceptions import (
    AmbiguousItemError,
    InvalidDueDateError,
    InvalidInputError,
    MeetingNotFoundError,
    SchedulingConflictError,
    TaskNotFoundError,
)
from buddyai.managers import Agenda, Notebook, TaskManager
from buddyai.models import Meeting, Note, Task

MANILA = ZoneInfo("Asia/Manila")


class TestTaskManager(unittest.TestCase):
    """Checks TaskManager creation, proposal confirmation, ranking, lookup, and updates."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=MANILA)
        self.tm = TaskManager()

    def test_add_task_refuses_past_due_date(self):
        past = Task("Late", self.now, due_date=self.now - timedelta(hours=1))
        with self.assertRaises(InvalidDueDateError):
            self.tm.add_task(past, self.now)

    def test_propose_accepts_a_task_with_a_past_due_date(self):
        proposed = Task(
            "From PDF",
            self.now,
            due_date=self.now - timedelta(days=1),
            status="proposed",
            source="upload",
        )
        self.tm.propose(proposed)
        self.assertEqual(len(self.tm.list_proposals()), 1)

    def test_confirm_opens_proposal_and_empties_list_proposals(self):
        proposed = Task("From PDF", self.now, status="proposed", source="upload")
        self.tm.propose(proposed)
        self.tm.confirm(proposed.item_id)
        self.assertEqual(proposed.status, "open")
        self.assertEqual(self.tm.list_proposals(), [])

    def test_restore_accepts_an_overdue_task(self):
        restored = Task("Loaded overdue", self.now, due_date=self.now - timedelta(days=2))
        self.tm.restore(restored)
        self.assertEqual(self.tm.get_task(restored.item_id), restored)

    def test_list_by_priority_ranks_tasks_by_urgency_score(self):
        low_today = Task("Alpha", self.now, due_date=self.now + timedelta(hours=2), priority=1)
        high_today = Task("Beta", self.now, due_date=self.now + timedelta(hours=4), priority=3)
        high_later = Task("Gamma", self.now, due_date=self.now + timedelta(days=5), priority=3)
        self.tm.add_task(low_today, self.now)
        self.tm.add_task(high_today, self.now)
        self.tm.add_task(high_later, self.now)
        ranked = self.tm.list_by_priority(self.now)
        self.assertEqual([t.title for t in ranked], ["Beta", "Alpha", "Gamma"])

    def test_find_task_matches_by_exact_id(self):
        task = Task("Alpha", self.now, due_date=self.now + timedelta(hours=2))
        self.tm.add_task(task, self.now)
        self.assertIs(self.tm.find_task(task.item_id), task)

    def test_find_task_matches_by_title_ignoring_case(self):
        task = Task("Alpha", self.now, due_date=self.now + timedelta(hours=2))
        self.tm.add_task(task, self.now)
        self.assertIs(self.tm.find_task("alpha"), task)

    def test_find_task_prefers_exact_title_over_partial_match(self):
        exact = Task("Beta", self.now, due_date=self.now + timedelta(hours=4))
        longer = Task("Beta review", self.now, due_date=self.now + timedelta(days=1))
        self.tm.add_task(exact, self.now)
        self.tm.add_task(longer, self.now)
        self.assertIs(self.tm.find_task("beta"), exact)

    def test_find_task_raises_ambiguous_item_error_for_multiple_partial_matches(self):
        self.tm.add_task(Task("Beta", self.now, due_date=self.now + timedelta(hours=4)), self.now)
        self.tm.add_task(Task("Beta review", self.now, due_date=self.now + timedelta(days=1)), self.now)
        with self.assertRaises(AmbiguousItemError):
            self.tm.find_task("bet")

    def test_find_task_raises_task_not_found_error_for_unknown_title(self):
        with self.assertRaises(TaskNotFoundError):
            self.tm.find_task("does not exist")

    def test_failed_update_task_with_past_due_date_leaves_title_unchanged(self):
        task = Task("Alpha", self.now, due_date=self.now + timedelta(hours=2))
        self.tm.add_task(task, self.now)
        with self.assertRaises(InvalidDueDateError):
            self.tm.update_task(
                task.item_id,
                title="Updated",
                due_date=self.now - timedelta(hours=1),
                now=self.now,
            )
        self.assertEqual(task.title, "Alpha")

    def test_failed_update_task_with_a_float_priority_leaves_title_unchanged(self):
        task = Task("Alpha", self.now)
        self.tm.add_task(task, self.now)
        with self.assertRaises(InvalidInputError):
            self.tm.update_task(task.item_id, title="Updated", priority=2.0)
        self.assertEqual(task.title, "Alpha")
        self.assertEqual(task.priority, 2)


class TestAgenda(unittest.TestCase):
    """Checks Agenda conflict checks, rescheduling, free slots, and meeting lookups."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=MANILA)
        self.day = date(2026, 11, 25)
        self.agenda = Agenda()
        self.m1 = Meeting(
            "Morning Sync",
            self.now,
            start=datetime(2026, 11, 25, 9, 0, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 10, 0, tzinfo=MANILA),
        )
        self.m2 = Meeting(
            "Design Review",
            self.now,
            start=datetime(2026, 11, 25, 10, 0, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
        )

    def test_back_to_back_meetings_are_accepted(self):
        self.agenda.schedule(self.m1)
        self.agenda.schedule(self.m2)
        self.assertEqual(len(self.agenda.list_meetings()), 2)

    def test_overlapping_meeting_raises_conflict_naming_both_and_suggests_after_them(self):
        self.agenda.schedule(self.m1)
        self.agenda.schedule(self.m2)
        overlap = Meeting(
            "Conflict Call",
            self.now,
            start=datetime(2026, 11, 25, 9, 30, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 10, 30, tzinfo=MANILA),
        )
        with self.assertRaises(SchedulingConflictError) as ctx:
            self.agenda.schedule(overlap)
        self.assertEqual(len(ctx.exception.conflicts), 2)
        self.assertIn("Morning Sync", str(ctx.exception))
        self.assertIn("Design Review", str(ctx.exception))
        self.assertEqual(
            ctx.exception.suggested_start,
            datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
        )

    def test_reschedule_into_conflict_raises_and_leaves_meeting_unchanged(self):
        self.agenda.schedule(self.m1)
        self.agenda.schedule(self.m2)
        with self.assertRaises(SchedulingConflictError):
            self.agenda.reschedule(
                self.m1.item_id,
                datetime(2026, 11, 25, 10, 30, tzinfo=MANILA),
                datetime(2026, 11, 25, 11, 30, tzinfo=MANILA),
            )
        self.assertEqual(self.m1.start, datetime(2026, 11, 25, 9, 0, tzinfo=MANILA))

    def test_find_free_slot_on_empty_day_returns_eight_am(self):
        self.assertEqual(
            self.agenda.find_free_slot(date(2026, 11, 26), 60),
            datetime(2026, 11, 26, 8, 0, tzinfo=MANILA),
        )

    def test_find_free_slot_on_busy_day_picks_eight_am_before_nine_am_meeting(self):
        self.agenda.schedule(self.m1)
        self.agenda.schedule(self.m2)
        self.assertEqual(
            self.agenda.find_free_slot(self.day, 60),
            datetime(2026, 11, 25, 8, 0, tzinfo=MANILA),
        )

    def test_external_meeting_blocks_free_slot_and_full_day_spills_to_next_day(self):
        self.agenda.schedule(self.m1)
        self.agenda.schedule(self.m2)
        ext = Meeting(
            "External Block",
            self.now,
            start=datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 18, 0, tzinfo=MANILA),
            source=Meeting.SOURCE_CALENDAR_FILE,
        )
        self.agenda.set_external([ext])
        self.assertEqual(
            self.agenda.find_free_slot(self.day, 60, earliest=time(9, 0)),
            datetime(2026, 11, 26, 8, 0, tzinfo=MANILA),
        )

    def test_unknown_meeting_raises_meeting_not_found_error(self):
        with self.assertRaises(MeetingNotFoundError):
            self.agenda.find_meeting("nonexistent")

    def test_ambiguous_meeting_title_raises_ambiguous_item_error(self):
        self.agenda.schedule(
            Meeting(
                "Thesis Sync",
                self.now,
                datetime(2026, 11, 25, 9, 0, tzinfo=MANILA),
                datetime(2026, 11, 25, 10, 0, tzinfo=MANILA),
            )
        )
        self.agenda.schedule(
            Meeting(
                "Thesis Follow-up",
                self.now,
                datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
                datetime(2026, 11, 25, 12, 0, tzinfo=MANILA),
            )
        )
        with self.assertRaises(AmbiguousItemError):
            self.agenda.find_meeting("thesis")


class TestNotebook(unittest.TestCase):
    """Checks Notebook keyword search, ordering, and blank-query validation."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=MANILA)
        self.nb = Notebook()
        self.n1 = Note("Lecture Notes", self.now - timedelta(hours=1), body="OOP polymorphism")
        self.n2 = Note("Grocery", self.now, body="Coffee and milk")
        self.nb.add_note(self.n1)
        self.nb.add_note(self.n2)

    def test_search_ignores_case(self):
        self.assertEqual(self.nb.search("POLYMORPHISM"), [self.n1])

    def test_list_notes_returns_newest_first(self):
        self.assertEqual(self.nb.list_notes(), [self.n2, self.n1])

    def test_blank_search_keyword_raises_invalid_input_error(self):
        with self.assertRaises(InvalidInputError):
            self.nb.search("   ")


if __name__ == "__main__":
    unittest.main()
