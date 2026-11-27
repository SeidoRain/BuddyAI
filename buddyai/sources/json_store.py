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
        # utf-8-sig also reads a file that Notepad saved with a byte order mark.
        try:
            with open(filepath, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataSourceError(
                f"Failed to read JSON from '{filepath}': {exc}"
            ) from exc
        if not isinstance(data, list):
            raise DataSourceError(
                f"Expected a JSON list in '{filepath}', got {type(data).__name__}."
            )
        return data

    def _parse_records(self, filename, records, parse):
        """Turn saved records into items; a bad record raises DataSourceError.

        The error names the file and the record, so the user knows what to fix.
        """
        items = []
        for index, record in enumerate(records, start=1):
            try:
                items.append(parse(record))
            except Exception as exc:
                label = f"record {index}"
                if isinstance(record, dict) and isinstance(record.get("item_id"), str):
                    label += f" (id {record['item_id']})"
                raise DataSourceError(
                    f"Could not load {label} in '{self._file_path(filename)}': "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        return items

    def _atomic_write(self, filepath, data):
        tmp_path = None
        try:
            os.makedirs(self._data_dir, exist_ok=True)
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

        tasks = self._parse_records(self.TASKS_FILE, task_records, Task.from_dict)
        task_lookup = {task.item_id: task for task in tasks}
        meetings = self._parse_records(
            self.MEETINGS_FILE, meeting_records, Meeting.from_dict
        )
        reminders = self._parse_records(
            self.REMINDERS_FILE, reminder_records, Reminder.from_dict
        )
        notes = self._parse_records(
            self.NOTES_FILE,
            note_records,
            lambda record: Note.from_dict(record, task_lookup=task_lookup),
        )
        return tasks + meetings + reminders + notes

    def save_all(self, items):
        """Save all local work items, writing each of the four JSON files atomically.

        Each file is replaced in one step, so a file is never left half
        written; the four files are four separate writes, not one.
        """
        items = list(items)
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

        # Assumption: the loop above sent every item to exactly one of the four files.
        assert len(tasks) + len(meetings) + len(reminders) + len(notes) == len(items)

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
