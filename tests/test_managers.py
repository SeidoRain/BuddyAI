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


class TestManagers(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=MANILA)

    def test_task_manager_add_propose_restore_and_confirm(self):
        tm = TaskManager()
        past_task = Task("Late", self.now, due_date=self.now - timedelta(hours=1))
        with self.assertRaises(InvalidDueDateError):
            tm.add_task(past_task, self.now)

        proposed_past = Task(
            "From PDF",
            self.now,
            due_date=self.now - timedelta(days=1),
            status="proposed",
            source="upload",
        )
        tm.propose(proposed_past)
        self.assertEqual(len(tm.list_proposals()), 1)

        tm.confirm(proposed_past.item_id)
        self.assertEqual(proposed_past.status, "open")
        self.assertEqual(tm.list_proposals(), [])

        restored_past = Task("Loaded overdue", self.now, due_date=self.now - timedelta(days=2))
        tm.restore(restored_past)
        self.assertEqual(tm.get_task(restored_past.item_id), restored_past)

    def test_task_manager_ranking_lookup_and_update(self):
        tm = TaskManager()
        low_today = Task("Alpha", self.now, due_date=self.now + timedelta(hours=2), priority=1)
        high_today = Task("Beta", self.now, due_date=self.now + timedelta(hours=4), priority=3)
        high_later = Task("Gamma", self.now, due_date=self.now + timedelta(days=5), priority=3)
        tm.add_task(low_today, self.now)
        tm.add_task(high_today, self.now)
        tm.add_task(high_later, self.now)

        ranked = tm.list_by_priority(self.now)
        self.assertEqual([t.title for t in ranked], ["Beta", "Alpha", "Gamma"])

        self.assertIs(tm.find_task(low_today.item_id), low_today)
        self.assertIs(tm.find_task("alpha"), low_today)

        t2 = Task("Beta review", self.now, due_date=self.now + timedelta(days=1))
        tm.add_task(t2, self.now)
        self.assertIs(tm.find_task("beta"), high_today)
        with self.assertRaises(AmbiguousItemError):
            tm.find_task("bet")

        with self.assertRaises(TaskNotFoundError):
            tm.find_task("does not exist")

        with self.assertRaises(InvalidDueDateError):
            tm.update_task(low_today.item_id, title="Updated", due_date=self.now - timedelta(hours=1), now=self.now)
        self.assertEqual(low_today.title, "Alpha")

    def test_agenda_conflicts_reschedule_and_free_slots(self):
        agenda = Agenda()
        day = date(2026, 11, 25)
        m1 = Meeting(
            "Morning Sync",
            self.now,
            start=datetime(2026, 11, 25, 9, 0, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 10, 0, tzinfo=MANILA),
        )
        m2_back_to_back = Meeting(
            "Design Review",
            self.now,
            start=datetime(2026, 11, 25, 10, 0, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
        )
        agenda.schedule(m1)
        agenda.schedule(m2_back_to_back)

        overlap = Meeting(
            "Conflict Call",
            self.now,
            start=datetime(2026, 11, 25, 9, 30, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 10, 30, tzinfo=MANILA),
        )
        with self.assertRaises(SchedulingConflictError) as ctx:
            agenda.schedule(overlap)
        self.assertEqual(len(ctx.exception.conflicts), 2)
        self.assertEqual(
            ctx.exception.suggested_start,
            datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
        )

        # Rescheduling m1 into m2's slot must fail and leave m1 unchanged.
        with self.assertRaises(SchedulingConflictError):
            agenda.reschedule(
                m1.item_id,
                datetime(2026, 11, 25, 10, 30, tzinfo=MANILA),
                datetime(2026, 11, 25, 11, 30, tzinfo=MANILA),
            )
        self.assertEqual(m1.start, datetime(2026, 11, 25, 9, 0, tzinfo=MANILA))

        # External meetings also count in conflicts and free-slot search.
        ext = Meeting(
            "External Block",
            self.now,
            start=datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
            end=datetime(2026, 11, 25, 18, 0, tzinfo=MANILA),
            source="google_calendar",
        )
        agenda.set_external([ext])

        # Empty day -> 08:00
        self.assertEqual(
            agenda.find_free_slot(date(2026, 11, 26), 60),
            datetime(2026, 11, 26, 8, 0, tzinfo=MANILA),
        )
        # Busy day -> 08:00 before 09:00 meeting
        self.assertEqual(
            agenda.find_free_slot(day, 60),
            datetime(2026, 11, 25, 8, 0, tzinfo=MANILA),
        )
        # Full from 09:00 to 18:00 -> spills to next day at 08:00
        self.assertEqual(
            agenda.find_free_slot(day, 60, earliest=time(9, 0)),
            datetime(2026, 11, 26, 8, 0, tzinfo=MANILA),
        )

        with self.assertRaises(MeetingNotFoundError):
            agenda.find_meeting("nonexistent")

    def test_agenda_ambiguous_and_notebook(self):
        agenda = Agenda()
        m1 = Meeting(
            "Thesis Sync",
            self.now,
            datetime(2026, 11, 25, 9, 0, tzinfo=MANILA),
            datetime(2026, 11, 25, 10, 0, tzinfo=MANILA),
        )
        m2 = Meeting(
            "Thesis Follow-up",
            self.now,
            datetime(2026, 11, 25, 11, 0, tzinfo=MANILA),
            datetime(2026, 11, 25, 12, 0, tzinfo=MANILA),
        )
        agenda.schedule(m1)
        agenda.schedule(m2)
        with self.assertRaises(AmbiguousItemError):
            agenda.find_meeting("thesis")

        nb = Notebook()
        n1 = Note("Lecture Notes", self.now - timedelta(hours=1), body="OOP polymorphism")
        n2 = Note("Grocery", self.now, body="Coffee and milk")
        nb.add_note(n1)
        nb.add_note(n2)
        self.assertEqual(nb.search("POLYMORPHISM"), [n1])
        self.assertEqual(nb.list_notes(), [n2, n1])
        with self.assertRaises(InvalidInputError):
            nb.search("   ")


if __name__ == "__main__":
    unittest.main()
