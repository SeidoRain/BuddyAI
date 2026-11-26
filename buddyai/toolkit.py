"""BuddyToolkit exposing domain actions as safe ADK tool methods."""

from datetime import datetime, time
import logging

from buddyai.config import (
    default_clock,
    ensure_aware,
    parse_date,
    parse_datetime,
    parse_due_date,
    parse_time,
)
from buddyai.exceptions import (
    BuddyError,
    InvalidInputError,
    SchedulingConflictError,
)
from buddyai.models.contact import Contact
from buddyai.models.meeting import Meeting
from buddyai.models.note import Note
from buddyai.models.reminder import Reminder
from buddyai.models.task import Task

logger = logging.getLogger(__name__)

_PRIORITY_NAMES = {
    "low": Task.PRIORITY_LOW,
    "medium": Task.PRIORITY_MEDIUM,
    "high": Task.PRIORITY_HIGH,
}


# Facade: provides the sole tool bridge between ADK agents and domain managers.
class BuddyToolkit:
    """Wraps Workspace, BriefingService, and DocumentReader into safe tool calls."""

    def __init__(self, workspace, briefing_service, document_reader, clock=None):
        self._workspace = workspace
        self._briefing_service = briefing_service
        self._document_reader = document_reader
        self._clock = clock if clock is not None else default_clock

    def current_time(self):
        """Return the current timezone-aware datetime from the configured clock."""
        return ensure_aware(self._clock())

    @staticmethod
    def _parse_priority_text(priority_text):
        cleaned = (priority_text or "").strip().lower()
        if cleaned not in _PRIORITY_NAMES:
            raise InvalidInputError(
                f"Invalid priority '{priority_text}'. Use low, medium, or high."
            )
        return _PRIORITY_NAMES[cleaned]

    @staticmethod
    def _parse_attendees_text(attendees_text):
        contacts = []
        if not attendees_text or not attendees_text.strip():
            return contacts
        for raw_entry in attendees_text.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            if "@" in entry:
                local_name = entry.split("@", 1)[0].strip() or entry
                contacts.append(Contact(name=local_name, email=entry))
            else:
                contacts.append(Contact(name=entry))
        return contacts

    @staticmethod
    def _error_response(exc):
        if isinstance(exc, SchedulingConflictError):
            return {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "conflicts": [mtg.to_dict() for mtg in exc.conflicts],
                "suggested_start": (
                    exc.suggested_start.isoformat()
                    if exc.suggested_start is not None
                    else None
                ),
            }
        if isinstance(exc, BuddyError):
            return {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        logger.exception("Unexpected error in BuddyToolkit tool.")
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": "An unexpected internal error occurred. Please try again.",
        }

    # --- Task & Reminder Tools ---

    def add_task(
        self,
        title: str,
        due: str = "",
        priority: str = "medium",
    ) -> dict:
        """Create and save a new task.

        Use when the user asks to add a to-do or task.
        `due` accepts YYYY-MM-DD (interpreted as 23:59) or YYYY-MM-DDTHH:MM, or empty.
        `priority` must be 'low', 'medium', or 'high'.
        """
        try:
            now = self.current_time()
            due_dt = (
                parse_due_date(due, tz=now.tzinfo) if due and due.strip() else None
            )
            priority_num = self._parse_priority_text(priority)
            task = Task(
                title=title,
                created_at=now,
                due_date=due_dt,
                priority=priority_num,
                status="open",
            )
            self._workspace.tasks.add_task(task, now)
            self._workspace.save()
            return {
                "status": "success",
                "task": task.to_dict(),
                "summary": f"Added task: {task.summarize()}",
            }
        except Exception as exc:
            return self._error_response(exc)

    def update_task(
        self,
        task: str,
        title: str = "",
        due: str = "",
        priority: str = "",
    ) -> dict:
        """Update an existing task's title, due date, or priority.

        `task` is a task ID or title. Empty text leaves a field unchanged.
        `due` accepts YYYY-MM-DD or YYYY-MM-DDTHH:MM. `priority` is low/medium/high.
        """
        try:
            now = self.current_time()
            target = self._workspace.tasks.find_task(task)
            new_title = title.strip() if title and title.strip() else None
            new_due = (
                parse_due_date(due, tz=now.tzinfo) if due and due.strip() else None
            )
            new_priority = (
                self._parse_priority_text(priority)
                if priority and priority.strip()
                else None
            )
            if new_title is None and new_due is None and new_priority is None:
                raise InvalidInputError("Provide at least one field to update.")
            updated = self._workspace.tasks.update_task(
                target.item_id,
                title=new_title,
                due_date=new_due,
                priority=new_priority,
                now=now,
            )
            self._workspace.save()
            return {
                "status": "success",
                "task": updated.to_dict(),
                "summary": f"Updated task: {updated.summarize()}",
            }
        except Exception as exc:
            return self._error_response(exc)

    def complete_task(self, task: str) -> dict:
        """Mark an open task as done. `task` is a task ID or title."""
        try:
            target = self._workspace.tasks.find_task(task)
            completed = self._workspace.tasks.complete_task(target.item_id)
            self._workspace.save()
            return {
                "status": "success",
                "task": completed.to_dict(),
                "summary": f"Completed task: {completed.summarize()}",
            }
        except Exception as exc:
            return self._error_response(exc)

    def delete_task(self, task: str) -> dict:
        """Delete a task permanently. `task` is a task ID or title."""
        try:
            target = self._workspace.tasks.find_task(task)
            removed = self._workspace.tasks.remove_task(target.item_id)
            self._workspace.save()
            return {
                "status": "success",
                "task": removed.to_dict(),
                "summary": f"Deleted task '{removed.title}' ({removed.item_id}).",
            }
        except Exception as exc:
            return self._error_response(exc)

    def list_tasks(self, include_done: bool = False) -> dict:
        """List open tasks ranked by urgency, flagging overdue items."""
        try:
            now = self.current_time()
            ranked = self._workspace.tasks.list_by_priority(now)
            task_dicts = []
            for item in ranked:
                record = item.to_dict()
                record["overdue"] = item.is_overdue(now)
                record["priority_score"] = item.priority_score(now)
                task_dicts.append(record)

            if include_done:
                for item in self._workspace.tasks.list_all_tasks():
                    if item.status == "done":
                        record = item.to_dict()
                        record["overdue"] = False
                        record["priority_score"] = 0
                        task_dicts.append(record)

            return {
                "status": "success",
                "tasks": task_dicts,
                "summary": f"Found {len(task_dicts)} task(s).",
            }
        except Exception as exc:
            return self._error_response(exc)

    def add_reminder(
        self,
        title: str,
        remind_at: str,
        repeat: str = "none",
    ) -> dict:
        """Create a one-off or repeating reminder.

        `remind_at` must use YYYY-MM-DDTHH:MM. `repeat` is 'none', 'daily', or 'weekly'.
        """
        try:
            now = self.current_time()
            remind_dt = parse_datetime(remind_at, tz=now.tzinfo)
            reminder = Reminder(
                title=title,
                created_at=now,
                remind_at=remind_dt,
                repeat=repeat,
            )
            self._workspace.tasks.add_reminder(reminder, now)
            self._workspace.save()
            return {
                "status": "success",
                "reminder": reminder.to_dict(),
                "summary": f"Added reminder: {reminder.summarize()}",
            }
        except Exception as exc:
            return self._error_response(exc)

    def list_proposals(self) -> dict:
        """List all proposed tasks waiting for user confirmation."""
        try:
            proposals = self._workspace.tasks.list_proposals()
            return {
                "status": "success",
                "proposals": [item.to_dict() for item in proposals],
                "summary": f"Found {len(proposals)} proposed task(s).",
            }
        except Exception as exc:
            return self._error_response(exc)

    def confirm_tasks(self, task_ids: list[str]) -> dict:
        """Confirm proposed tasks by ID so they become active open tasks."""
        try:
            if isinstance(task_ids, str):
                ids = [part.strip() for part in task_ids.split(",") if part.strip()]
            elif isinstance(task_ids, list):
                ids = [str(part).strip() for part in task_ids if str(part).strip()]
            else:
                raise InvalidInputError("task_ids must be a list of task IDs.")
            if not ids:
                raise InvalidInputError("Provide at least one task ID to confirm.")

            confirmed = self._workspace.tasks.confirm_all(ids)
            self._workspace.save()
            return {
                "status": "success",
                "tasks": [item.to_dict() for item in confirmed],
                "summary": f"Confirmed {len(confirmed)} task(s).",
            }
        except Exception as exc:
            return self._error_response(exc)

    # --- Schedule Tools ---

    def schedule_meeting(
        self,
        title: str,
        start: str,
        end: str,
        location: str = "",
        attendees: str = "",
    ) -> dict:
        """Schedule a new meeting after checking for conflicts.

        `start` and `end` must use YYYY-MM-DDTHH:MM.
        `attendees` is a comma-separated list of names or emails.
        """
        try:
            now = self.current_time()
            start_dt = parse_datetime(start, tz=now.tzinfo)
            end_dt = parse_datetime(end, tz=now.tzinfo)
            contacts = self._parse_attendees_text(attendees)
            meeting = Meeting(
                title=title,
                created_at=now,
                start=start_dt,
                end=end_dt,
                location=location,
                attendees=contacts,
            )
            self._workspace.agenda.schedule(meeting, now)
            self._workspace.save()
            return {
                "status": "success",
                "meeting": meeting.to_dict(),
                "summary": f"Scheduled: {meeting.summarize()}",
            }
        except Exception as exc:
            return self._error_response(exc)

    def reschedule_meeting(
        self,
        meeting: str,
        start: str,
        end: str,
    ) -> dict:
        """Move an existing meeting to a new time window.

        `meeting` is a meeting ID or title. `start` and `end` use YYYY-MM-DDTHH:MM.
        """
        try:
            now = self.current_time()
            target = self._workspace.agenda.find_meeting(meeting)
            start_dt = parse_datetime(start, tz=now.tzinfo)
            end_dt = parse_datetime(end, tz=now.tzinfo)
            updated = self._workspace.agenda.reschedule(
                target.item_id, start_dt, end_dt, now
            )
            self._workspace.save()
            return {
                "status": "success",
                "meeting": updated.to_dict(),
                "summary": f"Rescheduled: {updated.summarize()}",
            }
        except Exception as exc:
            return self._error_response(exc)

    def cancel_meeting(self, meeting: str) -> dict:
        """Cancel and remove a scheduled meeting. `meeting` is an ID or title."""
        try:
            target = self._workspace.agenda.find_meeting(meeting)
            cancelled = self._workspace.agenda.cancel(target.item_id)
            self._workspace.save()
            return {
                "status": "success",
                "meeting": cancelled.to_dict(),
                "summary": f"Cancelled meeting '{cancelled.title}' ({cancelled.item_id}).",
            }
        except Exception as exc:
            return self._error_response(exc)

    def find_conflicts(self, start: str, end: str) -> dict:
        """Check whether a time range conflicts with any existing meeting.

        `start` and `end` must use YYYY-MM-DDTHH:MM.
        """
        try:
            now = self.current_time()
            start_dt = parse_datetime(start, tz=now.tzinfo)
            end_dt = parse_datetime(end, tz=now.tzinfo)
            probe = Meeting(
                title="Conflict check",
                created_at=now,
                start=start_dt,
                end=end_dt,
            )
            conflicts = self._workspace.agenda.find_conflicts(probe)
            return {
                "status": "success",
                "conflicts": [mtg.to_dict() for mtg in conflicts],
                "summary": (
                    f"Found {len(conflicts)} conflicting meeting(s)."
                    if conflicts
                    else "No conflicts found for that time range."
                ),
            }
        except Exception as exc:
            return self._error_response(exc)

    def find_free_slot(
        self,
        day: str,
        minutes: int,
        earliest_time: str = "08:00",
    ) -> dict:
        """Find the earliest free meeting slot on or after a given day and time.

        `day` uses YYYY-MM-DD. `minutes` is duration in minutes. `earliest_time` uses HH:MM.
        A slot that has already passed is never returned.
        """
        try:
            target_day = parse_date(day)
            earliest = parse_time(earliest_time)
            slot_start = self._workspace.agenda.find_free_slot(
                day=target_day,
                minutes=minutes,
                earliest=earliest,
                now=self.current_time(),
            )
            return {
                "status": "success",
                "start": slot_start.isoformat(),
                "minutes": minutes,
                "summary": f"Earliest free slot starts at {slot_start.strftime('%Y-%m-%d %H:%M')}.",
            }
        except Exception as exc:
            return self._error_response(exc)

    def list_events(self, day: str = "") -> dict:
        """List scheduled meetings for a YYYY-MM-DD day, or all upcoming meetings if empty."""
        try:
            now = self.current_time()
            if day and day.strip():
                target_day = parse_date(day)
                meetings = self._workspace.agenda.meetings_on(target_day)
            else:
                meetings = [
                    mtg
                    for mtg in self._workspace.agenda.list_meetings()
                    if mtg.end >= now
                ]
            return {
                "status": "success",
                "meetings": [mtg.to_dict() for mtg in meetings],
                "summary": f"Found {len(meetings)} meeting(s).",
            }
        except Exception as exc:
            return self._error_response(exc)

    # --- Notes & Document Tools ---

    def add_note(self, title: str, body: str) -> dict:
        """Save a new note to the notebook."""
        try:
            now = self.current_time()
            note = Note(title=title, created_at=now, body=body)
            self._workspace.notebook.add_note(note)
            self._workspace.save()
            return {
                "status": "success",
                "note": note.to_dict(),
                "summary": f"Saved note: {note.summarize()}",
            }
        except Exception as exc:
            return self._error_response(exc)

    def search_notes(self, keyword: str) -> dict:
        """Search saved notes by keyword across titles and bodies."""
        try:
            matches = self._workspace.notebook.search(keyword)
            return {
                "status": "success",
                "notes": [note.to_dict() for note in matches],
                "summary": f"Found {len(matches)} matching note(s).",
            }
        except Exception as exc:
            return self._error_response(exc)

    def summarize_document(self, path: str) -> dict:
        """Summarize a PDF, PNG, JPG, or TXT file into a Note and proposed tasks."""
        try:
            now = self.current_time()
            note = self._document_reader.summarize(path, now=now)
            self._workspace.notebook.add_note(note)
            for task in note.action_items:
                self._workspace.tasks.propose(task)
            self._workspace.save()
            return {
                "status": "success",
                "note": note.to_dict(),
                "proposals": [task.to_dict() for task in note.action_items],
                "proposal_ids": [task.item_id for task in note.action_items],
                "summary": (
                    f"Saved '{note.title}' with {len(note.action_items)} proposed task(s)."
                ),
            }
        except Exception as exc:
            return self._error_response(exc)

    # --- Briefing Tool ---

    def get_daily_briefing(self, day: str = "") -> dict:
        """Generate a summary of due tasks, meetings, and reminders for a day.

        `day` uses YYYY-MM-DD, or empty for today.
        """
        try:
            now = self.current_time()
            if day and day.strip():
                target_day = parse_date(day)
                if target_day == now.date():
                    target_now = now
                else:
                    target_now = datetime.combine(
                        target_day, time(0, 0), tzinfo=now.tzinfo
                    )
            else:
                target_now = now
            briefing = self._briefing_service.build_briefing(target_now)
            return {
                "status": "success",
                "day": briefing.day.isoformat(),
                "items": [item.to_dict() for item in briefing.items],
                "briefing_text": briefing.to_text(),
                "summary": briefing.to_text(),
            }
        except Exception as exc:
            return self._error_response(exc)
