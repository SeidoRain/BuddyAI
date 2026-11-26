"""Unit tests for JsonStore, DataSource, Workspace, Briefing, and exceptions."""

from datetime import datetime, timedelta
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from buddyai.briefing import BriefingService
from buddyai.exceptions import (
    AmbiguousItemError,
    AuthenticationRequiredError,
    BuddyError,
    DataSourceError,
    InvalidDueDateError,
    InvalidInputError,
    MeetingNotFoundError,
    ReadOnlySourceError,
    SchedulingConflictError,
    TaskNotFoundError,
    UnsupportedFileTypeError,
)
from buddyai.models import Meeting, Note, Reminder, Task
from buddyai.sources import DataSource, JsonStore
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")


class FakeReadOnlySource(DataSource):
    def __init__(self, items):
        super().__init__("fake_google")
        self._items = list(items)

    def fetch_items(self):
        return list(self._items)


class TestStorageAndWorkspace(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)

    def test_exception_hierarchy(self):
        for exc_cls in (
            TaskNotFoundError,
            MeetingNotFoundError,
            AmbiguousItemError,
            InvalidDueDateError,
            InvalidInputError,
            SchedulingConflictError,
            UnsupportedFileTypeError,
            DataSourceError,
            ReadOnlySourceError,
            AuthenticationRequiredError,
        ):
            self.assertTrue(issubclass(exc_cls, BuddyError))
        self.assertTrue(issubclass(ReadOnlySourceError, DataSourceError))
        self.assertTrue(issubclass(AuthenticationRequiredError, DataSourceError))
        auth_err = AuthenticationRequiredError("Sign in required.")
        self.assertIsInstance(auth_err, DataSourceError)

    def test_json_store_round_trip_atomic_and_corrupt_handling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonStore(tmpdir)
            self.assertEqual(store.fetch_items(), [])

            task = Task("Write tests", self.now, due_date=self.now + timedelta(days=1), priority=3)
            meeting = Meeting(
                "Review",
                self.now,
                self.now + timedelta(hours=2),
                self.now + timedelta(hours=3),
            )
            reminder = Reminder("Hydrate", self.now, self.now + timedelta(hours=1), repeat="daily")
            note = Note("Summary", self.now, body="Details", action_items=[task])

            ws = Workspace(sources=[store])
            ws.tasks.add_task(task, self.now)
            ws.agenda.schedule(meeting)
            ws.tasks.add_reminder(reminder)
            ws.notebook.add_note(note)
            ws.save()

            leftover_tmp = [
                name for name in os.listdir(tmpdir) if name.startswith(".tmp_")
            ]
            self.assertEqual(leftover_tmp, [])

            reloaded = Workspace(sources=[store])
            reloaded.load()
            loaded_task = reloaded.tasks.get_task(task.item_id)
            loaded_note = reloaded.notebook.get_note(note.item_id)
            self.assertIs(loaded_note.action_items[0], loaded_task)
            self.assertEqual(reloaded.agenda.get_meeting(meeting.item_id).title, "Review")
            self.assertEqual(len(reloaded.tasks.list_reminders()), 1)

            tasks_path = os.path.join(tmpdir, JsonStore.TASKS_FILE)
            with open(tasks_path, "w", encoding="utf-8") as handle:
                handle.write("{corrupt json")
            with self.assertRaises(DataSourceError) as ctx:
                store.fetch_items()
            self.assertIn("tasks.json", str(ctx.exception))
            with open(tasks_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "{corrupt json")

    def test_read_only_source_and_workspace_polymorphism(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonStore(tmpdir)
            synced_meeting = Meeting(
                "External Sync",
                self.now,
                self.now + timedelta(hours=4),
                self.now + timedelta(hours=5),
                source="google",
            )
            ro_source = FakeReadOnlySource([synced_meeting])

            with self.assertRaises(ReadOnlySourceError):
                ro_source.save_item(synced_meeting)
            with self.assertRaises(ReadOnlySourceError):
                ro_source.remove_item(synced_meeting.item_id)
            with self.assertRaises(ReadOnlySourceError):
                ro_source.save_all([synced_meeting])

            ws = Workspace(sources=[store, ro_source])
            ws.load()
            ws.sync()

            task = Task("Submit draft", self.now, due_date=self.now + timedelta(hours=1), priority=3)
            reminder = Reminder("Stretch", self.now, self.now + timedelta(minutes=30))
            note = Note("Scratch", self.now, body="Not due")
            ws.tasks.add_task(task, self.now)
            ws.tasks.add_reminder(reminder)
            ws.notebook.add_note(note)

            ws.save()
            # Synced external items must never be persisted to JsonStore.
            persisted_ids = {item.item_id for item in store.fetch_items()}
            self.assertNotIn(synced_meeting.item_id, persisted_ids)
            self.assertIn(task.item_id, persisted_ids)

            day_items = ws.items_for_day(self.now)
            self.assertEqual(
                [item.item_id for item in day_items],
                [task.item_id, synced_meeting.item_id, reminder.item_id],
            )

            briefing = BriefingService(ws).build_briefing(self.now)
            text = briefing.to_text()
            self.assertIn("Submit draft", text)
            self.assertIn("External Sync", text)
            self.assertIn("Stretch", text)

            empty_ws = Workspace(sources=[])
            empty_text = BriefingService(empty_ws).build_briefing(self.now).to_text()
            self.assertIn("Nothing due or scheduled", empty_text)


if __name__ == "__main__":
    unittest.main()
