"""Unit tests for domain models, encapsulation, and polymorphic scoring."""

from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from buddyai.exceptions import InvalidDueDateError, InvalidInputError
from buddyai.models import Contact, Meeting, Note, Reminder, Task

MANILA = ZoneInfo("Asia/Manila")


class TestModels(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)

    def test_task_priority_score_and_is_due_boundaries(self):
        overdue_1m = Task(
            "Overdue by 1m",
            self.now,
            due_date=self.now - timedelta(minutes=1),
            priority=Task.PRIORITY_MEDIUM,
        )
        due_today = Task(
            "Due later today",
            self.now,
            due_date=self.now + timedelta(hours=3),
            priority=Task.PRIORITY_MEDIUM,
        )
        due_3d = Task(
            "Due in exactly 3 days",
            self.now,
            due_date=self.now + timedelta(days=3),
            priority=Task.PRIORITY_MEDIUM,
        )
        due_4d = Task(
            "Due in 4 days",
            self.now,
            due_date=self.now + timedelta(days=4),
            priority=Task.PRIORITY_MEDIUM,
        )
        no_due = Task(
            "No due date",
            self.now,
            due_date=None,
            priority=Task.PRIORITY_HIGH,
        )
        done_task = Task(
            "Completed",
            self.now,
            due_date=self.now - timedelta(days=1),
            priority=Task.PRIORITY_HIGH,
            status="done",
        )
        proposed_task = Task(
            "Suggested",
            self.now,
            due_date=self.now,
            priority=Task.PRIORITY_HIGH,
            status="proposed",
        )

        self.assertTrue(overdue_1m.is_overdue(self.now))
        self.assertTrue(overdue_1m.is_due(self.now))
        self.assertEqual(overdue_1m.priority_score(self.now), 50)

        self.assertFalse(due_today.is_overdue(self.now))
        self.assertTrue(due_today.is_due(self.now))
        self.assertEqual(due_today.priority_score(self.now), 40)

        self.assertFalse(due_3d.is_due(self.now))
        self.assertEqual(due_3d.priority_score(self.now), 30)

        self.assertFalse(due_4d.is_due(self.now))
        self.assertEqual(due_4d.priority_score(self.now), 20)

        self.assertFalse(no_due.is_due(self.now))
        self.assertEqual(no_due.priority_score(self.now), 30)

        self.assertFalse(done_task.is_due(self.now))
        self.assertEqual(done_task.priority_score(self.now), 0)

        self.assertFalse(proposed_task.is_due(self.now))
        self.assertEqual(proposed_task.priority_score(self.now), 0)

    def test_meeting_reminder_and_note_polymorphic_rules(self):
        mtg_today = Meeting(
            "Standup",
            self.now,
            start=self.now + timedelta(hours=2),
            end=self.now + timedelta(hours=3),
            location="Room 201",
            attendees=[Contact("Ana", "ana@example.com", "Team")],
        )
        mtg_tomorrow = Meeting(
            "Tomorrow Sync",
            self.now,
            start=self.now + timedelta(days=1),
            end=self.now + timedelta(days=1, hours=1),
        )
        self.assertTrue(mtg_today.is_due(self.now))
        self.assertEqual(mtg_today.priority_score(self.now), 20)
        self.assertFalse(mtg_tomorrow.is_due(self.now))
        self.assertEqual(mtg_tomorrow.priority_score(self.now), 0)

        rem_today = Reminder(
            "Daily standup ping",
            self.now,
            remind_at=self.now - timedelta(days=2) + timedelta(hours=1),
            repeat="daily",
        )
        rem_expired = Reminder(
            "Old one-off",
            self.now,
            remind_at=self.now - timedelta(hours=1),
            repeat="none",
        )
        rem_weekly = Reminder(
            "Weekly review",
            self.now,
            remind_at=self.now - timedelta(days=7) + timedelta(hours=2),
            repeat="weekly",
        )
        self.assertTrue(rem_today.is_due(self.now))
        self.assertEqual(rem_today.priority_score(self.now), 20)
        self.assertIsNone(rem_expired.next_occurrence(self.now))
        self.assertFalse(rem_expired.is_due(self.now))
        self.assertEqual(rem_expired.priority_score(self.now), 0)
        self.assertEqual(rem_weekly.next_occurrence(self.now), self.now + timedelta(hours=2))
        self.assertTrue(rem_weekly.is_due(self.now))

        note = Note("Ideas", self.now, body="Keep classes small.")
        self.assertFalse(note.is_due(self.now))
        self.assertEqual(note.priority_score(self.now), 0)

    def test_to_dict_from_dict_round_trip_including_overdue(self):
        overdue_task = Task(
            "Past deadline task",
            self.now - timedelta(days=5),
            due_date=self.now - timedelta(days=1),
            priority=3,
            status="open",
            source="upload",
        )
        restored_task = Task.from_dict(overdue_task.to_dict())
        self.assertEqual(restored_task.item_id, overdue_task.item_id)
        self.assertEqual(restored_task.title, overdue_task.title)
        self.assertEqual(restored_task.due_date, overdue_task.due_date)
        self.assertEqual(restored_task.priority, overdue_task.priority)
        self.assertEqual(restored_task.status, overdue_task.status)
        self.assertEqual(restored_task.source, "upload")

        meeting = Meeting(
            "Thesis Defense",
            self.now,
            start=self.now + timedelta(hours=1),
            end=self.now + timedelta(hours=2),
            location="AVR",
            attendees=[Contact("Prof. Cruz", "cruz@uni.edu", "CS")],
        )
        restored_meeting = Meeting.from_dict(meeting.to_dict())
        self.assertEqual(restored_meeting.to_dict(), meeting.to_dict())

        reminder = Reminder("Take break", self.now, self.now + timedelta(hours=4), repeat="daily")
        restored_rem = Reminder.from_dict(reminder.to_dict())
        self.assertEqual(restored_rem.to_dict(), reminder.to_dict())

        note = Note("Doc Summary", self.now, body="Key point 1", action_items=[overdue_task])
        restored_note = Note.from_dict(note.to_dict(), task_lookup={overdue_task.item_id: overdue_task})
        self.assertEqual(restored_note.to_dict(), note.to_dict())
        self.assertIs(restored_note.action_items[0], overdue_task)

    def test_encapsulation_and_status_transitions(self):
        with self.assertRaises(InvalidInputError):
            Task("   ", self.now)
        with self.assertRaises(InvalidInputError):
            Task("Valid", self.now, priority=9)
        with self.assertRaises(InvalidInputError):
            Task("Valid", self.now, priority=True)
        with self.assertRaises(InvalidInputError):
            Task("Valid", datetime(2026, 11, 24, 10, 0))
        with self.assertRaises(InvalidInputError):
            Meeting("Bad range", self.now, self.now, self.now)
        with self.assertRaises(InvalidInputError):
            Meeting("Reversed", self.now, self.now + timedelta(hours=1), self.now)
        with self.assertRaises(InvalidInputError):
            Reminder("Bad repeat", self.now, self.now, repeat="hourly")
        with self.assertRaises(InvalidInputError):
            Contact("")

        task = Task("Review draft", self.now, status="proposed")
        with self.assertRaises(InvalidInputError):
            task.mark_done()
        task.confirm()
        self.assertEqual(task.status, "open")
        task.mark_done()
        self.assertEqual(task.status, "done")
        with self.assertRaises(InvalidInputError):
            task.confirm()

        with self.assertRaises(InvalidDueDateError):
            task.set_due_date(self.now - timedelta(minutes=1), self.now)


if __name__ == "__main__":
    unittest.main()
