"""Unit tests for exceptions, JsonStore, DataSource, Workspace, and BriefingService."""

from datetime import datetime, timedelta
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from buddyai.briefing import BriefingService
from buddyai.exceptions import (
    AmbiguousItemError,
    BuddyError,
    DataSourceError,
    InvalidDueDateError,
    InvalidInputError,
    MeetingNotFoundError,
    NoteNotFoundError,
    ReadOnlySourceError,
    ReminderNotFoundError,
    SchedulingConflictError,
    TaskNotFoundError,
    UnsupportedFileTypeError,
)
from buddyai.models import Meeting, Note, Reminder, Task
from buddyai.sources import DataSource, JsonStore
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")


class _FakeReadOnlySource(DataSource):
    def __init__(self, items):
        super().__init__("fake_external")
        self._items = list(items)

    def fetch_items(self):
        return list(self._items)


class TestExceptionHierarchy(unittest.TestCase):
    """Verifies every custom exception subclasses BuddyError cleanly."""

    def test_all_domain_exceptions_extend_buddy_error(self):
        for exc_cls in (
            TaskNotFoundError,
            MeetingNotFoundError,
            ReminderNotFoundError,
            NoteNotFoundError,
            AmbiguousItemError,
            InvalidDueDateError,
            InvalidInputError,
            SchedulingConflictError,
            UnsupportedFileTypeError,
            DataSourceError,
            ReadOnlySourceError,
        ):
            with self.subTest(exc_cls=exc_cls.__name__):
                self.assertTrue(issubclass(exc_cls, BuddyError))

    def test_read_only_source_error_extends_data_source_error(self):
        self.assertTrue(issubclass(ReadOnlySourceError, DataSourceError))


class TestJsonStoreRoundTrip(unittest.TestCase):
    """Verifies JsonStore empty load, full round trip, atomic writes, and corrupt files."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        self.store = JsonStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _populate_and_save(self):
        task = Task(
            "Write tests", self.now, due_date=self.now + timedelta(days=1), priority=3
        )
        meeting = Meeting(
            "Review",
            self.now,
            self.now + timedelta(hours=2),
            self.now + timedelta(hours=3),
        )
        reminder = Reminder(
            "Hydrate", self.now, self.now + timedelta(hours=1), repeat="daily"
        )
        note = Note("Summary", self.now, body="Details", action_items=[task])

        ws = Workspace(sources=[self.store])
        ws.tasks.add_task(task, self.now)
        ws.agenda.schedule(meeting)
        ws.tasks.add_reminder(reminder)
        ws.notebook.add_note(note)
        ws.save()
        return task, meeting, reminder, note

    def test_empty_folder_returns_no_items(self):
        self.assertEqual(self.store.fetch_items(), [])

    def test_save_leaves_no_temporary_files_behind(self):
        self._populate_and_save()
        leftover_tmp = [
            name for name in os.listdir(self._tmp.name) if name.startswith(".tmp_")
        ]
        self.assertEqual(leftover_tmp, [])

    def test_note_action_item_is_the_same_task_object_after_reload(self):
        task, _, _, note = self._populate_and_save()
        reloaded = Workspace(sources=[self.store])
        reloaded.load()
        loaded_task = reloaded.tasks.get_task(task.item_id)
        loaded_note = reloaded.notebook.get_note(note.item_id)
        self.assertIs(loaded_note.action_items[0], loaded_task)

    def test_meeting_and_reminder_reload_after_save(self):
        _, meeting, _, _ = self._populate_and_save()
        reloaded = Workspace(sources=[self.store])
        reloaded.load()
        self.assertEqual(reloaded.agenda.get_meeting(meeting.item_id).title, "Review")
        self.assertEqual(len(reloaded.tasks.list_reminders()), 1)

    def test_corrupt_tasks_file_raises_data_source_error_and_is_not_overwritten(self):
        tasks_path = os.path.join(self._tmp.name, JsonStore.TASKS_FILE)
        with open(tasks_path, "w", encoding="utf-8") as handle:
            handle.write("{corrupt json")
        with self.assertRaises(DataSourceError) as ctx:
            self.store.fetch_items()
        self.assertIn("tasks.json", str(ctx.exception))
        with open(tasks_path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{corrupt json")


class TestReadOnlySourceContract(unittest.TestCase):
    """Checks that read-only DataSource subclasses refuse all write methods."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)
        self.meeting = Meeting(
            "External Sync",
            self.now,
            self.now + timedelta(hours=4),
            self.now + timedelta(hours=5),
            source=Meeting.SOURCE_CALENDAR_FILE,
        )
        self.source = _FakeReadOnlySource([self.meeting])

    def test_save_item_raises_read_only_source_error(self):
        with self.assertRaises(ReadOnlySourceError):
            self.source.save_item(self.meeting)

    def test_remove_item_raises_read_only_source_error(self):
        with self.assertRaises(ReadOnlySourceError):
            self.source.remove_item(self.meeting.item_id)

    def test_save_all_raises_read_only_source_error(self):
        with self.assertRaises(ReadOnlySourceError):
            self.source.save_all([self.meeting])


class TestWorkspaceAndBriefing(unittest.TestCase):
    """Checks Workspace sync isolation, polymorphic ordering, and DailyBriefing rendering."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        self.store = JsonStore(self._tmp.name)
        self.synced_meeting = Meeting(
            "External Sync",
            self.now,
            self.now + timedelta(hours=4),
            self.now + timedelta(hours=5),
            source=Meeting.SOURCE_CALENDAR_FILE,
        )
        self.ro_source = _FakeReadOnlySource([self.synced_meeting])
        self.ws = Workspace(sources=[self.store, self.ro_source])
        self.ws.load()
        self.ws.sync()

        self.task = Task(
            "Submit draft",
            self.now,
            due_date=self.now + timedelta(hours=1),
            priority=3,
        )
        self.reminder = Reminder(
            "Stretch", self.now, self.now + timedelta(minutes=30)
        )
        self.note = Note("Scratch", self.now, body="Not due")
        self.ws.tasks.add_task(self.task, self.now)
        self.ws.tasks.add_reminder(self.reminder)
        self.ws.notebook.add_note(self.note)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_does_not_persist_synced_items(self):
        self.ws.save()
        persisted_ids = {item.item_id for item in self.store.fetch_items()}
        self.assertNotIn(self.synced_meeting.item_id, persisted_ids)
        self.assertIn(self.task.item_id, persisted_ids)

    def test_items_for_day_orders_local_and_synced_items_by_score_and_title(self):
        day_items = self.ws.items_for_day(self.now)
        self.assertEqual(
            [item.item_id for item in day_items],
            [self.task.item_id, self.synced_meeting.item_id, self.reminder.item_id],
        )

    def test_briefing_text_contains_task_synced_meeting_and_reminder(self):
        text = BriefingService(self.ws).build_briefing(self.now).to_text()
        self.assertIn("Submit draft", text)
        self.assertIn("External Sync", text)
        self.assertIn("Stretch", text)

    def test_empty_workspace_briefing_says_nothing_due_or_scheduled(self):
        empty_ws = Workspace(sources=[])
        empty_text = BriefingService(empty_ws).build_briefing(self.now).to_text()
        self.assertIn("Nothing due or scheduled", empty_text)

    def test_briefing_marks_passed_reminder_on_same_day(self):
        ws = Workspace(sources=[])
        passed_rem = Reminder(
            "Bring thesis draft",
            self.now,
            datetime(2026, 11, 24, 9, 0, tzinfo=MANILA),
        )
        ws.tasks.add_reminder(passed_rem)
        text = BriefingService(ws).build_briefing(self.now).to_text()
        self.assertIn("Bring thesis draft", text)
        self.assertIn("[time has passed]", text)


if __name__ == "__main__":
    unittest.main()
