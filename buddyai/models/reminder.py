"""Reminder work item supporting one-off, daily, and weekly schedules."""

from datetime import datetime, timedelta

from buddyai.config import ensure_aware, parse_stored_datetime
from buddyai.exceptions import InvalidInputError
from buddyai.models.work_item import WorkItem


# Inheritance: extends WorkItem with repeat-aware next-occurrence calculation.
class Reminder(WorkItem):
    """Represents a one-off or repeating reminder."""

    ID_PREFIX = "rem"
    ITEM_TYPE = "reminder"
    VALID_REPEATS = ("none", "daily", "weekly")

    def __init__(
        self,
        title,
        created_at,
        remind_at,
        repeat="none",
        item_id=None,
        source="local",
    ):
        super().__init__(
            title=title,
            created_at=created_at,
            item_id=item_id,
            source=source,
        )
        aware_remind = ensure_aware(remind_at, error_cls=InvalidInputError)
        if not isinstance(repeat, str) or repeat.strip().lower() not in self.VALID_REPEATS:
            raise InvalidInputError(
                f"Invalid repeat value '{repeat}'. Use none, daily, or weekly."
            )
        self._remind_at = aware_remind
        self._repeat = repeat.strip().lower()

    @property
    def remind_at(self):
        return self._remind_at

    @property
    def repeat(self):
        return self._repeat

    def next_occurrence(self, now):
        """Return the next aware occurrence at or after now, or None if expired."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        base = self._remind_at.astimezone(aware_now.tzinfo)
        if base >= aware_now:
            return base
        if self._repeat == "none":
            return None
        if self._repeat == "daily":
            days_diff = (aware_now.date() - base.date()).days
            candidate = base + timedelta(days=days_diff)
            if candidate < aware_now:
                candidate = candidate + timedelta(days=1)
            return candidate

        weeks_diff = (aware_now.date() - base.date()).days // 7
        candidate = base + timedelta(days=weeks_diff * 7)
        if candidate < aware_now:
            candidate = candidate + timedelta(days=7)
        return candidate

    def occurrence_on(self, day, tz):
        """Return the aware datetime when this reminder fires on day in tz, or None."""
        first = self._remind_at.astimezone(tz)
        gap = (day - first.date()).days
        if gap < 0:
            return None
        if self._repeat == "none":
            return datetime.combine(day, first.timetz()) if gap == 0 else None
        if self._repeat == "daily":
            return datetime.combine(day, first.timetz())
        return datetime.combine(day, first.timetz()) if gap % 7 == 0 else None

    def is_due(self, now):
        """Return True if this reminder fires on the given day."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        return self.occurrence_on(aware_now.date(), aware_now.tzinfo) is not None

    def status_note(self, now):
        """Return 'time has passed' if today's reminder time is before now."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        occurrence = self.occurrence_on(aware_now.date(), aware_now.tzinfo)
        if occurrence is not None and occurrence < aware_now:
            return "time has passed"
        return ""

    def priority_score(self, now):
        """Return 20 when the reminder occurs today, otherwise 0."""
        return 20 if self.is_due(now) else 0

    def summarize(self):
        """Return a single readable summary line for this reminder."""
        repeat_note = (
            f", repeats {self._repeat}" if self._repeat != "none" else ""
        )
        when_text = self._remind_at.strftime("%Y-%m-%d %H:%M")
        return f"Reminder: {self._title} (at {when_text}{repeat_note}, id: {self._item_id})"

    def to_dict(self):
        """Serialize the reminder to a JSON-compatible dictionary."""
        data = super().to_dict()
        data["remind_at"] = self._remind_at.isoformat()
        data["repeat"] = self._repeat
        return data

    @classmethod
    def from_dict(cls, data):
        """Restore a Reminder from a saved dictionary."""
        if not isinstance(data, dict):
            raise InvalidInputError("Reminder record must be an object.")
        created_at = parse_stored_datetime(data.get("created_at", ""))
        remind_at = parse_stored_datetime(data.get("remind_at", ""))
        return cls(
            title=data.get("title", ""),
            created_at=created_at,
            remind_at=remind_at,
            repeat=data.get("repeat", "none"),
            item_id=data.get("item_id"),
            source=data.get("source", "local"),
        )
