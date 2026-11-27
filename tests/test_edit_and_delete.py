"""Unit tests for editing meetings and deleting reminders, notes, and done tasks."""

from datetime import datetime, timedelta
import json
import logging
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from buddyai.agents import (
    BriefingAgentProfile,
    CoordinatorProfile,
    NotesAgentProfile,
    ScheduleAgentProfile,
    TaskAgentProfile,
    VoiceCoordinatorProfile,
)
from buddyai.briefing import BriefingService
from buddyai.document_reader import DocumentReader
from buddyai.exceptions import (
    AmbiguousItemError,
    InvalidInputError,
    NoteNotFoundError,
    ReadOnlySourceError,
    ReminderNotFoundError,
    TaskNotFoundError,
)
from buddyai.managers import Agenda, Notebook, TaskManager
from buddyai.models import Meeting, Note, Reminder, Task
from buddyai.sources import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 24, 9, 0, tzinfo=MANILA)


def _meeting(title, hour=14, location=""):
    start = datetime(2026, 11, 25, hour, 0, tzinfo=MANILA)
    return Meeting(
        title, NOW, start, start + timedelta(hours=1), location=location
    )


class TestMeetingSetLocation(unittest.TestCase):
    """Checks that Meeting.set_location validates and stores the location."""

    def setUp(self):
        self.meeting = _meeting("Sprint review", location="Room 1")

    def test_set_location_stores_the_stripped_text(self):
        self.meeting.set_location("  Room 2  ")
        self.assertEqual(self.meeting.location, "Room 2")

    def test_empty_location_clears_it(self):
        self.meeting.set_location("")
        self.assertEqual(self.meeting.location, "")

    def test_non_text_location_raises_invalid_input_error(self):
        with self.assertRaises(InvalidInputError):
            self.meeting.set_location(42)

    def test_non_text_location_leaves_the_old_location(self):
        with self.assertRaises(InvalidInputError):
            self.meeting.set_location(None)
        self.assertEqual(self.meeting.location, "Room 1")


class TestAgendaUpdateMeeting(unittest.TestCase):
    """Checks Agenda.update_meeting applies a rename and location change safely."""

    def setUp(self):
        self.agenda = Agenda()
        self.meeting = self.agenda.schedule(_meeting("Sprint review", location="Room 1"))

    def test_update_meeting_renames_the_meeting(self):
        self.agenda.update_meeting(self.meeting.item_id, title="Sprint demo")
        self.assertEqual(self.meeting.title, "Sprint demo")

    def test_update_meeting_changes_the_location(self):
        self.agenda.update_meeting(self.meeting.item_id, location="Lab 3")
        self.assertEqual(self.meeting.location, "Lab 3")

    def test_update_meeting_returns_the_meeting(self):
        result = self.agenda.update_meeting(self.meeting.item_id, title="Demo")
        self.assertIs(result, self.meeting)

    def test_update_meeting_with_nothing_to_change_raises_invalid_input_error(self):
        with self.assertRaises(InvalidInputError):
            self.agenda.update_meeting(self.meeting.item_id)

    def test_blank_title_is_rejected_and_location_stays_unchanged(self):
        with self.assertRaises(InvalidInputError):
            self.agenda.update_meeting(
                self.meeting.item_id, title="   ", location="Lab 3"
            )
        self.assertEqual(self.meeting.location, "Room 1")

    def test_non_text_location_is_rejected_and_title_stays_unchanged(self):
        with self.assertRaises(InvalidInputError):
            self.agenda.update_meeting(
                self.meeting.item_id, title="Demo", location=5
            )
        self.assertEqual(self.meeting.title, "Sprint review")

    def test_calendar_file_meeting_is_refused_as_read_only(self):
        external = Meeting(
            "Dentist",
            NOW,
            datetime(2026, 11, 26, 10, 0, tzinfo=MANILA),
            datetime(2026, 11, 26, 11, 0, tzinfo=MANILA),
            source=Meeting.SOURCE_CALENDAR_FILE,
        )
        self.agenda.set_external([external])
        with self.assertRaises(ReadOnlySourceError):
            self.agenda.update_meeting(external.item_id, title="Eye doctor")


class TestTaskManagerFindReminder(unittest.TestCase):
    """Checks reminder lookup by ID, exact title, and partial title."""

    def setUp(self):
        self.tm = TaskManager()
        self.water = Reminder("Drink water", NOW, NOW + timedelta(hours=1))
        self.call = Reminder("Call mom", NOW, NOW + timedelta(hours=2))
        self.tm.add_reminder(self.water)
        self.tm.add_reminder(self.call)

    def test_find_reminder_matches_by_exact_id(self):
        self.assertIs(self.tm.find_reminder(self.call.item_id), self.call)

    def test_find_reminder_matches_title_ignoring_case(self):
        self.assertIs(self.tm.find_reminder("CALL MOM"), self.call)

    def test_find_reminder_matches_part_of_a_title(self):
        self.assertIs(self.tm.find_reminder("water"), self.water)

    def test_find_reminder_prefers_exact_title_over_partial_match(self):
        longer = Reminder("Call mom later", NOW, NOW + timedelta(hours=3))
        self.tm.add_reminder(longer)
        self.assertIs(self.tm.find_reminder("call mom"), self.call)

    def test_find_reminder_with_several_partial_matches_raises_ambiguous_item_error(self):
        with self.assertRaises(AmbiguousItemError) as ctx:
            self.tm.find_reminder("a")
        self.assertEqual(len(ctx.exception.matches), 2)

    def test_find_reminder_with_unknown_title_raises_reminder_not_found_error(self):
        with self.assertRaises(ReminderNotFoundError):
            self.tm.find_reminder("dentist")

    def test_find_reminder_with_blank_text_raises_invalid_input_error(self):
        with self.assertRaises(InvalidInputError):
            self.tm.find_reminder("   ")

    def test_remove_reminder_with_unknown_id_raises_reminder_not_found_error(self):
        with self.assertRaises(ReminderNotFoundError):
            self.tm.remove_reminder("rem-missing")


class TestTaskManagerFindDoneTask(unittest.TestCase):
    """Checks that find_task reaches done tasks only when include_done is set."""

    def setUp(self):
        self.tm = TaskManager()
        self.done = Task("Buy milk", NOW)
        self.tm.add_task(self.done, NOW)
        self.tm.complete_task(self.done.item_id)

    def test_done_task_is_not_found_by_title_by_default(self):
        with self.assertRaises(TaskNotFoundError):
            self.tm.find_task("Buy milk")

    def test_done_task_is_found_by_title_with_include_done(self):
        self.assertIs(self.tm.find_task("Buy milk", include_done=True), self.done)

    def test_done_task_is_found_by_part_of_its_title_with_include_done(self):
        self.assertIs(self.tm.find_task("milk", include_done=True), self.done)

    def test_active_task_wins_over_a_done_task_with_the_same_title(self):
        active = Task("Buy milk", NOW)
        self.tm.add_task(active, NOW)
        self.assertIs(self.tm.find_task("Buy milk", include_done=True), active)

    def test_two_done_tasks_with_the_same_title_raise_ambiguous_item_error(self):
        second = Task("Buy milk", NOW)
        self.tm.add_task(second, NOW)
        self.tm.complete_task(second.item_id)
        with self.assertRaises(AmbiguousItemError):
            self.tm.find_task("Buy milk", include_done=True)

    def test_unknown_title_still_raises_task_not_found_with_include_done(self):
        with self.assertRaises(TaskNotFoundError):
            self.tm.find_task("Walk dog", include_done=True)

    def test_an_exact_done_title_wins_over_part_of_an_active_title(self):
        self.tm.add_task(Task("Buy milk and eggs", NOW), NOW)
        self.assertIs(self.tm.find_task("Buy milk", include_done=True), self.done)

    def test_part_of_an_active_title_still_wins_without_include_done(self):
        longer = Task("Buy milk and eggs", NOW)
        self.tm.add_task(longer, NOW)
        self.assertIs(self.tm.find_task("Buy milk"), longer)


class TestNotebookFindNote(unittest.TestCase):
    """Checks note lookup by ID and title, and the not-found error type."""

    def setUp(self):
        self.nb = Notebook()
        self.lecture = Note("Lecture notes", NOW, body="OOP")
        self.recipe = Note("Pancake recipe", NOW + timedelta(minutes=1), body="Flour")
        self.nb.add_note(self.lecture)
        self.nb.add_note(self.recipe)

    def test_find_note_matches_by_exact_id(self):
        self.assertIs(self.nb.find_note(self.recipe.item_id), self.recipe)

    def test_find_note_matches_title_ignoring_case(self):
        self.assertIs(self.nb.find_note("LECTURE NOTES"), self.lecture)

    def test_find_note_matches_part_of_a_title(self):
        self.assertIs(self.nb.find_note("pancake"), self.recipe)

    def test_find_note_with_several_partial_matches_raises_ambiguous_item_error(self):
        with self.assertRaises(AmbiguousItemError) as ctx:
            self.nb.find_note("e")
        self.assertEqual(len(ctx.exception.matches), 2)

    def test_find_note_with_unknown_title_raises_note_not_found_error(self):
        with self.assertRaises(NoteNotFoundError):
            self.nb.find_note("budget")

    def test_find_note_with_blank_text_raises_invalid_input_error(self):
        with self.assertRaises(InvalidInputError):
            self.nb.find_note("")

    def test_get_note_with_unknown_id_raises_note_not_found_error(self):
        with self.assertRaises(NoteNotFoundError):
            self.nb.get_note("note-missing")


class _ToolkitTestCase(unittest.TestCase):
    """Builds a BuddyToolkit over a temporary JsonStore with a fixed clock."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(sources=[JsonStore(self._tmp.name)])
        self.ws.load()
        self.tk = BuddyToolkit(
            self.ws,
            BriefingService(self.ws),
            DocumentReader(model="gemini-4-hydrogen", clock=lambda: NOW),
            clock=lambda: NOW,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _reload(self):
        reloaded = Workspace(sources=[JsonStore(self._tmp.name)])
        reloaded.load()
        return reloaded


class TestToolkitUpdateMeeting(_ToolkitTestCase):
    """Checks the update_meeting tool for success, errors, and saved changes."""

    def setUp(self):
        super().setUp()
        self.tk.schedule_meeting(
            "Sprint review",
            "2026-11-25T14:00",
            "2026-11-25T15:00",
            location="Room 1",
        )

    def test_update_meeting_renames_and_sets_location(self):
        res = self.tk.update_meeting(
            "Sprint review", title="Sprint demo", location="Lab 3"
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["meeting"]["title"], "Sprint demo")
        self.assertEqual(res["meeting"]["location"], "Lab 3")

    def test_update_meeting_summary_describes_the_updated_meeting(self):
        res = self.tk.update_meeting("Sprint review", title="Sprint demo")
        self.assertTrue(res["summary"].startswith("Updated meeting: Meeting: Sprint demo"))

    def test_empty_location_leaves_the_location_unchanged(self):
        res = self.tk.update_meeting("Sprint review", title="Sprint demo")
        self.assertEqual(res["meeting"]["location"], "Room 1")

    def test_empty_title_leaves_the_title_unchanged(self):
        res = self.tk.update_meeting("Sprint review", location="Lab 3")
        self.assertEqual(res["meeting"]["title"], "Sprint review")

    def test_update_meeting_finds_the_meeting_by_id(self):
        meeting_id = self.ws.agenda.list_meetings()[0].item_id
        res = self.tk.update_meeting(meeting_id, location="Lab 3")
        self.assertEqual(res["status"], "success")

    def test_update_meeting_without_title_or_location_returns_invalid_input_error(self):
        res = self.tk.update_meeting("Sprint review")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_type"], "InvalidInputError")
        self.assertEqual(res["message"], "Provide a new title or location.")

    def test_update_meeting_with_unknown_meeting_returns_not_found_error(self):
        res = self.tk.update_meeting("Dentist", title="Eye doctor")
        self.assertEqual(res["error_type"], "MeetingNotFoundError")

    def test_update_meeting_with_ambiguous_title_returns_ambiguous_error(self):
        self.tk.schedule_meeting(
            "Sprint planning", "2026-11-26T09:00", "2026-11-26T10:00"
        )
        res = self.tk.update_meeting("sprint", title="Demo")
        self.assertEqual(res["error_type"], "AmbiguousItemError")

    def test_calendar_file_meeting_is_refused_as_read_only(self):
        self.ws.agenda.set_external(
            [
                Meeting(
                    "Dentist",
                    NOW,
                    datetime(2026, 11, 26, 10, 0, tzinfo=MANILA),
                    datetime(2026, 11, 26, 11, 0, tzinfo=MANILA),
                    source=Meeting.SOURCE_CALENDAR_FILE,
                )
            ]
        )
        res = self.tk.update_meeting("Dentist", title="Eye doctor")
        self.assertEqual(res["error_type"], "ReadOnlySourceError")

    def test_update_meeting_changes_are_on_disk_after_reload(self):
        self.tk.update_meeting("Sprint review", title="Sprint demo", location="Lab 3")
        saved = self._reload().agenda.list_meetings()[0]
        self.assertEqual((saved.title, saved.location), ("Sprint demo", "Lab 3"))


class TestToolkitReminders(_ToolkitTestCase):
    """Checks the list_reminders and delete_reminder tools."""

    def setUp(self):
        super().setUp()
        self.tk.add_reminder("Drink water", "2026-11-24T12:00")
        self.tk.add_reminder("Call mom", "2026-11-24T10:00")

    def test_list_reminders_returns_them_earliest_first(self):
        res = self.tk.list_reminders()
        self.assertEqual(res["status"], "success")
        self.assertEqual(
            [item["title"] for item in res["reminders"]],
            ["Call mom", "Drink water"],
        )

    def test_list_reminders_summary_counts_them(self):
        self.assertEqual(self.tk.list_reminders()["summary"], "Found 2 reminder(s).")

    def test_list_reminders_with_none_saved_returns_an_empty_list(self):
        self.tk.delete_reminder("Call mom")
        self.tk.delete_reminder("Drink water")
        res = self.tk.list_reminders()
        self.assertEqual(res["reminders"], [])

    def test_delete_reminder_by_title_removes_it(self):
        res = self.tk.delete_reminder("call mom")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["reminder"]["title"], "Call mom")
        self.assertEqual(len(self.ws.tasks.list_reminders()), 1)

    def test_delete_reminder_by_id_removes_it(self):
        reminder_id = self.ws.tasks.find_reminder("Drink water").item_id
        res = self.tk.delete_reminder(reminder_id)
        self.assertEqual(res["reminder"]["item_id"], reminder_id)

    def test_delete_reminder_with_unknown_title_returns_not_found_error(self):
        res = self.tk.delete_reminder("Dentist")
        self.assertEqual(res["error_type"], "ReminderNotFoundError")

    def test_delete_reminder_with_ambiguous_title_returns_ambiguous_error(self):
        res = self.tk.delete_reminder("a")
        self.assertEqual(res["error_type"], "AmbiguousItemError")

    def test_delete_reminder_leaves_tasks_alone(self):
        self.tk.add_task("Call mom")
        self.tk.delete_reminder("Call mom")
        self.assertEqual(len(self.ws.tasks.list_all_tasks()), 1)

    def test_deleted_reminder_is_gone_after_reload(self):
        self.tk.delete_reminder("Call mom")
        titles = [item.title for item in self._reload().tasks.list_reminders()]
        self.assertEqual(titles, ["Drink water"])


class TestToolkitDeleteNote(_ToolkitTestCase):
    """Checks the delete_note tool."""

    def setUp(self):
        super().setUp()
        self.tk.add_note("Lecture notes", "OOP basics")
        self.tk.add_note("Pancake recipe", "Flour and eggs")

    def test_delete_note_by_title_removes_it(self):
        res = self.tk.delete_note("pancake")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["note"]["title"], "Pancake recipe")
        self.assertEqual(len(self.ws.notebook.list_notes()), 1)

    def test_delete_note_by_id_removes_it(self):
        note_id = self.ws.notebook.find_note("Lecture notes").item_id
        res = self.tk.delete_note(note_id)
        self.assertEqual(res["note"]["item_id"], note_id)

    def test_delete_note_with_unknown_title_returns_not_found_error(self):
        res = self.tk.delete_note("budget")
        self.assertEqual(res["error_type"], "NoteNotFoundError")

    def test_delete_note_with_ambiguous_title_returns_ambiguous_error(self):
        res = self.tk.delete_note("e")
        self.assertEqual(res["error_type"], "AmbiguousItemError")

    def test_delete_note_keeps_tasks_that_came_from_it(self):
        task = Task("Approve budget", NOW, status="proposed", source="upload")
        self.ws.tasks.propose(task)
        self.ws.notebook.add_note(
            Note("Budget memo", NOW, body="Numbers", action_items=[task])
        )
        self.tk.delete_note("Budget memo")
        self.assertIs(self.ws.tasks.get_task(task.item_id), task)

    def test_deleted_note_is_gone_after_reload(self):
        self.tk.delete_note("Pancake recipe")
        titles = [note.title for note in self._reload().notebook.list_notes()]
        self.assertEqual(titles, ["Lecture notes"])


class TestToolkitDoneTasks(_ToolkitTestCase):
    """Checks that done tasks can be deleted and edited by title."""

    def setUp(self):
        super().setUp()
        self.tk.add_task("Buy milk")
        self.tk.complete_task("Buy milk")

    def test_delete_task_by_title_removes_a_done_task(self):
        res = self.tk.delete_task("Buy milk")
        self.assertEqual(res["status"], "success")
        self.assertEqual(self.ws.tasks.list_all_tasks(), [])

    def test_update_task_by_title_renames_a_done_task(self):
        res = self.tk.update_task("Buy milk", title="Buy oat milk")
        self.assertEqual(res["task"]["title"], "Buy oat milk")
        self.assertEqual(res["task"]["status"], "done")

    def test_complete_task_by_title_still_ignores_done_tasks(self):
        res = self.tk.complete_task("Buy milk")
        self.assertEqual(res["error_type"], "TaskNotFoundError")

    def test_deleted_done_task_is_gone_after_reload(self):
        self.tk.delete_task("Buy milk")
        self.assertEqual(self._reload().tasks.list_all_tasks(), [])

    def test_delete_by_exact_title_keeps_the_longer_open_task(self):
        self.tk.add_task("Buy milk and eggs")
        res = self.tk.delete_task("Buy milk")
        self.assertEqual(res["task"]["title"], "Buy milk")
        self.assertEqual(
            [task.title for task in self.ws.tasks.list_all_tasks()], ["Buy milk and eggs"]
        )


class TestToolkitDeleteLinkedTask(_ToolkitTestCase):
    """Checks that deleting a task also removes it from the note it came from."""

    def setUp(self):
        super().setUp()
        self.tk.add_task("Send slides")
        self.task = self.ws.tasks.find_task("Send slides")
        self.note = Note("Kickoff summary", NOW, action_items=[self.task])
        self.ws.notebook.add_note(self.note)
        self.ws.save()

    def test_deleting_a_task_unlinks_it_from_its_note(self):
        self.tk.delete_task(self.task.item_id)
        self.assertEqual(self.note.action_items, [])

    def test_the_saved_note_no_longer_lists_the_deleted_task(self):
        self.tk.delete_task(self.task.item_id)
        # Read the file itself: a reload would quietly drop an unknown ID.
        notes_path = os.path.join(self._tmp.name, JsonStore.NOTES_FILE)
        with open(notes_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(saved[0]["action_item_ids"], [])


class TestHonestyRuleInProfiles(unittest.TestCase):
    """Checks every agent profile carries the rule against false 'done' claims."""

    RULE = "only when a tool returned status 'success' for that exact change"

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        ws = Workspace(sources=[JsonStore(self._tmp.name)])
        self.tk = BuddyToolkit(
            ws,
            BriefingService(ws),
            DocumentReader(model="gemini-4-hydrogen", clock=lambda: NOW),
            clock=lambda: NOW,
        )

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def _profiles(self):
        specialists = [
            TaskAgentProfile("gemini-4-hydrogen", self.tk),
            ScheduleAgentProfile("gemini-4-hydrogen", self.tk),
            NotesAgentProfile("gemini-4-hydrogen", self.tk),
            BriefingAgentProfile("gemini-4-hydrogen", self.tk),
        ]
        coordinator = CoordinatorProfile("gemini-4-hydrogen", self.tk, specialists)
        voice = VoiceCoordinatorProfile("gemini-4-hydrogen", self.tk, specialists)
        return specialists + [coordinator, voice]

    def test_every_profile_instruction_contains_the_honesty_rule(self):
        for profile in self._profiles():
            with self.subTest(profile=profile.name):
                instr = profile.instruction()
                self.assertIn(self.RULE, instr)
                self.assertIn("BuddyAI cannot do that yet", instr)

    def test_task_instruction_sends_reminders_to_the_reminder_tools(self):
        instr = TaskAgentProfile("gemini-4-hydrogen", self.tk).instruction()
        self.assertIn("delete_reminder", instr)
        self.assertIn("never with the task tools", instr)


if __name__ == "__main__":
    unittest.main()
