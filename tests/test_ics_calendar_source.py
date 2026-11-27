"""Unit tests for IcsCalendarSource iCalendar (.ics) parsing and read-only rules."""

from datetime import datetime
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from buddyai.exceptions import DataSourceError, ReadOnlySourceError
from buddyai.models import Meeting
from buddyai.sources import IcsCalendarSource

MANILA = ZoneInfo("Asia/Manila")
FIXED_NOW = datetime(2026, 11, 26, 9, 0, tzinfo=MANILA)


def _wrap_calendar(*blocks):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BuddyAI//Test//EN"]
    lines.extend(blocks)
    lines.append("END:VCALENDAR")
    lines.append("")
    return "\r\n".join(lines)


class _IcsTestCase(unittest.TestCase):
    """Base test case writing temporary .ics files with a fixed clock and Manila zone."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def write_ics(self, content, name="cal.ics", encoding="utf-8"):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
        return path

    def load_source(self, content, name="cal.ics", encoding="utf-8"):
        path = self.write_ics(content, name=name, encoding=encoding)
        source = IcsCalendarSource(path, clock=lambda: FIXED_NOW, tz=MANILA)
        items = source.fetch_items()
        return source, items


class TestIcsDateTimeForms(_IcsTestCase):
    """Checks UTC, TZID, floating, and all-day date-time handling."""

    def test_utc_event_is_converted_to_manila_time(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:utc-1@example.com",
            "SUMMARY:UTC Sync",
            "DTSTART:20261127T060000Z",
            "DTEND:20261127T070000Z",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(len(items), 1)
        self.assertEqual(source.loaded_count, 1)
        self.assertEqual(items[0].start, datetime(2026, 11, 27, 14, 0, tzinfo=MANILA))
        self.assertEqual(items[0].end, datetime(2026, 11, 27, 15, 0, tzinfo=MANILA))

    def test_tzid_event_is_converted_to_manila_time(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:tzid-1@example.com",
            "SUMMARY:Tokyo Call",
            'DTSTART;TZID="Asia/Tokyo":20261127T150000',
            'DTEND;TZID="Asia/Tokyo":20261127T160000',
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].start, datetime(2026, 11, 27, 14, 0, tzinfo=MANILA))
        self.assertEqual(items[0].end, datetime(2026, 11, 27, 15, 0, tzinfo=MANILA))

    def test_floating_event_uses_configured_timezone(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:float-1@example.com",
            "SUMMARY:Floating Session",
            "DTSTART:20261127T103000",
            "DTEND:20261127T113000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].start, datetime(2026, 11, 27, 10, 30, tzinfo=MANILA))
        self.assertEqual(items[0].end, datetime(2026, 11, 27, 11, 30, tzinfo=MANILA))

    def test_all_day_event_is_skipped_and_counted(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:allday-1@example.com",
            "SUMMARY:Holiday",
            "DTSTART;VALUE=DATE:20261130",
            "DTEND;VALUE=DATE:20261201",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.loaded_count, 0)
        self.assertEqual(source.all_day_count, 1)
        self.assertEqual(source.skipped_count, 0)

    def test_past_event_is_loaded(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:past-1@example.com",
            "SUMMARY:Earlier Kickoff",
            "DTSTART:20200110T090000",
            "DTEND:20200110T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Earlier Kickoff")


class TestIcsTextAndStructure(_IcsTestCase):
    """Checks folding, escaping, metadata, nested blocks, and file encodings."""

    def test_folded_summary_with_space_and_tab_is_unfolded(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:fold-1@example.com",
            "SUMMARY:Part One ",
            " Part Two",
            "\tPart Three",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(items[0].title, "Part One Part TwoPart Three")

    def test_escaped_comma_semicolon_newline_and_backslash_are_unescaped(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:esc-1@example.com",
            r"SUMMARY:Review\, Part A\; Notes\nLine 2\\End",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(items[0].title, "Review, Part A; Notes Line 2\\End")

    def test_location_is_read_and_unescaped(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:loc-1@example.com",
            "SUMMARY:Lab Demo",
            r"LOCATION:Room 204\, Building B",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(items[0].location, "Room 204, Building B")

    def test_valarm_summary_does_not_overwrite_event_title(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:alarm-1@example.com",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "SUMMARY:Ignore this alarm title",
            "END:VALARM",
            "SUMMARY:Real Event Title",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(items[0].title, "Real Event Title")

    def test_vtimezone_dtstart_is_not_read_as_an_event(self):
        ics = _wrap_calendar(
            "BEGIN:VTIMEZONE",
            "TZID:Asia/Manila",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            "TZOFFSETFROM:+0800",
            "TZOFFSETTO:+0800",
            "END:STANDARD",
            "END:VTIMEZONE",
        )
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 0)

    def test_missing_summary_defaults_to_no_title(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:notitle-1@example.com",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(items[0].title, "(no title)")

    def test_rrule_event_loads_once_and_increments_recurring_count(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:rec-1@example.com",
            "SUMMARY:Weekly Sync",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "RRULE:FREQ=WEEKLY",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(len(items), 1)
        self.assertEqual(source.recurring_count, 1)

    def test_source_is_calendar_file_and_created_at_comes_from_clock(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:meta-1@example.com",
            "SUMMARY:Check Meta",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(items[0].source, Meeting.SOURCE_CALENDAR_FILE)
        self.assertEqual(items[0].created_at, FIXED_NOW)

    def test_bom_at_start_of_file_is_accepted(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:bom-1@example.com",
            "SUMMARY:BOM Event",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics, encoding="utf-8-sig")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "BOM Event")

    def test_lf_only_line_endings_are_accepted(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:lf-1@example.com",
            "SUMMARY:Unix Line Ends",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        ).replace("\r\n", "\n")
        _, items = self.load_source(ics)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Unix Line Ends")


class TestIcsIdsAndSkippedEvents(_IcsTestCase):
    """Checks deterministic IDs, collision suffixes, and malformed event skipping."""

    def test_id_format_is_ics_plus_eight_hex_chars_and_stable_across_loads(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:stable-1@example.com",
            "SUMMARY:Stable Event",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        path = self.write_ics(ics)
        first = IcsCalendarSource(path, clock=lambda: FIXED_NOW, tz=MANILA).fetch_items()[0]
        second = IcsCalendarSource(path, clock=lambda: FIXED_NOW, tz=MANILA).fetch_items()[0]
        self.assertRegex(first.item_id, r"^ics-[0-9a-f]{8}$")
        self.assertEqual(first.item_id, second.item_id)

    def test_same_uid_with_different_dtstart_gets_different_ids(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:shared@example.com",
            "SUMMARY:Occurrence 1",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:shared@example.com",
            "SUMMARY:Occurrence 2",
            "DTSTART:20261128T090000",
            "DTEND:20261128T100000",
            "END:VEVENT",
        )
        _, items = self.load_source(ics)
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0].item_id, items[1].item_id)

    def test_two_identical_events_get_dash_two_suffix(self):
        event = [
            "BEGIN:VEVENT",
            "UID:dup@example.com",
            "SUMMARY:Duplicate",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        ]
        ics = _wrap_calendar(*(event + event))
        _, items = self.load_source(ics)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].item_id, f"{items[0].item_id}-2")

    def test_missing_dtend_is_skipped(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:noend@example.com",
            "SUMMARY:No End",
            "DTSTART:20261127T090000",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 1)

    def test_duration_without_dtend_is_skipped(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:dur@example.com",
            "SUMMARY:Duration Only",
            "DTSTART:20261127T090000",
            "DURATION:PT1H",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 1)

    def test_end_before_start_is_skipped(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:rev@example.com",
            "SUMMARY:Backwards",
            "DTSTART:20261127T110000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 1)

    def test_unknown_tzid_is_skipped(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:win@example.com",
            "SUMMARY:Windows Zone",
            "DTSTART;TZID=Singapore Standard Time:20261127T090000",
            "DTEND;TZID=Singapore Standard Time:20261127T100000",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 1)

    def test_one_bad_event_does_not_stop_other_events_from_loading(self):
        ics = _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:bad@example.com",
            "SUMMARY:Bad",
            "DTSTART:not-a-date",
            "DTEND:20261127T100000",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "UID:good@example.com",
            "SUMMARY:Good Event",
            "DTSTART:20261127T090000",
            "DTEND:20261127T100000",
            "END:VEVENT",
        )
        source, items = self.load_source(ics)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Good Event")
        self.assertEqual(source.skipped_count, 1)


class TestIcsEventsThatUsedToCrash(_IcsTestCase):
    """Checks that odd dates or zones skip one event instead of stopping the load."""

    def _single_event(self, dtstart, dtend):
        return _wrap_calendar(
            "BEGIN:VEVENT",
            "UID:odd@example.com",
            "SUMMARY:Odd Event",
            dtstart,
            dtend,
            "END:VEVENT",
        )

    def test_an_event_in_the_year_9999_is_skipped(self):
        ics = self._single_event("DTSTART:99991231T230000Z", "DTEND:99991231T235900Z")
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 1)

    def test_a_folder_name_as_tzid_is_skipped(self):
        ics = self._single_event(
            "DTSTART;TZID=Asia:20261127T090000", "DTEND;TZID=Asia:20261127T100000"
        )
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 1)

    def test_a_time_without_seconds_is_skipped_not_misread(self):
        ics = self._single_event("DTSTART:20261128T1030", "DTEND:20261128T1130")
        source, items = self.load_source(ics)
        self.assertEqual(items, [])
        self.assertEqual(source.skipped_count, 1)


class TestIcsErrorsAndReadOnlyContract(_IcsTestCase):
    """Checks DataSourceError cases and inherited ReadOnlySourceError behaviour."""

    def test_missing_file_raises_data_source_error(self):
        missing = os.path.join(self._tmp.name, "missing.ics")
        source = IcsCalendarSource(missing, clock=lambda: FIXED_NOW, tz=MANILA)
        with self.assertRaises(DataSourceError):
            source.fetch_items()

    def test_directory_path_raises_data_source_error(self):
        source = IcsCalendarSource(self._tmp.name, clock=lambda: FIXED_NOW, tz=MANILA)
        with self.assertRaises(DataSourceError):
            source.fetch_items()

    def test_non_calendar_text_file_raises_data_source_error(self):
        path = self.write_ics("Hello, this is plain text, not iCalendar.\n")
        source = IcsCalendarSource(path, clock=lambda: FIXED_NOW, tz=MANILA)
        with self.assertRaises(DataSourceError):
            source.fetch_items()

    def test_non_utf8_file_raises_data_source_error(self):
        path = os.path.join(self._tmp.name, "binary.ics")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe\x00\x80not utf8")
        source = IcsCalendarSource(path, clock=lambda: FIXED_NOW, tz=MANILA)
        with self.assertRaises(DataSourceError):
            source.fetch_items()

    def test_empty_calendar_with_no_events_returns_empty_list(self):
        source, items = self.load_source(_wrap_calendar())
        self.assertEqual(items, [])
        self.assertEqual(source.loaded_count, 0)

    def test_source_is_read_only_and_refuses_all_write_methods(self):
        path = self.write_ics(_wrap_calendar())
        source = IcsCalendarSource(path, clock=lambda: FIXED_NOW, tz=MANILA)
        meeting = Meeting(
            "Local",
            FIXED_NOW,
            datetime(2026, 11, 27, 9, 0, tzinfo=MANILA),
            datetime(2026, 11, 27, 10, 0, tzinfo=MANILA),
        )
        self.assertTrue(source.is_read_only)
        with self.assertRaises(ReadOnlySourceError):
            source.save_item(meeting)
        with self.assertRaises(ReadOnlySourceError):
            source.remove_item(meeting.item_id)
        with self.assertRaises(ReadOnlySourceError):
            source.save_all([meeting])


if __name__ == "__main__":
    unittest.main()
