"""Unit tests for CommandRouter: command routing and the direct commands.

The router is tested with a stand-in app that only has a toolkit and an
`ask` method that records its calls, so no test can reach the real model.
Each test covers one behaviour.
"""

from datetime import datetime
from io import StringIO
import logging
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from rich.console import Console

from buddyai.briefing import BriefingService
from buddyai.cli import CommandRouter, RICH_THEME, TerminalUI
from buddyai.document_reader import DocumentReader
from buddyai.sources import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.web_lookup import WebLookup
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=MANILA)


class _FakeApp:
    """Offers only what CommandRouter needs and records every model request."""

    def __init__(self, toolkit, workspace, briefing_service):
        self.toolkit = toolkit
        self.workspace = workspace
        self.briefing_service = briefing_service
        self.asked = []

    def ask(self, message, files=None, on_status=None):
        self.asked.append((message, files))
        return "model reply"

    def check_file(self, path):
        return DocumentReader(model="gemini-4-hydrogen").validate_file(path)[0]


class _RouterTestCase(unittest.TestCase):
    """Builds a router on a temporary data folder with a fixed clock."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.store = JsonStore(self._tmp.name)
        self.workspace = Workspace(sources=[self.store])
        self.workspace.load()
        reader = DocumentReader(model="gemini-4-hydrogen", clock=lambda: NOW)
        self.briefing_service = BriefingService(self.workspace)
        toolkit = BuddyToolkit(
            self.workspace, self.briefing_service, reader, clock=lambda: NOW
        )
        self.app = _FakeApp(toolkit, self.workspace, self.briefing_service)

        self.buffer = StringIO()
        console = Console(
            file=self.buffer,
            theme=RICH_THEME,
            highlight=False,
            no_color=True,
            width=200,
        )
        self.ui = TerminalUI(console=console, interactive=False)
        self.router = CommandRouter(self.app, self.ui)

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def output(self):
        return self.buffer.getvalue()

    def titles(self, items):
        return [item.title for item in items]

    def saved_workspace(self):
        """Load the data folder again, as a restart of BuddyAI would."""
        reloaded = Workspace(sources=[JsonStore(self._tmp.name)])
        reloaded.load()
        return reloaded


class TestRouting(_RouterTestCase):
    def test_quit_asks_to_exit(self):
        self.assertEqual(self.router.handle("/quit"), CommandRouter.EXIT)

    def test_exit_is_another_word_for_quit(self):
        self.assertEqual(self.router.handle("/exit"), CommandRouter.EXIT)

    def test_a_known_command_is_handled(self):
        self.assertEqual(self.router.handle("/help"), CommandRouter.HANDLED)
        self.assertIn("add | edit | delete | done a task", self.output())

    def test_command_words_ignore_capital_letters(self):
        self.assertEqual(self.router.handle("/HELP"), CommandRouter.HANDLED)

    def test_an_ordinary_message_is_not_a_command(self):
        self.assertEqual(self.router.handle("add a task to buy milk"), CommandRouter.NOT_A_COMMAND)

    def test_an_empty_line_is_not_a_command(self):
        self.assertEqual(self.router.handle("   "), CommandRouter.NOT_A_COMMAND)

    def test_a_message_starting_with_a_path_is_not_a_command(self):
        outcome = self.router.handle("/home/me/file.pdf summarize")
        self.assertEqual(outcome, CommandRouter.NOT_A_COMMAND)

    def test_an_unknown_command_is_handled_with_a_warning(self):
        self.assertEqual(self.router.handle("/foo"), CommandRouter.HANDLED)
        self.assertIn("Unknown command /foo. Type /help to see the commands.", self.output())

    def test_an_unknown_command_is_not_sent_to_the_model(self):
        self.router.handle("/foo bar")
        self.assertEqual(self.app.asked, [])

    def test_direct_commands_make_no_model_request(self):
        self.router.handle("/task add Write report | 2026-12-01 | high")
        self.router.handle("/meet add Review | 2026-11-30 14:00 | 2026-11-30 15:00")
        self.router.handle("/done Write report")
        self.router.handle("/tasks")
        self.assertEqual(self.app.asked, [])


class TestSend(_RouterTestCase):
    def test_send_asks_the_model_once_and_shows_the_reply(self):
        self.router.send("hello")
        self.assertEqual(self.app.asked, [("hello", None)])
        self.assertIn("model reply", self.output())


class TestTaskAdd(_RouterTestCase):
    def test_adds_a_task_with_due_date_and_priority(self):
        self.router.handle("/task add Write report | 2026-12-01 | high")
        task = self.workspace.tasks.find_task("Write report")
        self.assertEqual(task.priority, 3)
        self.assertEqual(task.due_date.strftime("%Y-%m-%d"), "2026-12-01")

    def test_success_line_names_the_task_and_its_id(self):
        self.router.handle("/task add Write report | 2026-12-01 | high")
        task = self.workspace.tasks.find_task("Write report")
        self.assertIn(f"Added task: Write report (id: {task.item_id})", self.output())

    def test_the_new_task_is_saved_to_disk(self):
        self.router.handle("/task add Write report | 2026-12-01 | high")
        saved = self.saved_workspace()
        self.assertEqual(self.titles(saved.tasks.list_all_tasks()), ["Write report"])

    def test_due_date_and_priority_are_optional(self):
        self.router.handle("/task add Buy milk")
        task = self.workspace.tasks.find_task("Buy milk")
        self.assertIsNone(task.due_date)
        self.assertEqual(task.priority, 2)

    def test_a_date_and_time_can_be_typed_with_a_space(self):
        self.router.handle("/task add Call Ana | 2026-12-01 14:30 | low")
        task = self.workspace.tasks.find_task("Call Ana")
        self.assertEqual(task.due_date.strftime("%Y-%m-%d %H:%M"), "2026-12-01 14:30")

    def test_a_past_due_date_shows_the_exception_name(self):
        self.router.handle("/task add Old news | 2020-01-01 | high")
        self.assertIn("InvalidDueDateError: Due date 2020-01-01 23:59 is in the past.", self.output())

    def test_a_past_due_date_saves_nothing(self):
        self.router.handle("/task add Old news | 2020-01-01 | high")
        self.assertEqual(self.workspace.tasks.list_all_tasks(), [])
        self.assertEqual(self.saved_workspace().tasks.list_all_tasks(), [])

    def test_a_date_in_words_shows_the_exception_name(self):
        self.router.handle("/task add Call Ana | tomorrow")
        self.assertIn("InvalidDueDateError", self.output())

    def test_an_invalid_priority_shows_the_exception_name(self):
        self.router.handle("/task add Write report | 2026-12-01 | urgent")
        self.assertIn("InvalidInputError: Invalid priority 'urgent'", self.output())

    def test_an_invalid_priority_saves_nothing(self):
        self.router.handle("/task add Write report | 2026-12-01 | urgent")
        self.assertEqual(self.workspace.tasks.list_all_tasks(), [])

    def test_task_without_add_shows_usage(self):
        self.assertEqual(self.router.handle("/task"), CommandRouter.HANDLED)
        self.assertIn("/task add <title>", self.output())

    def test_task_add_without_a_title_shows_usage(self):
        self.router.handle("/task add")
        self.assertIn("/task add <title>", self.output())

    def test_task_add_with_an_empty_title_shows_usage(self):
        self.router.handle("/task add | 2026-12-01 | high")
        self.assertIn("/task add <title>", self.output())

    def test_task_add_with_too_many_fields_shows_usage(self):
        self.router.handle("/task add Report | 2026-12-01 | high | extra")
        self.assertIn("/task add <title>", self.output())

    def test_an_unknown_task_subcommand_shows_usage(self):
        self.router.handle("/task remove Report")
        self.assertIn("/task add <title>", self.output())

    def test_usage_message_saves_nothing(self):
        self.router.handle("/task add")
        self.assertEqual(self.workspace.tasks.list_all_tasks(), [])


class TestMeetAdd(_RouterTestCase):
    def test_schedules_a_meeting(self):
        self.router.handle("/meet add Standup | 2026-11-30 14:00 | 2026-11-30 15:00")
        meeting = self.workspace.agenda.find_meeting("Standup")
        self.assertEqual(meeting.start.strftime("%Y-%m-%d %H:%M"), "2026-11-30 14:00")
        self.assertEqual(meeting.end.strftime("%H:%M"), "15:00")

    def test_success_line_names_the_meeting_and_its_id(self):
        self.router.handle("/meet add Standup | 2026-11-30T14:00 | 2026-11-30T15:00")
        meeting = self.workspace.agenda.find_meeting("Standup")
        self.assertIn(f"Scheduled meeting: Standup (id: {meeting.item_id})", self.output())

    def test_the_new_meeting_is_saved_to_disk(self):
        self.router.handle("/meet add Standup | 2026-11-30 14:00 | 2026-11-30 15:00")
        saved = self.saved_workspace()
        self.assertEqual(self.titles(saved.agenda.list_meetings()), ["Standup"])

    def test_an_overlapping_meeting_shows_the_exception_name(self):
        self.router.handle("/meet add Standup | 2026-11-30 14:00 | 2026-11-30 15:00")
        self.router.handle("/meet add Clash | 2026-11-30 14:30 | 2026-11-30 15:30")
        self.assertIn("SchedulingConflictError: Meeting 'Clash' conflicts with 'Standup'", self.output())

    def test_an_overlapping_meeting_shows_the_suggested_free_start(self):
        self.router.handle("/meet add Standup | 2026-11-30 14:00 | 2026-11-30 15:00")
        self.router.handle("/meet add Clash | 2026-11-30 14:30 | 2026-11-30 15:30")
        self.assertIn("Suggested free start: 2026-11-30 15:00", self.output())

    def test_an_overlapping_meeting_is_not_saved(self):
        self.router.handle("/meet add Standup | 2026-11-30 14:00 | 2026-11-30 15:00")
        self.router.handle("/meet add Clash | 2026-11-30 14:30 | 2026-11-30 15:30")
        self.assertEqual(self.titles(self.workspace.agenda.list_meetings()), ["Standup"])

    def test_an_end_before_the_start_is_refused(self):
        self.router.handle("/meet add Backwards | 2026-11-30 16:00 | 2026-11-30 15:00")
        self.assertIn("InvalidInputError: Meeting end time must be after start time.", self.output())
        self.assertEqual(self.workspace.agenda.list_meetings(), [])

    def test_a_meeting_in_the_past_is_refused(self):
        self.router.handle("/meet add Old | 2020-01-01 09:00 | 2020-01-01 10:00")
        self.assertIn("InvalidInputError", self.output())
        self.assertEqual(self.workspace.agenda.list_meetings(), [])

    def test_meet_without_add_shows_usage(self):
        self.assertEqual(self.router.handle("/meet"), CommandRouter.HANDLED)
        self.assertIn("/meet add <title>", self.output())

    def test_a_missing_end_time_shows_usage(self):
        self.router.handle("/meet add Title | 2026-11-30T14:00")
        self.assertIn("/meet add <title>", self.output())

    def test_a_missing_title_shows_usage(self):
        self.router.handle("/meet add | 2026-11-30 14:00 | 2026-11-30 15:00")
        self.assertIn("/meet add <title>", self.output())

    def test_usage_message_saves_nothing(self):
        self.router.handle("/meet add Title | 2026-11-30T14:00")
        self.assertEqual(self.workspace.agenda.list_meetings(), [])


class TestTaskEdit(_RouterTestCase):
    def setUp(self):
        super().setUp()
        self.app.toolkit.add_task("Write report", due="2026-12-01", priority="high")
        self.task = self.workspace.tasks.find_task("Write report")

    def test_edit_changes_the_title_due_date_and_priority(self):
        self.router.handle("/task edit Write report | Final report | 2026-12-05 | low")
        self.assertEqual(self.task.title, "Final report")
        self.assertEqual(self.task.due_date.strftime("%Y-%m-%d"), "2026-12-05")
        self.assertEqual(self.task.priority, 1)

    def test_edit_finds_the_task_by_id(self):
        self.router.handle(f"/task edit {self.task.item_id} | Final report")
        self.assertEqual(self.task.title, "Final report")

    def test_edit_success_line_names_the_task_and_its_id(self):
        self.router.handle("/task edit Write report | Final report")
        self.assertIn(f"Updated task: Final report (id: {self.task.item_id})", self.output())

    def test_edit_with_only_a_due_date_keeps_the_title_and_priority(self):
        self.router.handle("/task edit Write report | | 2026-12-10")
        self.assertEqual(self.task.title, "Write report")
        self.assertEqual(self.task.priority, 3)
        self.assertEqual(self.task.due_date.strftime("%Y-%m-%d"), "2026-12-10")

    def test_the_edit_is_saved_to_disk(self):
        self.router.handle("/task edit Write report | Final report")
        saved = self.saved_workspace().tasks.get_task(self.task.item_id)
        self.assertEqual(saved.title, "Final report")

    def test_edit_with_nothing_to_change_shows_usage(self):
        self.router.handle("/task edit Write report | | |")
        self.assertIn("/task edit <task>", self.output())

    def test_edit_with_only_a_task_shows_usage_and_changes_nothing(self):
        self.router.handle("/task edit Write report")
        self.assertIn("/task edit <task>", self.output())
        self.assertEqual(self.task.title, "Write report")
        self.assertEqual(self.task.priority, 3)

    def test_edit_without_a_task_shows_usage(self):
        self.router.handle("/task edit | Final report")
        self.assertIn("/task edit <task>", self.output())
        self.assertEqual(self.task.title, "Write report")

    def test_edit_with_too_many_fields_shows_usage_and_changes_nothing(self):
        self.router.handle("/task edit Write report | Final | 2026-12-05 | low | extra")
        self.assertIn("/task edit <task>", self.output())
        self.assertEqual(self.task.title, "Write report")

    def test_edit_of_an_unknown_task_shows_the_exception_name(self):
        self.router.handle("/task edit Nothing like this | New title")
        self.assertIn("TaskNotFoundError", self.output())

    def test_edit_with_an_invalid_priority_changes_nothing(self):
        self.router.handle("/task edit Write report | Final report | | urgent")
        self.assertIn("InvalidInputError", self.output())
        self.assertEqual(self.task.title, "Write report")

    def test_edit_makes_no_model_request(self):
        self.router.handle("/task edit Write report | Final report")
        self.assertEqual(self.app.asked, [])


class TestTaskDelete(_RouterTestCase):
    def setUp(self):
        super().setUp()
        self.app.toolkit.add_task("Write report", due="2026-12-01", priority="high")
        self.task = self.workspace.tasks.find_task("Write report")

    def test_delete_removes_the_task_by_title(self):
        self.router.handle("/task delete Write report")
        self.assertEqual(self.workspace.tasks.list_all_tasks(), [])

    def test_delete_removes_the_task_by_id(self):
        self.router.handle(f"/task delete {self.task.item_id}")
        self.assertEqual(self.workspace.tasks.list_all_tasks(), [])

    def test_delete_success_line_names_the_task_and_its_id(self):
        self.router.handle("/task delete Write report")
        self.assertIn(f"Deleted task: Write report (id: {self.task.item_id})", self.output())

    def test_the_deletion_is_saved_to_disk(self):
        self.router.handle("/task delete Write report")
        self.assertEqual(self.saved_workspace().tasks.list_all_tasks(), [])

    def test_delete_of_an_unknown_task_shows_the_exception_name(self):
        self.router.handle("/task delete Nothing like this")
        self.assertIn("TaskNotFoundError", self.output())

    def test_delete_of_an_unknown_task_keeps_the_existing_task(self):
        self.router.handle("/task delete Nothing like this")
        self.assertEqual(self.titles(self.workspace.tasks.list_all_tasks()), ["Write report"])

    def test_delete_without_a_task_shows_usage(self):
        self.router.handle("/task delete")
        self.assertIn("/task delete <task>", self.output())
        self.assertEqual(self.titles(self.workspace.tasks.list_all_tasks()), ["Write report"])

    def test_delete_with_extra_fields_shows_usage_and_keeps_the_task(self):
        self.router.handle("/task delete Write report | extra")
        self.assertIn("/task delete <task>", self.output())
        self.assertEqual(self.titles(self.workspace.tasks.list_all_tasks()), ["Write report"])

    def test_a_typed_delete_works_after_a_chat_request_read_untrusted_text(self):
        # Stands in for an earlier chat message that searched the web or read a file.
        self.app.toolkit._mark_untrusted_read()
        self.router.handle("/task delete Write report")
        self.assertEqual(self.workspace.tasks.list_all_tasks(), [])


class TestMeetChanges(_RouterTestCase):
    """Covers /meet move, /meet edit and /meet cancel on two existing meetings."""

    def setUp(self):
        super().setUp()
        self.app.toolkit.schedule_meeting(
            "Standup", "2026-11-30 14:00", "2026-11-30 15:00"
        )
        self.app.toolkit.schedule_meeting(
            "Review", "2026-11-30 16:00", "2026-11-30 17:00"
        )
        self.standup = self.workspace.agenda.find_meeting("Standup")
        self.review = self.workspace.agenda.find_meeting("Review")

    def test_move_changes_the_start_and_end(self):
        self.router.handle("/meet move Review | 2026-12-01 09:00 | 2026-12-01 10:00")
        self.assertEqual(self.review.start.strftime("%Y-%m-%d %H:%M"), "2026-12-01 09:00")
        self.assertEqual(self.review.end.strftime("%Y-%m-%d %H:%M"), "2026-12-01 10:00")

    def test_move_success_line_names_the_meeting_and_its_id(self):
        self.router.handle("/meet move Review | 2026-12-01 09:00 | 2026-12-01 10:00")
        self.assertIn(f"Moved meeting: Review (id: {self.review.item_id})", self.output())

    def test_the_move_is_saved_to_disk(self):
        self.router.handle("/meet move Review | 2026-12-01 09:00 | 2026-12-01 10:00")
        saved = self.saved_workspace().agenda.get_meeting(self.review.item_id)
        self.assertEqual(saved.start.strftime("%Y-%m-%d %H:%M"), "2026-12-01 09:00")

    def test_move_into_a_conflict_shows_the_exception_name(self):
        self.router.handle("/meet move Review | 2026-11-30 14:30 | 2026-11-30 15:30")
        self.assertIn("SchedulingConflictError", self.output())

    def test_move_into_a_conflict_shows_the_suggested_free_start(self):
        self.router.handle("/meet move Review | 2026-11-30 14:30 | 2026-11-30 15:30")
        self.assertIn("Suggested free start: 2026-11-30 15:00", self.output())

    def test_move_into_a_conflict_leaves_the_meeting_where_it_was(self):
        self.router.handle("/meet move Review | 2026-11-30 14:30 | 2026-11-30 15:30")
        self.assertEqual(self.review.start.strftime("%H:%M"), "16:00")
        self.assertEqual(self.review.end.strftime("%H:%M"), "17:00")

    def test_move_without_an_end_time_shows_usage_and_moves_nothing(self):
        self.router.handle("/meet move Review | 2026-12-01 09:00")
        self.assertIn("/meet move <meeting>", self.output())
        self.assertEqual(self.review.start.strftime("%Y-%m-%d %H:%M"), "2026-11-30 16:00")

    def test_edit_renames_the_meeting_and_sets_the_location(self):
        self.router.handle("/meet edit Review | Sprint review | Room 2")
        self.assertEqual(self.review.title, "Sprint review")
        self.assertEqual(self.review.location, "Room 2")

    def test_edit_success_line_names_the_meeting_and_its_id(self):
        self.router.handle("/meet edit Review | Sprint review | Room 2")
        self.assertIn(f"Updated meeting: Sprint review (id: {self.review.item_id})", self.output())

    def test_edit_with_only_a_location_keeps_the_title(self):
        self.router.handle("/meet edit Review | | Room 2")
        self.assertEqual(self.review.title, "Review")
        self.assertEqual(self.review.location, "Room 2")

    def test_the_edit_is_saved_to_disk(self):
        self.router.handle("/meet edit Review | Sprint review | Room 2")
        saved = self.saved_workspace().agenda.get_meeting(self.review.item_id)
        self.assertEqual(saved.title, "Sprint review")
        self.assertEqual(saved.location, "Room 2")

    def test_edit_with_nothing_to_change_shows_usage(self):
        self.router.handle("/meet edit Review | |")
        self.assertIn("/meet edit <meeting>", self.output())
        self.assertEqual(self.review.title, "Review")

    def test_edit_with_too_many_fields_shows_usage_and_changes_nothing(self):
        self.router.handle("/meet edit Review | Sprint review | Room 2 | extra")
        self.assertIn("/meet edit <meeting>", self.output())
        self.assertEqual(self.review.title, "Review")

    def test_cancel_removes_the_meeting(self):
        self.router.handle("/meet cancel Review")
        self.assertEqual(self.titles(self.workspace.agenda.list_meetings()), ["Standup"])

    def test_cancel_success_line_names_the_meeting_and_its_id(self):
        self.router.handle("/meet cancel Review")
        self.assertIn(f"Cancelled meeting: Review (id: {self.review.item_id})", self.output())

    def test_the_cancellation_is_saved_to_disk(self):
        self.router.handle("/meet cancel Review")
        saved = self.saved_workspace()
        self.assertEqual(self.titles(saved.agenda.list_meetings()), ["Standup"])

    def test_cancel_of_an_unknown_meeting_shows_the_exception_name(self):
        self.router.handle("/meet cancel Nothing like this")
        self.assertIn("MeetingNotFoundError", self.output())

    def test_cancel_without_a_meeting_shows_usage_and_keeps_both_meetings(self):
        self.router.handle("/meet cancel")
        self.assertIn("/meet cancel <meeting>", self.output())
        self.assertEqual(len(self.workspace.agenda.list_meetings()), 2)


class TestUsageText(_RouterTestCase):
    def test_bare_task_lists_every_task_subcommand(self):
        self.router.handle("/task")
        for line in ("/task add <title>", "/task edit <task>", "/task delete <task>"):
            self.assertIn(line, self.output())

    def test_bare_meet_lists_every_meet_subcommand(self):
        self.router.handle("/meet")
        for line in (
            "/meet add <title>",
            "/meet move <meeting>",
            "/meet edit <meeting>",
            "/meet cancel <meeting>",
        ):
            self.assertIn(line, self.output())

    def test_an_unknown_task_subcommand_shows_the_usage_lines(self):
        self.router.handle("/task rename Report")
        self.assertIn("/task delete <task>", self.output())

    def test_an_unknown_meet_subcommand_shows_the_usage_lines(self):
        self.router.handle("/meet postpone Review")
        self.assertIn("/meet cancel <meeting>", self.output())

    def test_subcommands_ignore_capital_letters(self):
        self.app.toolkit.add_task("Write report")
        self.router.handle("/task DELETE Write report")
        self.assertEqual(self.workspace.tasks.list_all_tasks(), [])


class TestTaskDone(_RouterTestCase):
    def setUp(self):
        super().setUp()
        self.app.toolkit.add_task("Write report", due="2026-12-01", priority="high")
        self.task = self.workspace.tasks.find_task("Write report")

    def test_task_done_marks_the_task_done_by_title(self):
        self.router.handle("/task done Write report")
        self.assertEqual(self.task.status, "done")

    def test_task_done_shows_the_completed_task(self):
        self.router.handle("/task done Write report")
        self.assertIn(f"Completed task: Write report (id: {self.task.item_id})", self.output())

    def test_task_done_without_a_task_shows_usage(self):
        self.router.handle("/task done")
        self.assertIn("/task done <task>", self.output())
        self.assertEqual(self.task.status, "open")

    def test_task_done_twice_by_id_says_it_is_already_done(self):
        self.router.handle(f"/task done {self.task.item_id}")
        self.router.handle(f"/task done {self.task.item_id}")
        output = self.output()
        self.assertEqual(output.count("Completed task"), 1)
        self.assertIn("InvalidInputError: Task 'Write report' is already done.", output)


class TestFileMentions(_RouterTestCase):
    """Checks that @path in a message attaches a file and is checked first."""

    def setUp(self):
        super().setUp()
        folder = os.path.join(self._tmp.name, "Juan Cruz")
        os.makedirs(folder)
        self.path = os.path.join(folder, "meeting notes.txt")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("notes")
        self.short_path = os.path.join(self._tmp.name, "notes.txt")
        with open(self.short_path, "w", encoding="utf-8") as handle:
            handle.write("notes")

    def test_a_mention_is_replaced_by_the_file_name_in_the_message(self):
        message, paths = CommandRouter._take_file_mentions(
            f"Summarize @{self.short_path} please"
        )
        self.assertEqual(message, "Summarize notes.txt please")
        self.assertEqual(paths, [self.short_path])

    def test_a_quoted_mention_may_contain_spaces(self):
        message, paths = CommandRouter._take_file_mentions(f'Read @"{self.path}"')
        self.assertEqual(paths, [self.path])
        self.assertEqual(message, "Read meeting notes.txt")

    def test_punctuation_after_a_mention_is_not_part_of_the_path(self):
        message, paths = CommandRouter._take_file_mentions(
            f"Read @{self.short_path}, then list tasks."
        )
        self.assertEqual(paths, [self.short_path])
        self.assertEqual(message, "Read notes.txt, then list tasks.")

    def test_a_message_that_is_only_a_mention_becomes_empty(self):
        message, paths = CommandRouter._take_file_mentions(f"@{self.short_path}")
        self.assertEqual((message, paths), ("", [self.short_path]))

    def test_an_email_address_is_not_a_file_mention(self):
        text = "Email ana@example.com about the report"
        self.assertEqual(CommandRouter._take_file_mentions(text), (text, []))

    def test_a_name_without_an_extension_is_not_a_file_mention(self):
        text = "Remind @Ana about the meeting"
        self.assertEqual(CommandRouter._take_file_mentions(text), (text, []))

    def test_a_mention_sends_the_absolute_path_to_the_model(self):
        self.router.send(f"Summarize @{self.short_path}")
        self.assertEqual(
            self.app.asked, [("Summarize notes.txt", [os.path.abspath(self.short_path)])]
        )

    def test_a_missing_file_shows_the_error_and_asks_nothing(self):
        self.router.send(f"Summarize @{os.path.join(self._tmp.name, 'gone.pdf')}")
        self.assertIn("InvalidInputError", self.output())
        self.assertEqual(self.app.asked, [])

    def test_an_unsupported_file_shows_the_error_and_asks_nothing(self):
        self.router.send(f"Summarize @{os.path.join(self._tmp.name, 'report.doc')}")
        self.assertIn("UnsupportedFileTypeError", self.output())
        self.assertEqual(self.app.asked, [])

    def test_a_message_without_mentions_is_sent_unchanged(self):
        self.router.send("What is due today?")
        self.assertEqual(self.app.asked, [("What is due today?", None)])

    def test_a_handle_with_a_dot_is_not_a_file_mention(self):
        text = "mail the notes to @ana.cruz please"
        self.assertEqual(CommandRouter._take_file_mentions(text), (text, []))

    def test_a_time_after_an_at_sign_is_not_a_file_mention(self):
        text = "Move the call to @3.30pm"
        self.assertEqual(CommandRouter._take_file_mentions(text), (text, []))

    def test_a_handle_with_a_dot_is_sent_to_the_model_unchanged(self):
        self.router.send("mail the notes to @ana.cruz please")
        self.assertEqual(self.app.asked, [("mail the notes to @ana.cruz please", None)])

    def test_a_path_cut_at_a_space_shows_the_quotes_hint(self):
        self.router.send(f"Summarize @{os.path.join(self._tmp.name, 'Juan')} Cruz\\notes.txt")
        output = self.output()
        self.assertIn("UnsupportedFileTypeError", output)
        self.assertIn("If the file path has spaces, put it in double quotes", output)
        self.assertEqual(self.app.asked, [])


class TestTextIsShownAsTyped(_RouterTestCase):
    """Checks that titles and messages are printed literally, never as Rich markup."""

    def test_adding_a_title_with_a_closing_tag_shows_it_without_a_crash(self):
        self.router.handle("/task add Fix [/] now")
        self.assertIn("Added task: Fix [/] now", self.output())

    def test_tasks_lists_a_title_with_a_closing_tag(self):
        self.app.toolkit.add_task("Fix [/] now")
        self.router.handle("/tasks")
        self.assertIn("Fix [/] now", self.output())

    def test_square_brackets_in_a_title_are_kept(self):
        self.app.toolkit.add_task("Report [draft] v2")
        self.router.handle("/tasks")
        self.assertIn("Report [draft] v2", self.output())

    def test_the_ascii_ok_glyph_is_shown(self):
        # A StringIO console has no UTF-8 encoding, so the ASCII glyphs are used.
        self.router.handle("/task add Write report")
        self.assertIn("[ok] Added task: Write report", self.output())

    def test_brief_shows_emphasis_characters_in_a_title_as_typed(self):
        self.app.toolkit.add_task("Fix *urgent* bug_report", due="2026-11-26")
        self.router.handle("/brief")
        self.assertIn("Fix *urgent* bug_report", self.output())

    def test_a_spoken_reply_with_brackets_is_shown_as_said(self):
        self.router._render_voice_text("BuddyAI", "Say [/] or [bold]hi")
        self.assertIn("BuddyAI: Say [/] or [bold]hi", self.output())


class TestHelpAndTypos(_RouterTestCase):
    def test_help_groups_the_commands(self):
        self.router.handle("/help")
        for group in ("Session", "Your day", "Change data (no AI)", "Input"):
            with self.subTest(group=group):
                self.assertIn(group, self.output())

    def test_help_lists_file_mentions_instead_of_the_file_command(self):
        self.router.handle("/help")
        self.assertIn("@path", self.output())
        self.assertNotIn("/file", self.output())

    def test_help_still_lists_voice(self):
        self.router.handle("/help")
        self.assertIn("/voice", self.output())

    def test_a_mistyped_command_suggests_the_closest_one(self):
        self.router.handle("/tsk add Buy milk")
        self.assertIn("Did you mean /task?", self.output())

    def test_a_mistyped_command_is_not_sent_to_the_model(self):
        self.router.handle("/tsk add Buy milk")
        self.assertEqual(self.app.asked, [])

    def test_a_typo_is_never_corrected_to_an_unlisted_older_name(self):
        self.router.handle("/exti")
        self.assertNotIn("/exit?", self.output())

    def test_an_unknown_word_far_from_any_command_gets_no_suggestion(self):
        self.router.handle("/xyzzy")
        self.assertNotIn("Did you mean", self.output())

    def test_older_command_names_still_work(self):
        self.app.toolkit.add_task("Write report")
        self.router.handle("/done Write report")
        self.assertEqual(self.workspace.tasks.find_task("Write report", include_done=True).status, "done")


class TestDone(_RouterTestCase):
    def setUp(self):
        super().setUp()
        self.app.toolkit.add_task("Write report", due="2026-12-01", priority="high")
        self.task = self.workspace.tasks.find_task("Write report")

    def test_marks_a_task_done_by_title(self):
        self.router.handle("/done Write report")
        self.assertEqual(self.task.status, "done")

    def test_marks_a_task_done_by_id(self):
        self.router.handle(f"/done {self.task.item_id}")
        self.assertEqual(self.task.status, "done")

    def test_success_line_names_the_task_and_its_id(self):
        self.router.handle("/done Write report")
        self.assertIn(f"Completed task: Write report (id: {self.task.item_id})", self.output())

    def test_the_change_is_saved_to_disk(self):
        self.router.handle("/done Write report")
        saved = self.saved_workspace().tasks.get_task(self.task.item_id)
        self.assertEqual(saved.status, "done")

    def test_an_unknown_title_shows_the_exception_name(self):
        self.router.handle("/done Nothing like this")
        self.assertIn("TaskNotFoundError: No active task found matching 'Nothing like this'.", self.output())

    def test_an_unknown_title_leaves_the_task_open(self):
        self.router.handle("/done Nothing like this")
        self.assertEqual(self.task.status, "open")

    def test_done_without_a_task_shows_usage(self):
        self.assertEqual(self.router.handle("/done"), CommandRouter.HANDLED)
        self.assertIn("Usage: /task done <task id or title>", self.output())


class TestFileCommand(_RouterTestCase):
    def setUp(self):
        super().setUp()
        folder = os.path.join(self._tmp.name, "Juan Cruz", "My Docs")
        os.makedirs(folder)
        self.path = os.path.join(folder, "sample brief.txt")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("brief")

    def test_unquoted_path_with_spaces_is_kept_whole(self):
        self.assertEqual(CommandRouter._parse_file_command(f" {self.path}"), (self.path, ""))

    def test_unquoted_path_with_spaces_and_a_message(self):
        path, message = CommandRouter._parse_file_command(f" {self.path} please summarize this")
        self.assertEqual(path, self.path)
        self.assertEqual(message, "please summarize this")

    def test_quoted_path_and_message(self):
        path, message = CommandRouter._parse_file_command(f' "{self.path}" what is due?')
        self.assertEqual(path, self.path)
        self.assertEqual(message, "what is due?")

    def test_missing_file_with_spaces_is_not_cut_at_the_space(self):
        missing = os.path.join(self._tmp.name, "Juan Cruz", "notes.docx")
        path, message = CommandRouter._parse_file_command(f" {missing} summarize")
        self.assertEqual(path, missing)
        self.assertEqual(message, "summarize")

    def test_empty_argument_gives_no_path(self):
        self.assertEqual(CommandRouter._parse_file_command("   "), (None, ""))

    def test_file_without_a_path_shows_usage_and_asks_nothing(self):
        self.assertEqual(self.router.handle("/file"), CommandRouter.HANDLED)
        self.assertIn("write @path inside your message", self.output())
        self.assertEqual(self.app.asked, [])

    def test_file_with_a_path_sends_the_file_and_message_to_the_model(self):
        self.router.handle(f'/file "{self.path}" what is due?')
        self.assertEqual(self.app.asked, [("what is due?", [self.path])])


class TestBriefCommand(_RouterTestCase):
    def setUp(self):
        super().setUp()
        self.requested_urls = []
        self.app.briefing_service = BriefingService(
            self.workspace,
            web_lookup=WebLookup(fetcher=self._fake_fetcher),
        )

    def _fake_fetcher(self, url):
        self.requested_urls.append(url)
        if "geocoding-api.open-meteo.com" in url:
            city = "Cebu" if "Cebu" in url else "Manila"
            return f'{{"results": [{{"name": "{city}", "admin1": "", "country": "Philippines", "latitude": 14.6, "longitude": 120.98}}]}}'
        if "api.open-meteo.com" in url:
            return (
                '{"timezone": "Asia/Manila",'
                ' "current": {"time": "2026-11-26T10:00", "temperature_2m": 29.0,'
                '  "apparent_temperature": 32.0, "relative_humidity_2m": 65,'
                '  "weather_code": 1, "wind_speed_10m": 8.0},'
                ' "hourly": {"time": ["2026-11-26T15:00", "2026-11-27T12:00", "2026-11-27T15:00"],'
                '  "temperature_2m": [33.0, 30.5, 31.5],'
                '  "apparent_temperature": [36.0, 33.5, 34.5],'
                '  "relative_humidity_2m": [55, 62, 60],'
                '  "weather_code": [3, 2, 80], "wind_speed_10m": [11.0, 9.0, 10.0],'
                '  "precipitation_probability": [50, 25, 45]},'
                ' "daily": {"time": ["2026-11-26", "2026-11-27"],'
                '  "temperature_2m_max": [34.0, 33.0],'
                '  "temperature_2m_min": [25.0, 24.5],'
                '  "precipitation_probability_max": [50, 45]}}'
            )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0"><channel>'
            '<item><title>Headline One - Inquirer</title><link>https://example.com/1</link><source>Inquirer</source></item>'
            '<item><title>Headline Two - Rappler</title><link>https://example.com/2</link><source>Rappler</source></item>'
            '<item><title>Headline Three - Philstar</title><link>https://example.com/3</link><source>Philstar</source></item>'
            '<item><title>Headline Four - GMA News</title><link>https://example.com/4</link><source>GMA News</source></item>'
            '<item><title>Headline Five - ABS-CBN News</title><link>https://example.com/5</link><source>ABS-CBN News</source></item>'
            '<item><title>Headline Six - Ignored</title><link>https://example.com/6</link><source>Ignored</source></item>'
            '</channel></rss>'
        )

    def test_brief_shows_schedule_weather_and_top_five_ph_headlines_with_links_without_model_call(self):
        self.router.handle("/task add Prepare slides | 2026-11-26 | high")
        self.assertEqual(self.router.handle("/brief"), CommandRouter.HANDLED)
        out = self.output()
        self.assertIn("Daily Briefing for Thursday, November 26, 2026 at 10:00 AM", out)
        self.assertIn("Prepare slides", out)
        self.assertIn("Manila, Philippines (2026-11-26 10:00): Mainly clear, 29.0°C", out)
        self.assertIn("Top 5 Headlines (Philippines)", out)
        self.assertIn("Headline One - Inquirer", out)
        self.assertIn("https://example.com/1", out)
        self.assertIn("Headline Five - ABS-CBN News", out)
        self.assertIn("https://example.com/5", out)
        self.assertNotIn("Headline Six", out)
        self.assertEqual(self.app.asked, [])

    def test_brief_at_particular_time_and_location_shows_forecast_for_that_time(self):
        self.assertEqual(self.router.handle("/brief 15:00 | Cebu"), CommandRouter.HANDLED)
        out = self.output()
        self.assertIn("Cebu, Philippines (2026-11-26 15:00): Overcast, 33.0°C", out)
        self.assertIn("rain chance 50%", out)

    def test_brief_with_invalid_time_shows_invalid_input_error(self):
        self.assertEqual(self.router.handle("/brief 99:99"), CommandRouter.HANDLED)
        self.assertIn("InvalidInputError", self.output())

    def test_brief_tomorrow_and_tomorrow_with_time_and_location(self):
        self.assertEqual(self.router.handle("/brief tomorrow"), CommandRouter.HANDLED)
        out = self.output()
        self.assertIn("Daily Briefing for Friday, November 27, 2026", out)
        self.assertNotIn("Daily Briefing for Friday, November 27, 2026 at ", out)
        self.assertIn("Manila, Philippines (2026-11-27)", out)
        self.assertIn("30.5°C", out)

        self.buffer.truncate(0)
        self.buffer.seek(0)
        self.assertEqual(self.router.handle("/brief tomorrow 15:00 | Cebu"), CommandRouter.HANDLED)
        out = self.output()
        self.assertIn("Daily Briefing for Friday, November 27, 2026 at 3:00 PM", out)
        self.assertIn("Cebu, Philippines (2026-11-27 15:00)", out)
        self.assertIn("31.5°C", out)

    def test_brief_location_only_and_invalid_pipe_arguments(self):
        self.assertEqual(self.router.handle("/brief Cebu"), CommandRouter.HANDLED)
        self.assertIn("Cebu, Philippines (2026-11-26 10:00)", self.output())

        self.buffer.truncate(0)
        self.buffer.seek(0)
        self.assertEqual(self.router.handle("/brief badtime | Cebu"), CommandRouter.HANDLED)
        self.assertIn("InvalidInputError", self.output())

        self.buffer.truncate(0)
        self.buffer.seek(0)
        self.assertEqual(self.router.handle("/brief 15:00 | Cebu | extra"), CommandRouter.HANDLED)
        self.assertIn("InvalidInputError", self.output())


if __name__ == "__main__":
    unittest.main()
