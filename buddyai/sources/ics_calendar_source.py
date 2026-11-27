"""Read-only DataSource that loads Meeting items from an iCalendar (.ics) file."""

from datetime import datetime, timezone
import hashlib
import os
import re
from zoneinfo import ZoneInfo

from buddyai.config import default_clock, get_timezone
from buddyai.exceptions import DataSourceError
from buddyai.models.meeting import Meeting
from buddyai.sources.data_source import DataSource


# Inheritance and abstraction: a second DataSource subclass; it stays read-only,
# so it never has to implement the write methods that DataSource refuses.
class IcsCalendarSource(DataSource):
    """Reads VEVENT records from a local .ics file as read-only Meeting items."""

    DEFAULT_NAME = "ics_calendar"
    # YYYYMMDDTHHMMSS, with a Z at the end for UTC times.
    _DATE_TIME_SHAPE = re.compile(r"^[0-9]{8}T[0-9]{6}Z?$", re.IGNORECASE)

    def __init__(self, path, name=DEFAULT_NAME, clock=None, tz=None):
        super().__init__(name)
        self._path = os.path.abspath(os.fspath(path))
        self._clock = clock if clock is not None else default_clock
        self._tz = tz
        self._loaded_count = 0
        self._skipped_count = 0
        self._all_day_count = 0
        self._recurring_count = 0

    @property
    def path(self):
        return self._path

    @property
    def loaded_count(self):
        return self._loaded_count

    @property
    def skipped_count(self):
        return self._skipped_count

    @property
    def all_day_count(self):
        return self._all_day_count

    @property
    def recurring_count(self):
        return self._recurring_count

    def _read_text(self):
        """Read UTF-8 text (stripping any BOM) or raise DataSourceError."""
        if not os.path.exists(self._path):
            raise DataSourceError(f"Calendar file not found: {self._path}")
        try:
            with open(self._path, "r", encoding="utf-8-sig") as handle:
                return handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise DataSourceError(
                f"Could not read calendar file '{self._path}': {exc}"
            ) from exc

    @staticmethod
    def _unfold(text):
        """Split lines on CRLF/LF/CR and unfold RFC 5545 continuation lines."""
        raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        unfolded = []
        for line in raw_lines:
            if line and line[0] in (" ", "\t") and unfolded:
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)
        return unfolded

    @staticmethod
    def _split_line(line):
        """Parse 'NAME;PARAM=VAL:VALUE' into (name, params_dict, value)."""
        colon_index = -1
        in_quotes = False
        for index, char in enumerate(line):
            if char == '"':
                in_quotes = not in_quotes
            elif char == ":" and not in_quotes:
                colon_index = index
                break
        if colon_index == -1:
            return None, {}, ""

        header = line[:colon_index]
        value = line[colon_index + 1:]

        # Split header parts on semicolons outside double quotes.
        tokens = []
        current = []
        in_quotes = False
        for char in header:
            if char == '"':
                in_quotes = not in_quotes
                current.append(char)
            elif char == ";" and not in_quotes:
                tokens.append("".join(current))
                current = []
            else:
                current.append(char)
        tokens.append("".join(current))

        name = tokens[0].strip().upper()
        params = {}
        for token in tokens[1:]:
            if "=" not in token:
                continue
            key, raw_val = token.split("=", 1)
            cleaned_val = raw_val.strip()
            if (
                len(cleaned_val) >= 2
                and cleaned_val[0] == '"'
                and cleaned_val[-1] == '"'
            ):
                cleaned_val = cleaned_val[1:-1]
            params[key.strip().upper()] = cleaned_val
        return name, params, value

    def _collect_events(self, lines):
        """Extract VEVENT property maps inside VCALENDAR, ignoring nested blocks."""
        saw_calendar = False
        stack = []
        events = []
        current_event = None

        for line in lines:
            if not line.strip():
                continue
            name, params, value = self._split_line(line)
            if not name:
                continue
            if name == "BEGIN":
                comp = value.strip().upper()
                if comp == "VCALENDAR":
                    saw_calendar = True
                stack.append(comp)
                if (
                    comp == "VEVENT"
                    and "VCALENDAR" in stack
                    and "VTIMEZONE" not in stack
                ):
                    current_event = {}
                continue
            if name == "END":
                comp = value.strip().upper()
                if comp == "VEVENT" and current_event is not None and stack and stack[-1] == "VEVENT":
                    events.append(current_event)
                    current_event = None
                if stack and stack[-1] == comp:
                    stack.pop()
                continue

            if current_event is not None and stack and stack[-1] == "VEVENT":
                if name not in current_event:
                    current_event[name] = (params, value)

        if not saw_calendar:
            raise DataSourceError(
                f"'{os.path.basename(self._path)}' is not an iCalendar (.ics) file."
            )
        return events

    @staticmethod
    def _unescape(text):
        """Unescape iCalendar TEXT sequences (\\, \\; \\n \\N \\\\)."""
        result = []
        index = 0
        length = len(text)
        while index < length:
            char = text[index]
            if char == "\\" and index + 1 < length:
                nxt = text[index + 1]
                if nxt in ("n", "N"):
                    result.append(" ")
                    index += 2
                    continue
                if nxt in (",", ";", "\\"):
                    result.append(nxt)
                    index += 2
                    continue
            result.append(char)
            index += 1
        return "".join(result)

    @staticmethod
    def _is_all_day(params, value):
        cleaned = value.strip()
        if params.get("VALUE", "").upper() == "DATE":
            return True
        return len(cleaned) == 8 and cleaned.isdigit()

    @classmethod
    def _parse_when(cls, params, value, tz):
        """Parse an iCalendar UTC, TZID, or floating date-time into tz."""
        cleaned = value.strip()
        # strptime would read "20261128T1030" as 10:03, so check the shape first.
        if not cls._DATE_TIME_SHAPE.match(cleaned):
            raise ValueError(f"Unreadable date-time '{cleaned}'")
        if cleaned.endswith(("Z", "z")):
            parsed = datetime.strptime(cleaned[:-1], "%Y%m%dT%H%M%S")
            return parsed.replace(tzinfo=timezone.utc).astimezone(tz)
        tzid = params.get("TZID", "").strip()
        if tzid:
            zone = ZoneInfo(tzid)
            parsed = datetime.strptime(cleaned, "%Y%m%dT%H%M%S")
            return parsed.replace(tzinfo=zone).astimezone(tz)
        parsed = datetime.strptime(cleaned, "%Y%m%dT%H%M%S")
        return parsed.replace(tzinfo=tz)

    @staticmethod
    def _make_item_id(uid, raw_dtstart, title, seen_ids):
        """Build a stable 'ics-<8 hex>' ID, adding -2/-3 on collisions."""
        key = uid.strip() if uid and uid.strip() else title
        digest = hashlib.sha1(
            f"{key}|{raw_dtstart.strip()}".encode("utf-8")
        ).hexdigest()[:8]
        base_id = f"ics-{digest}"
        if base_id not in seen_ids:
            seen_ids.add(base_id)
            return base_id
        suffix = 2
        while f"{base_id}-{suffix}" in seen_ids:
            suffix += 1
        unique_id = f"{base_id}-{suffix}"
        seen_ids.add(unique_id)
        return unique_id

    def _event_to_meeting(self, event, tz, seen_ids):
        """Convert one VEVENT property dict into ('meeting', Meeting, recurring) or ('all_day', None, False)."""
        if "DTSTART" not in event:
            raise ValueError("Missing DTSTART")
        start_params, start_val = event["DTSTART"]
        if self._is_all_day(start_params, start_val):
            return "all_day", None, False

        if "DTEND" not in event:
            raise ValueError("Missing DTEND")
        end_params, end_val = event["DTEND"]
        if self._is_all_day(end_params, end_val):
            raise ValueError("DTEND is date-only while DTSTART has a time")

        start = self._parse_when(start_params, start_val, tz)
        end = self._parse_when(end_params, end_val, tz)

        raw_summary = event.get("SUMMARY", ({}, ""))[1]
        title = self._unescape(raw_summary).strip() or "(no title)"
        raw_location = event.get("LOCATION", ({}, ""))[1]
        location = self._unescape(raw_location).strip()
        uid = event.get("UID", ({}, ""))[1]
        item_id = self._make_item_id(uid, start_val, title, seen_ids)

        meeting = Meeting(
            title=title,
            created_at=self._clock(),
            start=start,
            end=end,
            location=location,
            item_id=item_id,
            source=Meeting.SOURCE_CALENDAR_FILE,
        )
        return "meeting", meeting, ("RRULE" in event)

    def fetch_items(self):
        """Read and parse the .ics file, returning Meeting items sorted by start."""
        text = self._read_text()
        lines = self._unfold(text)
        events = self._collect_events(lines)
        tz = self._tz if self._tz is not None else get_timezone()

        meetings = []
        seen_ids = set()
        skipped = 0
        all_day = 0
        recurring = 0

        for event in events:
            try:
                kind, meeting, is_recurring = self._event_to_meeting(
                    event, tz, seen_ids
                )
            # Any problem with one event (bad date, year 9999, unknown TZID)
            # skips that event only; the rest of the calendar still loads.
            except Exception:
                skipped += 1
                continue
            if kind == "all_day":
                all_day += 1
                continue
            meetings.append(meeting)
            if is_recurring:
                recurring += 1

        meetings.sort(key=lambda mtg: mtg.start.timestamp())
        self._loaded_count = len(meetings)
        self._skipped_count = skipped
        self._all_day_count = all_day
        self._recurring_count = recurring
        return meetings
