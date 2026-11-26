"""Note work item holding freeform text and linked Task action items."""

from buddyai.config import parse_stored_datetime
from buddyai.exceptions import InvalidInputError
from buddyai.models.task import Task
from buddyai.models.work_item import WorkItem


# Inheritance & Aggregation: extends WorkItem and links to existing Task objects.
class Note(WorkItem):
    """Represents a user note or summarized document with suggested action items."""

    ID_PREFIX = "note"
    ITEM_TYPE = "note"

    def __init__(
        self,
        title,
        created_at,
        body="",
        action_items=None,
        item_id=None,
        source="local",
    ):
        super().__init__(
            title=title,
            created_at=created_at,
            item_id=item_id,
            source=source,
        )
        if not isinstance(body, str):
            raise InvalidInputError("Note body must be text.")
        self._body = body
        self._action_items = []
        if action_items is not None:
            for task in action_items:
                self.add_action_item(task)

    @property
    def body(self):
        return self._body

    @property
    def action_items(self):
        return list(self._action_items)

    def add_action_item(self, task):
        """Link a Task as an action item on this note."""
        if not isinstance(task, Task):
            raise InvalidInputError("Action item must be a Task.")
        if task not in self._action_items:
            self._action_items.append(task)

    def is_due(self, now):
        """Notes are reference records and are never due on a schedule."""
        return False

    def priority_score(self, now):
        """Notes always have a priority score of 0."""
        return 0

    def summarize(self):
        """Return a single readable summary line for this note."""
        preview = " ".join(self._body.strip().split())
        if len(preview) > 60:
            preview = preview[:57] + "..."
        extra = f" - {preview}" if preview else ""
        if self._action_items:
            extra += f" [{len(self._action_items)} action item(s)]"
        return f"Note: {self._title}{extra} (id: {self._item_id})"

    def to_dict(self):
        """Serialize the note, storing action item links as task IDs."""
        data = super().to_dict()
        data["body"] = self._body
        data["action_item_ids"] = [task.item_id for task in self._action_items]
        return data

    @classmethod
    def from_dict(cls, data, task_lookup=None):
        """Restore a Note and reconnect action_item_ids to Task instances."""
        if not isinstance(data, dict):
            raise InvalidInputError("Note record must be an object.")
        created_at = parse_stored_datetime(data.get("created_at", ""))
        note = cls(
            title=data.get("title", ""),
            created_at=created_at,
            body=data.get("body", ""),
            item_id=data.get("item_id"),
            source=data.get("source", "local"),
        )
        raw_ids = data.get("action_item_ids", [])
        if not isinstance(raw_ids, list):
            raise InvalidInputError("Note action_item_ids must be a list.")
        if task_lookup is not None:
            for task_id in raw_ids:
                task = task_lookup.get(task_id)
                if task is not None:
                    note.add_action_item(task)
        return note
