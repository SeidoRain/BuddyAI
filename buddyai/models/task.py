"""Task work item with priority, due date, and lifecycle status."""

from buddyai.config import ensure_aware, parse_stored_datetime
from buddyai.exceptions import InvalidDueDateError, InvalidInputError
from buddyai.models.work_item import WorkItem


# Inheritance & Encapsulation: extends WorkItem with validated priority and status transitions.
class Task(WorkItem):
    """Represents an actionable task that can be proposed, open, or done."""

    ID_PREFIX = "task"
    ITEM_TYPE = "task"

    PRIORITY_LOW = 1
    PRIORITY_MEDIUM = 2
    PRIORITY_HIGH = 3
    VALID_PRIORITIES = (PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH)
    VALID_STATUSES = ("proposed", "open", "done")
    PRIORITY_LABELS = {
        PRIORITY_LOW: "LOW",
        PRIORITY_MEDIUM: "MEDIUM",
        PRIORITY_HIGH: "HIGH",
    }

    def __init__(
        self,
        title,
        created_at,
        due_date=None,
        priority=2,
        status="open",
        item_id=None,
        source="local",
    ):
        super().__init__(
            title=title,
            created_at=created_at,
            item_id=item_id,
            source=source,
        )
        if due_date is not None:
            due_date = ensure_aware(due_date, error_cls=InvalidDueDateError)
        self._validate_priority(priority)
        if status not in self.VALID_STATUSES:
            raise InvalidInputError(
                f"Invalid task status '{status}'. Use proposed, open, or done."
            )

        self._due_date = due_date
        self._priority = priority
        self._status = status

    @staticmethod
    def _validate_priority(priority):
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise InvalidInputError(
                "Priority must be 1 (low), 2 (medium), or 3 (high)."
            )
        if priority not in Task.VALID_PRIORITIES:
            raise InvalidInputError(
                f"Priority '{priority}' is invalid. Use 1 (low), 2 (medium), or 3 (high)."
            )

    @property
    def due_date(self):
        return self._due_date

    @property
    def priority(self):
        return self._priority

    @property
    def status(self):
        return self._status

    def confirm(self):
        """Promote a proposed task to open status."""
        if self._status != "proposed":
            raise InvalidInputError(
                f"Task '{self._title}' cannot be confirmed because its status is '{self._status}'."
            )
        self._status = "open"

    def mark_done(self):
        """Mark an open task as completed."""
        if self._status == "proposed":
            raise InvalidInputError(
                f"Task '{self._title}' is still proposed. Confirm it before marking it done."
            )
        if self._status == "done":
            raise InvalidInputError(f"Task '{self._title}' is already done.")
        self._status = "done"

    def set_due_date(self, due_date, now):
        """Validate and update the due date against the current time."""
        aware_now = ensure_aware(now, error_cls=InvalidDueDateError)
        if due_date is None:
            self._due_date = None
            return
        aware_due = ensure_aware(due_date, error_cls=InvalidDueDateError)
        if aware_due < aware_now:
            raise InvalidDueDateError(
                f"Due date {aware_due.strftime('%Y-%m-%d %H:%M')} is in the past."
            )
        self._due_date = aware_due

    def set_priority(self, priority):
        """Validate and update the task priority."""
        self._validate_priority(priority)
        self._priority = priority

    def is_overdue(self, now):
        """Return True if this open task is past its due date."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        if self._status != "open" or self._due_date is None:
            return False
        return self._due_date < aware_now

    def is_due(self, now):
        """Return True if this task is open and due today or earlier."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        if self._status != "open" or self._due_date is None:
            return False
        due_local = self._due_date.astimezone(aware_now.tzinfo)
        return due_local.date() <= aware_now.date()

    def priority_score(self, now):
        """Compute urgency score: priority * 10 plus at most one deadline bonus."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        if self._status != "open":
            return 0
        base = self._priority * 10
        if self._due_date is None:
            return base

        due_local = self._due_date.astimezone(aware_now.tzinfo)
        if due_local < aware_now:
            bonus = 30
        elif due_local.date() == aware_now.date():
            bonus = 20
        elif 0 < (due_local.date() - aware_now.date()).days <= 3:
            bonus = 10
        else:
            bonus = 0
        return base + bonus

    def summarize(self):
        """Return a single readable summary line for this task."""
        label = self.PRIORITY_LABELS.get(self._priority, str(self._priority))
        if self._due_date is not None:
            due_text = self._due_date.strftime("%Y-%m-%d %H:%M")
        else:
            due_text = "no due date"
        return (
            f"[{label}] {self._title} (due {due_text}, status: {self._status}, "
            f"id: {self._item_id})"
        )

    def to_dict(self):
        """Serialize the task to a JSON-compatible dictionary."""
        data = super().to_dict()
        data["due_date"] = (
            self._due_date.isoformat() if self._due_date is not None else None
        )
        data["priority"] = self._priority
        data["status"] = self._status
        return data

    @classmethod
    def from_dict(cls, data):
        """Restore a Task from a saved dictionary without creation-time date checks."""
        if not isinstance(data, dict):
            raise InvalidInputError("Task record must be an object.")
        created_at = parse_stored_datetime(data.get("created_at", ""))
        raw_due = data.get("due_date")
        due_date = None
        if raw_due is not None:
            try:
                due_date = parse_stored_datetime(raw_due)
            except InvalidInputError as exc:
                raise InvalidDueDateError(str(exc)) from exc
        return cls(
            title=data.get("title", ""),
            created_at=created_at,
            due_date=due_date,
            priority=data.get("priority", cls.PRIORITY_MEDIUM),
            status=data.get("status", "open"),
            item_id=data.get("item_id"),
            source=data.get("source", "local"),
        )
