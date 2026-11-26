"""Meeting work item with start/end times, location, and Contact attendees."""

from buddyai.config import ensure_aware, parse_stored_datetime
from buddyai.exceptions import InvalidInputError
from buddyai.models.contact import Contact
from buddyai.models.work_item import WorkItem


# Inheritance & Aggregation: extends WorkItem and holds a list of Contact objects.
class Meeting(WorkItem):
    """Represents a scheduled meeting on the user's agenda."""

    ID_PREFIX = "mtg"
    ITEM_TYPE = "meeting"

    def __init__(
        self,
        title,
        created_at,
        start,
        end,
        location="",
        attendees=None,
        item_id=None,
        source="local",
    ):
        super().__init__(
            title=title,
            created_at=created_at,
            item_id=item_id,
            source=source,
        )
        aware_start, aware_end = self._validate_range(start, end)
        if not isinstance(location, str):
            raise InvalidInputError("Location must be text.")

        self._start = aware_start
        self._end = aware_end
        self._location = location.strip()
        self._attendees = []
        if attendees is not None:
            for person in attendees:
                self.add_attendee(person)

    @staticmethod
    def _validate_range(start, end):
        aware_start = ensure_aware(start, error_cls=InvalidInputError)
        aware_end = ensure_aware(end, error_cls=InvalidInputError)
        if aware_end <= aware_start:
            raise InvalidInputError("Meeting end time must be after start time.")
        return aware_start, aware_end

    @property
    def start(self):
        return self._start

    @property
    def end(self):
        return self._end

    @property
    def location(self):
        return self._location

    @property
    def attendees(self):
        return list(self._attendees)

    def overlaps(self, other):
        """Return True if this meeting overlaps another meeting (back-to-back is False)."""
        if not isinstance(other, Meeting):
            raise InvalidInputError("Overlap check requires another Meeting.")
        return self._start < other._end and other._start < self._end

    def reschedule(self, start, end):
        """Validate and update the meeting start and end times."""
        aware_start, aware_end = self._validate_range(start, end)
        self._start = aware_start
        self._end = aware_end

    def add_attendee(self, contact):
        """Add a Contact to the meeting attendee list."""
        if not isinstance(contact, Contact):
            raise InvalidInputError("Attendee must be a Contact.")
        self._attendees.append(contact)

    def is_due(self, now):
        """Return True if this meeting starts on the given day."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        start_local = self._start.astimezone(aware_now.tzinfo)
        return start_local.date() == aware_now.date()

    def priority_score(self, now):
        """Return 20 when the meeting starts today, otherwise 0."""
        return 20 if self.is_due(now) else 0

    def summarize(self):
        """Return a single readable summary line for this meeting."""
        end_local = self._end.astimezone(self._start.tzinfo)
        if self._start.date() == end_local.date():
            span = (
                f"{self._start.strftime('%Y-%m-%d %H:%M')}-"
                f"{end_local.strftime('%H:%M')}"
            )
        else:
            span = (
                f"{self._start.strftime('%Y-%m-%d %H:%M')} to "
                f"{end_local.strftime('%Y-%m-%d %H:%M')}"
            )
        place = f" @ {self._location}" if self._location else ""
        return f"Meeting: {self._title} ({span}{place}, id: {self._item_id})"

    def to_dict(self):
        """Serialize the meeting and its attendees to a JSON-compatible dictionary."""
        data = super().to_dict()
        data["start"] = self._start.isoformat()
        data["end"] = self._end.isoformat()
        data["location"] = self._location
        data["attendees"] = [person.to_dict() for person in self._attendees]
        return data

    @classmethod
    def from_dict(cls, data):
        """Restore a Meeting from a saved dictionary."""
        if not isinstance(data, dict):
            raise InvalidInputError("Meeting record must be an object.")
        created_at = parse_stored_datetime(data.get("created_at", ""))
        start = parse_stored_datetime(data.get("start", ""))
        end = parse_stored_datetime(data.get("end", ""))
        raw_attendees = data.get("attendees", [])
        if not isinstance(raw_attendees, list):
            raise InvalidInputError("Meeting attendees must be a list.")
        attendees = [Contact.from_dict(item) for item in raw_attendees]
        return cls(
            title=data.get("title", ""),
            created_at=created_at,
            start=start,
            end=end,
            location=data.get("location", ""),
            attendees=attendees,
            item_id=data.get("item_id"),
            source=data.get("source", "local"),
        )
