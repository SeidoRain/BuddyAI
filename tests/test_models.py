"""Unit tests for domain models, validation, serialization, and polymorphic scoring."""

from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from buddyai.exceptions import InvalidDueDateError, InvalidInputError
from buddyai.models import Contact, Meeting, Note, Reminder, Task

MANILA = ZoneInfo("Asia/Manila")


class TestTaskScoring(unittest.TestCase):
    """Checks Task is_due, is_overdue, and priority_score across deadline boundaries."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)

    def test_a_task_overdue_by_one_minute_is_overdue_due_and_scores_fifty(self):
        task = Task(
            "Overdue by 1m",
            self.now,
            due_date=self.now - timedelta(minutes=1),
            priority=Task.PRIORITY_MEDIUM,
        )
        self.assertTrue(task.is_overdue(self.now))
        self.assertTrue(task.is_due(self.now))
        self.assertEqual(task.priority_score(self.now), 50)

    def test_a_task_due_later_today_is_due_not_overdue_and_scores_forty(self):
        task = Task(
            "Due later today",
            self.now,
            due_date=self.now + timedelta(hours=3),
            priority=Task.PRIORITY_MEDIUM,
        )
        self.assertFalse(task.is_overdue(self.now))
        self.assertTrue(task.is_due(self.now))
        self.assertEqual(task.priority_score(self.now), 40)

    def test_a_task_due_in_exactly_three_days_is_not_due_and_scores_thirty(self):
        task = Task(
            "Due in exactly 3 days",
            self.now,
            due_date=self.now + timedelta(days=3),
            priority=Task.PRIORITY_MEDIUM,
        )
        self.assertFalse(task.is_due(self.now))
        self.assertEqual(task.priority_score(self.now), 30)

    def test_a_task_due_in_four_days_is_not_due_and_scores_twenty(self):
        task = Task(
            "Due in 4 days",
            self.now,
            due_date=self.now + timedelta(days=4),
            priority=Task.PRIORITY_MEDIUM,
        )
        self.assertFalse(task.is_due(self.now))
        self.assertEqual(task.priority_score(self.now), 20)

    def test_a_high_priority_task_with_no_due_date_is_not_due_and_scores_thirty(self):
        task = Task("No due date", self.now, due_date=None, priority=Task.PRIORITY_HIGH)
        self.assertFalse(task.is_due(self.now))
        self.assertEqual(task.priority_score(self.now), 30)

    def test_a_done_task_is_not_due_and_scores_zero(self):
        task = Task(
            "Completed",
            self.now,
            due_date=self.now - timedelta(days=1),
            priority=Task.PRIORITY_HIGH,
            status="done",
        )
        self.assertFalse(task.is_due(self.now))
        self.assertEqual(task.priority_score(self.now), 0)

    def test_a_proposed_task_is_not_due_and_scores_zero(self):
        task = Task(
            "Suggested",
            self.now,
            due_date=self.now,
            priority=Task.PRIORITY_HIGH,
            status="proposed",
        )
        self.assertFalse(task.is_due(self.now))
        self.assertEqual(task.priority_score(self.now), 0)


class TestMeetingAndNoteRules(unittest.TestCase):
    """Checks polymorphic due and scoring behaviour for Meeting and Note."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)

    def test_a_meeting_today_is_due_and_scores_twenty(self):
        mtg = Meeting(
            "Standup",
            self.now,
            start=self.now + timedelta(hours=2),
            end=self.now + timedelta(hours=3),
            location="Room 201",
            attendees=[Contact("Ana", "ana@example.com", "Team")],
        )
        self.assertTrue(mtg.is_due(self.now))
        self.assertEqual(mtg.priority_score(self.now), 20)
        self.assertEqual(mtg.status_note(self.now), "")

    def test_a_meeting_tomorrow_is_not_due_and_scores_zero(self):
        mtg = Meeting(
            "Tomorrow Sync",
            self.now,
            start=self.now + timedelta(days=1),
            end=self.now + timedelta(days=1, hours=1),
        )
        self.assertFalse(mtg.is_due(self.now))
        self.assertEqual(mtg.priority_score(self.now), 0)

    def test_a_note_is_never_due_and_scores_zero(self):
        note = Note("Ideas", self.now, body="Keep classes small.")
        self.assertFalse(note.is_due(self.now))
        self.assertEqual(note.priority_score(self.now), 0)
        self.assertEqual(note.status_note(self.now), "")


class TestReminderRules(unittest.TestCase):
    """Checks Reminder due rules, next_occurrence, priority_score, and status_note."""

    def setUp(self):
        self.now = datetime(2026, 11, 26, 10, 0, tzinfo=MANILA)

    def test_daily_reminder_started_two_days_ago_is_due_and_scores_twenty(self):
        rem = Reminder(
            "Daily standup ping",
            self.now,
            remind_at=self.now - timedelta(days=2) + timedelta(hours=1),
            repeat="daily",
        )
        self.assertTrue(rem.is_due(self.now))
        self.assertEqual(rem.priority_score(self.now), 20)
        self.assertEqual(rem.status_note(self.now), "")

    def test_weekly_reminder_started_seven_days_ago_is_due_with_next_in_two_hours(self):
        rem = Reminder(
            "Weekly review",
            self.now,
            remind_at=self.now - timedelta(days=7) + timedelta(hours=2),
            repeat="weekly",
        )
        self.assertEqual(rem.next_occurrence(self.now), self.now + timedelta(hours=2))
        self.assertTrue(rem.is_due(self.now))
        self.assertEqual(rem.priority_score(self.now), 20)
        self.assertEqual(rem.status_note(self.now), "")

    def test_one_off_earlier_today_is_due_scores_twenty_and_is_marked_passed(self):
        rem = Reminder("Morning pill", self.now, datetime(2026, 11, 26, 9, 0, tzinfo=MANILA))
        self.assertTrue(rem.is_due(self.now))
        self.assertEqual(rem.priority_score(self.now), 20)
        self.assertEqual(rem.status_note(self.now), "time has passed")

    def test_one_off_earlier_today_has_no_next_occurrence(self):
        rem = Reminder("Morning pill", self.now, datetime(2026, 11, 26, 9, 0, tzinfo=MANILA))
        self.assertIsNone(rem.next_occurrence(self.now))

    def test_one_off_later_today_is_due_with_no_status_note(self):
        rem = Reminder("Call adviser", self.now, datetime(2026, 11, 26, 11, 0, tzinfo=MANILA))
        self.assertTrue(rem.is_due(self.now))
        self.assertEqual(rem.status_note(self.now), "")

    def test_one_off_yesterday_is_not_due(self):
        rem = Reminder("Yesterday task", self.now, datetime(2026, 11, 25, 9, 0, tzinfo=MANILA))
        self.assertFalse(rem.is_due(self.now))
        self.assertEqual(rem.priority_score(self.now), 0)
        self.assertEqual(rem.status_note(self.now), "")

    def test_daily_reminder_from_three_days_ago_earlier_today_is_due_and_passed(self):
        rem = Reminder(
            "Daily standup",
            self.now,
            datetime(2026, 11, 23, 8, 0, tzinfo=MANILA),
            repeat="daily",
        )
        self.assertTrue(rem.is_due(self.now))
        self.assertEqual(rem.status_note(self.now), "time has passed")

    def test_daily_reminder_starting_tomorrow_is_not_due(self):
        rem = Reminder(
            "Future daily",
            self.now,
            datetime(2026, 11, 27, 8, 0, tzinfo=MANILA),
            repeat="daily",
        )
        self.assertFalse(rem.is_due(self.now))
        self.assertEqual(rem.status_note(self.now), "")

    def test_weekly_reminder_three_days_ago_is_not_due(self):
        rem = Reminder(
            "Off-day weekly",
            self.now,
            datetime(2026, 11, 23, 14, 0, tzinfo=MANILA),
            repeat="weekly",
        )
        self.assertFalse(rem.is_due(self.now))
        self.assertEqual(rem.status_note(self.now), "")


class TestModelSerialization(unittest.TestCase):
    """Checks to_dict and from_dict round-trip fidelity for every WorkItem type."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)

    def test_overdue_upload_task_round_trips_all_fields(self):
        overdue_task = Task(
            "Past deadline task",
            self.now - timedelta(days=5),
            due_date=self.now - timedelta(days=1),
            priority=3,
            status="open",
            source="upload",
        )
        restored = Task.from_dict(overdue_task.to_dict())
        self.assertEqual(restored.item_id, overdue_task.item_id)
        self.assertEqual(restored.title, overdue_task.title)
        self.assertEqual(restored.due_date, overdue_task.due_date)
        self.assertEqual(restored.priority, overdue_task.priority)
        self.assertEqual(restored.status, overdue_task.status)
        self.assertEqual(restored.source, "upload")

    def test_meeting_with_attendee_round_trips(self):
        meeting = Meeting(
            "Thesis Defense",
            self.now,
            start=self.now + timedelta(hours=1),
            end=self.now + timedelta(hours=2),
            location="AVR",
            attendees=[Contact("Prof. Cruz", "cruz@uni.edu", "CS")],
        )
        restored = Meeting.from_dict(meeting.to_dict())
        self.assertEqual(restored.to_dict(), meeting.to_dict())

    def test_reminder_round_trips(self):
        reminder = Reminder(
            "Take break", self.now, self.now + timedelta(hours=4), repeat="daily"
        )
        restored = Reminder.from_dict(reminder.to_dict())
        self.assertEqual(restored.to_dict(), reminder.to_dict())

    def test_note_round_trips_and_links_the_same_task_object(self):
        task = Task(
            "Action",
            self.now,
            due_date=self.now + timedelta(days=1),
            source="upload",
        )
        note = Note("Doc Summary", self.now, body="Key point 1", action_items=[task])
        restored = Note.from_dict(note.to_dict(), task_lookup={task.item_id: task})
        self.assertEqual(restored.to_dict(), note.to_dict())
        self.assertIs(restored.action_items[0], task)


class TestModelValidationAndStatusFlow(unittest.TestCase):
    """Checks constructor rejections and Task status/due-date transition rules."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)

    def test_blank_title_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Task("   ", self.now)

    def test_out_of_range_priority_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Task("Valid", self.now, priority=9)

    def test_boolean_priority_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Task("Valid", self.now, priority=True)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Task("Valid", datetime(2026, 11, 24, 10, 0))

    def test_zero_length_meeting_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Meeting("Bad range", self.now, self.now, self.now)

    def test_reversed_meeting_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Meeting("Reversed", self.now, self.now + timedelta(hours=1), self.now)

    def test_invalid_reminder_repeat_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Reminder("Bad repeat", self.now, self.now, repeat="hourly")

    def test_blank_contact_name_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            Contact("")

    def test_proposed_task_cannot_be_marked_done_before_confirmation(self):
        task = Task("Review draft", self.now, status="proposed")
        with self.assertRaises(InvalidInputError):
            task.mark_done()

    def test_confirm_promotes_proposed_task_to_open(self):
        task = Task("Review draft", self.now, status="proposed")
        task.confirm()
        self.assertEqual(task.status, "open")

    def test_mark_done_moves_open_task_to_done(self):
        task = Task("Review draft", self.now, status="open")
        task.mark_done()
        self.assertEqual(task.status, "done")

    def test_done_task_cannot_be_confirmed(self):
        task = Task("Review draft", self.now, status="done")
        with self.assertRaises(InvalidInputError):
            task.confirm()

    def test_setting_past_due_date_raises_invalid_due_date_error(self):
        task = Task("Review draft", self.now)
        with self.assertRaises(InvalidDueDateError):
            task.set_due_date(self.now - timedelta(minutes=1), self.now)


if __name__ == "__main__":
    unittest.main()
