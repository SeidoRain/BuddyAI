"""Agenda manager handling local and external meetings and conflict checks."""

from datetime import date, datetime, time, timedelta

from buddyai.config import ensure_aware, get_timezone
from buddyai.exceptions import (
    AmbiguousItemError,
    InvalidInputError,
    MeetingNotFoundError,
    ReadOnlySourceError,
    SchedulingConflictError,
)
from buddyai.models.meeting import Meeting


# Encapsulation & Aggregation: manages local meetings and read-only external meetings.
class Agenda:
    """Owns local meetings, tracks external meetings, and finds free slots."""

    WORK_START_HOUR = 8
    WORK_END_HOUR = 18
    SLOT_STEP_MINUTES = 15

    def __init__(self):
        self._meetings = {}
        self._external = []

    def _all_meetings_except(self, exclude_id=None):
        items = [
            meeting
            for meeting in self._meetings.values()
            if meeting.item_id != exclude_id
        ]
        items.extend(self._external)
        return items

    def find_conflicts(self, meeting, exclude_id=None):
        """Return all local and external meetings that overlap the given meeting."""
        if not isinstance(meeting, Meeting):
            raise InvalidInputError("Expected a Meeting instance.")
        conflicts = [
            existing
            for existing in self._all_meetings_except(exclude_id=exclude_id)
            if meeting.overlaps(existing)
        ]
        return sorted(conflicts, key=lambda item: item.start.timestamp())

    @classmethod
    def _round_up(cls, moment):
        """Round a time up to the next quarter hour so suggested slots look natural."""
        rounded = moment.replace(second=0, microsecond=0)
        if rounded < moment:
            rounded += timedelta(minutes=1)
        remainder = rounded.minute % cls.SLOT_STEP_MINUTES
        if remainder:
            rounded += timedelta(minutes=cls.SLOT_STEP_MINUTES - remainder)
        return rounded

    @staticmethod
    def _reject_past_start(start, now):
        """Raise InvalidInputError if `now` is given and the start is already past."""
        if now is None:
            return
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        if start < aware_now:
            raise InvalidInputError(
                f"Meeting start {start.strftime('%Y-%m-%d %H:%M')} is in the past."
            )

    def find_free_slot(self, day, minutes, earliest=None, exclude_id=None, now=None):
        """Find the earliest free slot of `minutes` within working hours (08:00-18:00).

        When `now` is given, a slot that has already started is never returned.
        """
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
            raise InvalidInputError("Meeting duration in minutes must be a positive integer.")

        max_work_minutes = (self.WORK_END_HOUR - self.WORK_START_HOUR) * 60
        if minutes > max_work_minutes:
            raise InvalidInputError(
                f"Duration of {minutes} minutes exceeds daily working hours "
                f"({self.WORK_START_HOUR:02d}:00-{self.WORK_END_HOUR:02d}:00)."
            )

        if isinstance(day, datetime):
            aware_day = ensure_aware(day, error_cls=InvalidInputError)
            target_date = aware_day.date()
            tz = aware_day.tzinfo
        elif isinstance(day, date):
            target_date = day
            tz = get_timezone()
        else:
            raise InvalidInputError("Day must be a date or aware datetime.")

        if earliest is None:
            earliest_dt = datetime.combine(
                target_date, time(self.WORK_START_HOUR, 0), tzinfo=tz
            )
        elif isinstance(earliest, datetime):
            earliest_dt = ensure_aware(earliest, tz=tz, error_cls=InvalidInputError)
        elif isinstance(earliest, time):
            if earliest.tzinfo is not None:
                raise InvalidInputError("Earliest time must not carry a timezone.")
            earliest_dt = datetime.combine(target_date, earliest, tzinfo=tz)
        else:
            raise InvalidInputError("Earliest must be None, a time, or an aware datetime.")

        not_before = None
        if now is not None:
            not_before = self._round_up(
                ensure_aware(now, tz=tz, error_cls=InvalidInputError)
            )

        duration = timedelta(minutes=minutes)
        all_existing = sorted(
            self._all_meetings_except(exclude_id=exclude_id),
            key=lambda item: item.start.timestamp(),
        )

        for day_offset in range(365):
            current_day = target_date + timedelta(days=day_offset)
            work_start = datetime.combine(
                current_day, time(self.WORK_START_HOUR, 0), tzinfo=tz
            )
            work_end = datetime.combine(
                current_day, time(self.WORK_END_HOUR, 0), tzinfo=tz
            )
            candidate = max(work_start, earliest_dt) if day_offset == 0 else work_start
            if not_before is not None:
                candidate = max(candidate, not_before)
            if candidate + duration > work_end:
                continue

            for existing in all_existing:
                existing_start = existing.start.astimezone(tz)
                existing_end = existing.end.astimezone(tz)
                if existing_end <= candidate:
                    continue
                if candidate + duration <= existing_start:
                    # Assumption: the slot lies inside the working day and has the requested length.
                    assert work_start <= candidate and candidate + duration <= work_end
                    return candidate
                candidate = max(candidate, existing_end)
                if candidate + duration > work_end:
                    break

            if candidate + duration <= work_end:
                # Same assumption as above: inside the working day, requested length.
                assert work_start <= candidate and candidate + duration <= work_end
                return candidate

        raise SchedulingConflictError(
            "No free slot is available within the next 365 days."
        )

    def _suggest_slot_for(self, start, end, exclude_id=None, now=None):
        minutes = max(1, int((end - start).total_seconds() // 60))
        max_work_minutes = (self.WORK_END_HOUR - self.WORK_START_HOUR) * 60
        if minutes > max_work_minutes:
            return None
        return self.find_free_slot(
            day=start.date(),
            minutes=minutes,
            earliest=start,
            exclude_id=exclude_id,
            now=now,
        )

    def schedule(self, meeting, now=None):
        """Schedule a meeting or raise SchedulingConflictError with nearest free slot.

        When `now` is given, a meeting that starts in the past is refused.
        """
        if not isinstance(meeting, Meeting):
            raise InvalidInputError("Expected a Meeting instance.")
        self._reject_past_start(meeting.start, now)
        conflicts = self.find_conflicts(meeting)
        if conflicts:
            suggested = self._suggest_slot_for(meeting.start, meeting.end, now=now)
            conflict_text = ", ".join(
                f"'{item.title}' ({item.start.strftime('%Y-%m-%d %H:%M')}-"
                f"{item.end.astimezone(item.start.tzinfo).strftime('%H:%M')})"
                for item in conflicts
            )
            suggestion_text = (
                f" Next free slot starts at {suggested.strftime('%Y-%m-%d %H:%M')}."
                if suggested is not None
                else ""
            )
            raise SchedulingConflictError(
                f"Meeting '{meeting.title}' conflicts with {conflict_text}.{suggestion_text}",
                conflicts=conflicts,
                suggested_start=suggested,
            )
        self._meetings[meeting.item_id] = meeting
        return meeting

    def reschedule(self, meeting_id, start, end, now=None):
        """Reschedule an existing meeting, leaving it unchanged if a conflict occurs.

        When `now` is given, moving a meeting into the past is refused.
        """
        meeting = self.get_meeting(meeting_id)
        probe = Meeting(
            title=meeting.title,
            created_at=meeting.created_at,
            start=start,
            end=end,
            item_id=meeting.item_id,
            source=meeting.source,
        )
        self._reject_past_start(probe.start, now)
        conflicts = self.find_conflicts(probe, exclude_id=meeting.item_id)
        if conflicts:
            suggested = self._suggest_slot_for(
                probe.start, probe.end, exclude_id=meeting.item_id, now=now
            )
            conflict_text = ", ".join(
                f"'{item.title}' ({item.start.strftime('%Y-%m-%d %H:%M')}-"
                f"{item.end.astimezone(item.start.tzinfo).strftime('%H:%M')})"
                for item in conflicts
            )
            suggestion_text = (
                f" Next free slot starts at {suggested.strftime('%Y-%m-%d %H:%M')}."
                if suggested is not None
                else ""
            )
            raise SchedulingConflictError(
                f"Cannot reschedule '{meeting.title}' because it conflicts with "
                f"{conflict_text}.{suggestion_text}",
                conflicts=conflicts,
                suggested_start=suggested,
            )
        meeting.reschedule(start, end)
        return meeting

    def update_meeting(self, meeting_id, title=None, location=None):
        """Rename a meeting and/or change its location, all or nothing."""
        if title is None and location is None:
            raise InvalidInputError("Provide a new title or location.")
        meeting = self.get_meeting(meeting_id)

        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise InvalidInputError("Title cannot be empty.")
        if location is not None:
            if not isinstance(location, str):
                raise InvalidInputError("Location must be text.")

        if title is not None:
            meeting.rename(title)
        if location is not None:
            meeting.set_location(location)
        return meeting

    def cancel(self, meeting_id):
        """Cancel and remove a local meeting by ID."""
        meeting = self.get_meeting(meeting_id)
        return self._meetings.pop(meeting.item_id)

    def _refuse_if_external(self, id_or_title, exact_only=False):
        """Raise ReadOnlySourceError if id_or_title matches a read-only external meeting.

        An ID must match exactly. With exact_only the title must match exactly
        too; otherwise part of the title is enough.
        """
        query_lower = id_or_title.lower()
        for mtg in self._external:
            title_lower = mtg.title.lower()
            if exact_only:
                title_matches = title_lower == query_lower
            else:
                title_matches = query_lower in title_lower
            if mtg.item_id.lower() == query_lower or title_matches:
                raise ReadOnlySourceError(
                    f"'{mtg.title}' comes from your calendar file, so BuddyAI "
                    "cannot change, move or cancel it. Change it in your calendar "
                    "app, then load the file again with /calendar <path>."
                )

    def get_meeting(self, meeting_id):
        """Retrieve a local meeting by exact ID or raise MeetingNotFoundError."""
        if not isinstance(meeting_id, str) or not meeting_id.strip():
            raise MeetingNotFoundError("Meeting ID cannot be empty.")
        key = meeting_id.strip()
        if key not in self._meetings:
            self._refuse_if_external(key, exact_only=True)
            raise MeetingNotFoundError(f"Meeting '{key}' was not found.")
        return self._meetings[key]

    def find_meeting(self, id_or_title):
        """Find a local meeting by exact ID first, then case-insensitive title.

        Order: exact local ID, exact local title, exact calendar-file ID or
        title (refused as read-only), then part of a local title.
        """
        if not isinstance(id_or_title, str) or not id_or_title.strip():
            raise InvalidInputError("Meeting ID or title cannot be empty.")
        query = id_or_title.strip()
        if query in self._meetings:
            return self._meetings[query]

        query_lower = query.lower()
        candidates = list(self._meetings.values())
        exact_matches = [
            mtg for mtg in candidates if mtg.title.lower() == query_lower
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            labels = ", ".join(f"{m.item_id} ({m.title})" for m in exact_matches)
            raise AmbiguousItemError(
                f"Multiple meetings match '{query}': {labels}.",
                matches=exact_matches,
            )
        # An exact calendar-file title wins over part of a local title, so
        # "Standup" refuses the read-only "Standup", not cancel "Standup prep".
        self._refuse_if_external(query, exact_only=True)

        partial_matches = [
            mtg for mtg in candidates if query_lower in mtg.title.lower()
        ]
        if not partial_matches:
            self._refuse_if_external(query)
            raise MeetingNotFoundError(f"No meeting found matching '{query}'.")
        if len(partial_matches) > 1:
            labels = ", ".join(f"{m.item_id} ({m.title})" for m in partial_matches)
            raise AmbiguousItemError(
                f"Multiple meetings match '{query}': {labels}.",
                matches=partial_matches,
            )
        return partial_matches[0]

    def meetings_on(self, day):
        """Return all local and external meetings occurring on the given date."""
        if isinstance(day, datetime):
            aware_day = ensure_aware(day, error_cls=InvalidInputError)
            target_date = aware_day.date()
            tz = aware_day.tzinfo
        elif isinstance(day, date):
            target_date = day
            tz = get_timezone()
        else:
            raise InvalidInputError("Day must be a date or aware datetime.")

        matches = [
            mtg
            for mtg in self.list_meetings()
            if mtg.start.astimezone(tz).date() == target_date
        ]
        return matches

    def list_meetings(self):
        """Return all local and external meetings sorted by start time."""
        combined = list(self._meetings.values()) + list(self._external)
        return sorted(combined, key=lambda mtg: mtg.start.timestamp())

    def list_local_meetings(self):
        """Return only locally managed meetings sorted by start time."""
        return sorted(
            self._meetings.values(),
            key=lambda mtg: mtg.start.timestamp(),
        )

    def set_external(self, meetings):
        """Replace the read-only list of synced external meetings."""
        validated = []
        for mtg in meetings:
            if not isinstance(mtg, Meeting):
                raise InvalidInputError("External meetings must be Meeting instances.")
            validated.append(mtg)
        self._external = validated

    def restore(self, meeting):
        """Restore a loaded local meeting without conflict checks."""
        if not isinstance(meeting, Meeting):
            raise InvalidInputError("Expected a Meeting instance.")
        self._meetings[meeting.item_id] = meeting
        return meeting
