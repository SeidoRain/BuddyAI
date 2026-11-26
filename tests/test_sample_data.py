"""Unit tests for the sample data generator in sample_data/make_sample_data.py."""

from datetime import date, datetime
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from buddyai.models import Meeting, Note, Reminder, Task
from buddyai.sources import IcsCalendarSource, JsonStore
from sample_data.make_sample_data import write_sample_data

MANILA = ZoneInfo("Asia/Manila")
TODAY = date(2026, 11, 26)
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=MANILA)


class TestSampleDataGenerator(unittest.TestCase):
    """Verifies the generated sample JSON files load cleanly and cover demo cases."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        write_sample_data(self._tmp.name, TODAY)
        self.items = JsonStore(self._tmp.name).fetch_items()

    def tearDown(self):
        self._tmp.cleanup()

    def test_written_folder_loads_with_json_store(self):
        self.assertGreater(len(self.items), 0)

    def test_sample_data_contains_all_four_item_types(self):
        self.assertTrue(any(isinstance(i, Task) for i in self.items))
        self.assertTrue(any(isinstance(i, Meeting) for i in self.items))
        self.assertTrue(any(isinstance(i, Reminder) for i in self.items))
        self.assertTrue(any(isinstance(i, Note) for i in self.items))

    def test_sample_data_includes_an_overdue_task_and_a_proposed_task(self):
        tasks = [i for i in self.items if isinstance(i, Task)]
        self.assertTrue(any(t.is_overdue(NOW) for t in tasks))
        self.assertTrue(any(t.status == "proposed" for t in tasks))

    def test_sample_data_includes_a_meeting_today_and_a_one_off_reminder_today(self):
        meetings = [i for i in self.items if isinstance(i, Meeting)]
        reminders = [i for i in self.items if isinstance(i, Reminder)]
        self.assertTrue(any(m.is_due(NOW) for m in meetings))
        self.assertTrue(
            any(r.repeat == "none" and r.is_due(NOW) for r in reminders)
        )

    def test_note_action_items_are_the_same_task_objects_returned_by_fetch(self):
        tasks_by_id = {i.item_id: i for i in self.items if isinstance(i, Task)}
        notes = [i for i in self.items if isinstance(i, Note)]
        linked_notes = [n for n in notes if n.action_items]
        self.assertGreater(len(linked_notes), 0)
        for note in linked_notes:
            for action_task in note.action_items:
                self.assertIn(action_task.item_id, tasks_by_id)
                self.assertIs(action_task, tasks_by_id[action_task.item_id])

    def test_every_datetime_in_sample_data_is_timezone_aware(self):
        for item in self.items:
            self.assertIsNotNone(item.created_at.tzinfo)
            if isinstance(item, Task) and item.due_date is not None:
                self.assertIsNotNone(item.due_date.tzinfo)
            elif isinstance(item, Meeting):
                self.assertIsNotNone(item.start.tzinfo)
                self.assertIsNotNone(item.end.tzinfo)
            elif isinstance(item, Reminder):
                self.assertIsNotNone(item.remind_at.tzinfo)

    def test_running_generator_twice_with_same_date_produces_identical_files(self):
        with tempfile.TemporaryDirectory() as other_dir:
            write_sample_data(other_dir, TODAY)
            for filename in (
                JsonStore.TASKS_FILE,
                JsonStore.MEETINGS_FILE,
                JsonStore.REMINDERS_FILE,
                JsonStore.NOTES_FILE,
            ):
                with open(os.path.join(self._tmp.name, filename), "r", encoding="utf-8") as first:
                    text_first = first.read()
                with open(os.path.join(other_dir, filename), "r", encoding="utf-8") as second:
                    text_second = second.read()
                self.assertEqual(text_first, text_second)

    def test_generated_sample_calendar_loads_with_expected_counts(self):
        ics_path = os.path.join(self._tmp.name, "sample_calendar.ics")
        self.assertTrue(os.path.isfile(ics_path))
        source = IcsCalendarSource(ics_path, clock=lambda: NOW, tz=MANILA)
        meetings = source.fetch_items()
        self.assertEqual(len(meetings), 5)
        self.assertEqual(source.loaded_count, 5)
        self.assertEqual(source.recurring_count, 1)
        self.assertEqual(source.all_day_count, 1)
        self.assertEqual(source.skipped_count, 1)
        titles = [m.title for m in meetings]
        self.assertIn("Department meeting", titles)
        self.assertIn("Midterm review, Section B", titles)


if __name__ == "__main__":
    unittest.main()
