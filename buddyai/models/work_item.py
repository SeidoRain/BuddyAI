"""Abstract base class for all BuddyAI work items."""

from abc import ABC, abstractmethod
import uuid

from buddyai.config import ensure_aware
from buddyai.exceptions import InvalidInputError


# Abstraction: defines the shared contract for tasks, meetings, reminders, and notes.
class WorkItem(ABC):
    """Abstract base class for trackable items stored in a Workspace."""

    ID_PREFIX = "item"
    ITEM_TYPE = "work_item"

    def __init__(self, title, created_at, item_id=None, source="local"):
        if not isinstance(title, str) or not title.strip():
            raise InvalidInputError("Title cannot be empty.")
        aware_created = ensure_aware(created_at, error_cls=InvalidInputError)
        if not isinstance(source, str) or not source.strip():
            raise InvalidInputError("Source cannot be empty.")

        if item_id is None:
            resolved_id = f"{self.ID_PREFIX}-{uuid.uuid4().hex[:8]}"
        else:
            if not isinstance(item_id, str) or not item_id.strip():
                raise InvalidInputError("Item ID cannot be empty.")
            resolved_id = item_id.strip()

        self._item_id = resolved_id
        self._title = title.strip()
        self._created_at = aware_created
        self._source = source.strip()

    @property
    def item_id(self):
        return self._item_id

    @property
    def title(self):
        return self._title

    @property
    def created_at(self):
        return self._created_at

    @property
    def source(self):
        return self._source

    def rename(self, title):
        """Validate and update the item's title."""
        if not isinstance(title, str) or not title.strip():
            raise InvalidInputError("Title cannot be empty.")
        self._title = title.strip()

    @abstractmethod
    def is_due(self, now):
        """Return True if this item should appear in the day's schedule/briefing."""

    @abstractmethod
    def summarize(self):
        """Return a concise single-line human-readable summary."""

    @abstractmethod
    def priority_score(self, now):
        """Return an integer urgency score relative to the given current time."""

    def status_note(self, now):
        """Return a short note to show next to the item in a briefing, or an empty string."""
        return ""

    def to_dict(self):
        """Serialize base WorkItem fields into a dictionary."""
        return {
            "type": self.ITEM_TYPE,
            "item_id": self._item_id,
            "title": self._title,
            "created_at": self._created_at.isoformat(),
            "source": self._source,
        }

    @classmethod
    @abstractmethod
    def from_dict(cls, data):
        """Restore a saved WorkItem instance from a dictionary."""
