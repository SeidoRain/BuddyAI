"""Atomic JSON persistence backend implementing the DataSource interface."""

import json
import os
import tempfile

from buddyai.exceptions import DataSourceError
from buddyai.models.meeting import Meeting
from buddyai.models.note import Note
from buddyai.models.reminder import Reminder
from buddyai.models.task import Task
from buddyai.sources.data_source import DataSource


# Inheritance: implements writable atomic JSON storage for local BuddyAI items.
class JsonStore(DataSource):
    """Stores tasks, meetings, reminders, and notes in indented UTF-8 JSON files."""

    TASKS_FILE = "tasks.json"
    MEETINGS_FILE = "meetings.json"
    REMINDERS_FILE = "reminders.json"
    NOTES_FILE = "notes.json"

    def __init__(self, data_dir, name="local_json"):
        super().__init__(name=name)
        self._data_dir = os.fspath(data_dir)

    @property
    def is_read_only(self):
        return False

    @property
    def data_dir(self):
        return self._data_dir

    def _file_path(self, filename):
        return os.path.join(self._data_dir, filename)

    def _read_records(self, filename):
        filepath = self._file_path(filename)
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise DataSourceError(
                f"Failed to read JSON from '{filepath}': {exc}"
            ) from exc
        if not isinstance(data, list):
            raise DataSourceError(
                f"Expected a JSON list in '{filepath}', got {type(data).__name__}."
            )
        return data

    def _atomic_write(self, filepath, data):
        os.makedirs(self._data_dir, exist_ok=True)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._data_dir,
                prefix=".tmp_",
                suffix=".json",
                delete=False,
            ) as tmp_file:
                tmp_path = tmp_file.name
                json.dump(data, tmp_file, indent=2, ensure_ascii=False)
                tmp_file.write("\n")
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, filepath)
        except OSError as exc:
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise DataSourceError(
                f"Failed to write JSON to '{filepath}': {exc}"
            ) from exc

    def fetch_items(self):
        """Load all persisted work items and reconnect Note action items to Tasks."""
        task_records = self._read_records(self.TASKS_FILE)
        meeting_records = self._read_records(self.MEETINGS_FILE)
        reminder_records = self._read_records(self.REMINDERS_FILE)
        note_records = self._read_records(self.NOTES_FILE)

        tasks = [Task.from_dict(record) for record in task_records]
        task_lookup = {task.item_id: task for task in tasks}
        meetings = [Meeting.from_dict(record) for record in meeting_records]
        reminders = [Reminder.from_dict(record) for record in reminder_records]
        notes = [
            Note.from_dict(record, task_lookup=task_lookup)
            for record in note_records
        ]
        return tasks + meetings + reminders + notes

    def save_all(self, items):
        """Atomically save all local work items across the four JSON files."""
        tasks = []
        meetings = []
        reminders = []
        notes = []

        for item in items:
            if isinstance(item, Task):
                tasks.append(item.to_dict())
            elif isinstance(item, Meeting):
                meetings.append(item.to_dict())
            elif isinstance(item, Reminder):
                reminders.append(item.to_dict())
            elif isinstance(item, Note):
                notes.append(item.to_dict())
            else:
                raise DataSourceError(
                    f"Unsupported item type '{type(item).__name__}' for JsonStore."
                )

        self._atomic_write(self._file_path(self.TASKS_FILE), tasks)
        self._atomic_write(self._file_path(self.MEETINGS_FILE), meetings)
        self._atomic_write(self._file_path(self.REMINDERS_FILE), reminders)
        self._atomic_write(self._file_path(self.NOTES_FILE), notes)

    def save_item(self, item):
        """Insert or update a single item in the JSON store."""
        existing = self.fetch_items()
        updated = [obj for obj in existing if obj.item_id != item.item_id]
        updated.append(item)
        self.save_all(updated)

    def remove_item(self, item_id):
        """Remove an item by ID from the JSON store."""
        existing = self.fetch_items()
        remaining = [obj for obj in existing if obj.item_id != item_id]
        self.save_all(remaining)
