"""Generate sample BuddyAI workspace data around a given date."""

import argparse
from datetime import datetime, time, timedelta, timezone
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from buddyai.config import default_clock, get_timezone, get_timezone_name, parse_date
from buddyai.models import Contact, Meeting, Note, Reminder, Task
from buddyai.sources import JsonStore

DEFAULT_OUT_DIR = os.path.join(SCRIPT_DIR, "generated")


def build_items(today):
    """Build a deterministic list of sample work items relative to today."""
    tz = get_timezone()

    def at(day_offset, hour, minute):
        return datetime.combine(
            today + timedelta(days=day_offset),
            time(hour, minute),
            tzinfo=tz,
        )

    created = at(0, 9, 0)

    task_01 = Task(
        title="Submit thesis draft to adviser",
        created_at=created,
        due_date=at(2, 17, 0),
        priority=Task.PRIORITY_HIGH,
        status="open",
        item_id="task-demo01",
    )
    task_02 = Task(
        title="Prepare slides for the final defense",
        created_at=created,
        due_date=at(1, 12, 0),
        priority=Task.PRIORITY_HIGH,
        status="open",
        item_id="task-demo02",
    )
    task_03 = Task(
        title="Return library books",
        created_at=created,
        due_date=at(-1, 17, 0),
        priority=Task.PRIORITY_LOW,
        status="open",
        item_id="task-demo03",
    )
    task_04 = Task(
        title="Email Prof. Reyes about the consultation",
        created_at=created,
        due_date=at(0, 16, 0),
        priority=Task.PRIORITY_MEDIUM,
        status="open",
        item_id="task-demo04",
    )
    task_05 = Task(
        title="Buy printer paper",
        created_at=created,
        due_date=None,
        priority=Task.PRIORITY_LOW,
        status="open",
        item_id="task-demo05",
    )
    task_06 = Task(
        title="Finish OOP lab exercise",
        created_at=created,
        due_date=at(-1, 17, 0),
        priority=Task.PRIORITY_MEDIUM,
        status="done",
        item_id="task-demo06",
    )
    task_07 = Task(
        title="Book a room for the group meeting",
        created_at=created,
        due_date=at(3, 17, 0),
        priority=Task.PRIORITY_MEDIUM,
        status="proposed",
        item_id="task-demo07",
        source="upload",
    )
    task_08 = Task(
        title="Share the meeting notes with the team",
        created_at=created,
        due_date=None,
        priority=Task.PRIORITY_MEDIUM,
        status="proposed",
        item_id="task-demo08",
        source="upload",
    )

    adviser = Contact("Prof. Reyes", "reyes@example.edu", "Thesis Adviser")
    mtg_01 = Meeting(
        title="Thesis consultation",
        created_at=created,
        start=at(0, 14, 0),
        end=at(0, 15, 0),
        location="Room 301",
        attendees=[adviser],
        item_id="mtg-demo01",
    )
    mtg_02 = Meeting(
        title="Group project sync",
        created_at=created,
        start=at(1, 13, 0),
        end=at(1, 14, 0),
        item_id="mtg-demo02",
    )
    mtg_03 = Meeting(
        title="Practice defense run",
        created_at=created,
        start=at(3, 14, 0),
        end=at(3, 16, 0),
        item_id="mtg-demo03",
    )
    mtg_04 = Meeting(
        title="Morning check-in",
        created_at=created,
        start=at(0, 8, 30),
        end=at(0, 9, 0),
        item_id="mtg-demo04",
    )

    rem_01 = Reminder(
        title="Bring the printed thesis draft",
        created_at=created,
        remind_at=at(0, 8, 0),
        repeat="none",
        item_id="rem-demo01",
    )
    rem_02 = Reminder(
        title="Back up the thesis folder",
        created_at=created,
        remind_at=at(0, 20, 0),
        repeat="none",
        item_id="rem-demo02",
    )
    rem_03 = Reminder(
        title="Review tomorrow's plan",
        created_at=created,
        remind_at=at(0, 21, 0),
        repeat="daily",
        item_id="rem-demo03",
    )
    rem_04 = Reminder(
        title="Weekly progress report",
        created_at=created,
        remind_at=at(-7, 17, 30),
        repeat="weekly",
        item_id="rem-demo04",
    )

    note_01 = Note(
        title="Summary of sample_meeting_notes.txt",
        created_at=created,
        body=(
            "The thesis group agreed to freeze the class diagram before Friday "
            "and rehearse the live demonstration together. Follow-up tasks were "
            "assigned for booking a study room and sharing the final notes."
        ),
        action_items=[task_07, task_08],
        item_id="note-demo01",
        source="upload",
    )
    note_02 = Note(
        title="Ideas for the defense demo",
        created_at=created,
        body=(
            "Show /brief first, then demonstrate an overdue task, a scheduling "
            "conflict, and a document summary with proposed tasks."
        ),
        item_id="note-demo02",
        source="local",
    )

    return [
        task_01,
        task_02,
        task_03,
        task_04,
        task_05,
        task_06,
        task_07,
        task_08,
        mtg_01,
        mtg_02,
        mtg_03,
        mtg_04,
        rem_01,
        rem_02,
        rem_03,
        rem_04,
        note_01,
        note_02,
    ]


def write_calendar_file(out_dir, today):
    """Write sample_calendar.ics exercising all supported iCalendar forms."""
    tz = get_timezone()
    tz_name = get_timezone_name()

    def local_dt(day_offset, hour, minute):
        return datetime.combine(
            today + timedelta(days=day_offset),
            time(hour, minute),
            tzinfo=tz,
        )

    def fmt_local(dt):
        return dt.strftime("%Y%m%dT%H%M%S")

    def fmt_utc(dt):
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def fmt_date(day_offset):
        return (today + timedelta(days=day_offset)).strftime("%Y%m%d")

    dept_start = local_dt(1, 10, 0)
    dept_end = local_dt(1, 11, 0)
    lab_start = local_dt(1, 15, 0)
    lab_end = local_dt(1, 16, 0)
    study_start = local_dt(2, 13, 0)
    study_end = local_dt(2, 14, 30)
    midterm_start = local_dt(3, 9, 0)
    midterm_end = local_dt(3, 10, 0)
    weekly_start = local_dt(5, 16, 0)
    weekly_end = local_dt(5, 17, 0)
    broken_start = local_dt(6, 11, 0)

    offset = local_dt(0, 12, 0).strftime("%z") or "+0800"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BuddyAI//Sample Calendar//EN",
        "BEGIN:VTIMEZONE",
        f"TZID:{tz_name}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        f"TZOFFSETFROM:{offset}",
        f"TZOFFSETTO:{offset}",
        "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        "UID:sample-dept-meeting@buddyai.example",
        "SUMMARY:Department meeting",
        f"DTSTART;TZID={tz_name}:{fmt_local(dept_start)}",
        f"DTEND;TZID={tz_name}:{fmt_local(dept_end)}",
        "LOCATION:Room 204",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:sample-lab-consultation@buddyai.example",
        "SUMMARY:Lab consultation",
        f"DTSTART:{fmt_utc(lab_start)}",
        f"DTEND:{fmt_utc(lab_end)}",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:sample-study-group@buddyai.example",
        "SUMMARY:Study group",
        f"DTSTART:{fmt_local(study_start)}",
        f"DTEND:{fmt_local(study_end)}",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:sample-midterm-review@buddyai.example",
        "SUMMARY:Midterm review\\, ",
        " Section B",
        f"DTSTART:{fmt_local(midterm_start)}",
        f"DTEND:{fmt_local(midterm_end)}",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:sample-library-closed@buddyai.example",
        "SUMMARY:Library closed",
        f"DTSTART;VALUE=DATE:{fmt_date(4)}",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:sample-weekly-lab@buddyai.example",
        "SUMMARY:Weekly lab meeting",
        f"DTSTART;TZID={tz_name}:{fmt_local(weekly_start)}",
        f"DTEND;TZID={tz_name}:{fmt_local(weekly_end)}",
        "RRULE:FREQ=WEEKLY",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "TRIGGER:-PT15M",
        "SUMMARY:Alarm reminder for lab meeting",
        "DESCRIPTION:Starts in 15 minutes",
        "END:VALARM",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:sample-broken-event@buddyai.example",
        "SUMMARY:Broken event",
        f"DTSTART:{fmt_local(broken_start)}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]

    os.makedirs(out_dir, exist_ok=True)
    ics_path = os.path.join(out_dir, "sample_calendar.ics")
    with open(ics_path, "w", encoding="utf-8", newline="") as handle:
        handle.write("\r\n".join(lines))
    return ics_path


def write_sample_data(out_dir, today):
    """Write sample JSON files and sample_calendar.ics into out_dir."""
    items = build_items(today)
    store = JsonStore(out_dir)
    store.save_all(items)
    write_calendar_file(out_dir, today)
    return items


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Write sample BuddyAI data files relative to a date."
    )
    parser.add_argument(
        "--today",
        help="Base date in YYYY-MM-DD format (defaults to today in configured timezone).",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT_DIR,
        help="Output directory (defaults to sample_data/generated).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """CLI entry point for generating sample data."""
    args = _parse_args(argv)
    today = parse_date(args.today) if args.today else default_clock().date()
    out_dir = os.path.abspath(args.out)
    write_sample_data(out_dir, today)

    try:
        rel_out = os.path.relpath(out_dir, PROJECT_ROOT)
    except ValueError:
        rel_out = out_dir

    print(f"Sample data written to: {out_dir}")
    print("Start BuddyAI on this folder in PowerShell:")
    print(f'  $env:BUDDYAI_DATA_DIR = "{rel_out}"')
    print(r"  .\.venv\Scripts\python.exe main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
