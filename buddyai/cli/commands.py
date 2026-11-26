"""CommandRouter: turns one line typed in the terminal chat into an action."""

from datetime import datetime, timedelta
import os
import re

from buddyai.briefing import resolve_briefing_window
from buddyai.config import get_api_key
from buddyai.exceptions import BuddyError, InvalidInputError


# Encapsulation & Composition: holds the app and UI privately so main.py only calls handle() and send().
class CommandRouter:
    """Decides whether a typed line is a command and runs it.

    /task, /meet and /done call the same BuddyToolkit methods that the agents
    call, so the same rules apply, but they make no request to the model.
    """

    # The three answers handle() can give.
    EXIT = "exit"                       # the user asked to quit
    HANDLED = "handled"                 # it was a command and has been dealt with
    NOT_A_COMMAND = "not_a_command"     # an ordinary chat message

    # A first word such as /foo looks like a command; /home/me/file.pdf does not.
    _LOOKS_LIKE_COMMAND = re.compile(r"^/[a-z]+$", re.IGNORECASE)

    TASK_USAGE = (
        "Usage:\n"
        "  /task add <title> | <due> | <priority>   (due and priority are optional)\n"
        "  /task edit <task> | <title> | <due> | <priority>   "
        "(leave a field empty to keep it)\n"
        "  /task delete <task>"
    )
    MEET_USAGE = (
        "Usage:\n"
        "  /meet add <title> | <start> | <end>   "
        "(example: /meet add Review | 2026-11-30 14:00 | 2026-11-30 15:00)\n"
        "  /meet move <meeting> | <start> | <end>\n"
        "  /meet edit <meeting> | <title> | <location>   "
        "(leave a field empty to keep it)\n"
        "  /meet cancel <meeting>"
    )
    DONE_USAGE = "Usage: /done <task id or title>"
    FILE_USAGE = "Usage: /file <path> (an optional message may follow the path)"

    def __init__(self, app, ui):
        self._app = app
        self._ui = ui
        self._pending_input = ""
        # Maps each command word to the method that runs it.
        self._commands = {
            "/quit": self._quit,
            "/exit": self._quit,
            "/help": self._show_help,
            "/clear": self._clear_screen,
            "/status": self._show_status,
            "/tasks": self._show_tasks,
            "/brief": self._show_brief,
            "/model": self._change_model,
            "/models": self._change_model,
            "/file": self._attach_file,
            "/calendar": self._calendar_command,
            "/live": self._live_command,
            "/voice": self._voice_command,
            "/task": self._task_command,
            "/meet": self._meet_command,
            "/done": self._done_command,
        }

    def take_pending_input(self):
        """Return and clear any text queued to pre-fill the next input prompt."""
        text = self._pending_input
        self._pending_input = ""
        return text

    def handle(self, text):
        """Run `text` if it is a command; return EXIT, HANDLED or NOT_A_COMMAND."""
        words = text.split(None, 1)
        if not words:
            return self.NOT_A_COMMAND
        first_word = words[0]
        arguments = words[1] if len(words) > 1 else ""

        method = self._commands.get(first_word.lower())
        if method is not None:
            if method(arguments) == self.EXIT:
                return self.EXIT
            return self.HANDLED

        # A mistyped command must not be sent to the model.
        if self._LOOKS_LIKE_COMMAND.match(first_word):
            self._ui.render_warn(
                f"Unknown command {first_word}. Type /help to see the commands."
            )
            return self.HANDLED
        return self.NOT_A_COMMAND

    def send(self, prompt_text, files=None):
        """Run one chat turn with a live thinking indicator and Ctrl+C handling."""
        try:
            with self._ui.thinking_context() as indicator:
                reply = self._app.ask(
                    prompt_text, files=files, on_status=indicator.update
                )
            self._ui.render_buddy_reply(
                reply,
                agents=indicator.agents,
                elapsed=indicator.elapsed,
            )
        except KeyboardInterrupt:
            self._ui.render_warn("Cancelled.")

    # --- Simple commands (no AI call) ---

    def _quit(self, arguments):
        self._ui.render_muted("Goodbye!")
        return self.EXIT

    def _show_help(self, arguments):
        self._ui.render_help()

    def _clear_screen(self, arguments):
        self._ui.clear_and_reset(self._app)

    def _show_status(self, arguments):
        self._ui.render_status(self._app)

    def _show_tasks(self, arguments):
        self._ui.render_tasks(self._app)

    @staticmethod
    def _parse_brief_arguments(arguments, today=None):
        """Parse `/brief [today|tomorrow|HH:MM|YYYY-MM-DD|YYYY-MM-DD HH:MM] [| location]`."""
        raw = (arguments or "").strip()
        if not raw:
            return "", "", ""
        has_pipe = "|" in raw
        if has_pipe:
            parts = [part.strip() for part in raw.split("|")]
            if len(parts) > 2:
                raise InvalidInputError(
                    "Use /brief [today|tomorrow|HH:MM|YYYY-MM-DD [HH:MM]] [| location]."
                )
            when_text, location = parts[0], parts[1]
        else:
            when_text, location = raw, ""

        if not when_text:
            return "", "", location

        first_word, _, rest = when_text.partition(" ")
        lower_word = first_word.lower()
        if lower_word in ("today", "tomorrow") and today is not None:
            resolved_day = (
                today if lower_word == "today" else today + timedelta(days=1)
            )
            return resolved_day.isoformat(), rest.strip(), location

        if not when_text[0].isdigit():
            if has_pipe:
                return "", when_text, location
            return "", "", when_text

        if len(when_text) == 10 and when_text[4] == "-" and when_text[7] == "-":
            return when_text, "", location
        return "", when_text, location

    def _show_brief(self, arguments):
        try:
            now = self._app.toolkit.current_time()
            day_text, time_text, location = self._parse_brief_arguments(
                arguments, today=now.date()
            )
            target_now, weather_at = resolve_briefing_window(
                now, day=day_text, at_time=time_text
            )
        except BuddyError as exc:
            self._ui.render_error(f"{type(exc).__name__}: {exc}")
            return
        self._ui.render_brief(
            self._app,
            target_now=target_now,
            weather_at=weather_at,
            location=location or None,
        )

    # --- /model and /file ---

    def _change_model(self, arguments):
        """Handle `/model` (interactive picker or list) and `/model <choice>`."""
        if not arguments.strip():
            chosen = self._ui.pick_model_interactive(self._app)
            if not self._ui.interactive:
                return
            if chosen is None:
                self._ui.render_muted("Model unchanged.")
                return
            reply = self._app.run_model_command(f"/model {chosen}")
        else:
            reply = self._app.run_model_command(f"/model {arguments.strip()}")

        if reply is None:
            return
        if reply.level == "ok":
            self._ui.render_ok(reply.text)
        elif reply.level == "warn":
            self._ui.render_warn(reply.text)
        elif reply.level == "error":
            self._ui.render_error(reply.text)
        else:
            self._ui.render_muted(reply.text)

    def _attach_file(self, arguments):
        """Handle `/file <path> [message]` by sending the file to the model."""
        file_path, note_prompt = self._parse_file_command(arguments)
        if not file_path:
            self._ui.render_warn(self.FILE_USAGE)
            return
        self.send(note_prompt, files=[file_path])

    @staticmethod
    def _format_calendar_summary(source):
        """Format a loaded IcsCalendarSource summary line for the user."""
        loaded_part = f"{source.loaded_count} events loaded"
        if source.recurring_count > 0:
            loaded_part += (
                f" ({source.recurring_count} recurring, first occurrence only)"
            )
        parts = [loaded_part]
        if source.all_day_count > 0:
            parts.append(f"{source.all_day_count} all-day events skipped")
        if source.skipped_count > 0:
            parts.append(f"{source.skipped_count} skipped as unreadable")
        return f"{source.path}: {', '.join(parts)}"

    def _calendar_command(self, arguments):
        """Handle `/calendar`, `/calendar <path>`, and `/calendar off`."""
        raw = arguments.strip()
        if not raw:
            source = self._app.calendar_source
            if source is not None:
                self._ui.render_ok(self._format_calendar_summary(source))
            else:
                self._ui.render_muted(
                    "No calendar file loaded. Use /calendar <path> or set "
                    "BUDDYAI_ICS_FILE in buddy_agent/.env."
                )
            if self._app.calendar_error:
                self._ui.render_warn(self._app.calendar_error)
            return

        if raw.lower() == "off":
            if self._app.unload_calendar():
                self._ui.render_ok("Calendar file removed.")
            else:
                self._ui.render_muted("No calendar file was loaded.")
            return

        path = raw
        if len(path) >= 2 and path[0] == path[-1] and path[0] in ('"', "'"):
            path = path[1:-1].strip()
        abs_path = os.path.abspath(os.path.expanduser(path))
        try:
            source = self._app.load_calendar(abs_path)
        except BuddyError as exc:
            self._ui.render_error(f"{type(exc).__name__}: {exc}")
            return
        self._ui.render_ok(self._format_calendar_summary(source))

    def _render_voice_text(self, speaker, text):
        """Display spoken transcripts from VoiceSession in the terminal."""
        if speaker == "You":
            self._ui.render_muted(f"You: {text}")
        elif speaker == "System":
            self._ui.render_muted(text)
        else:
            self._ui.console.print(f"{speaker}: {text}", style="buddy.text")

    def _live_command(self, arguments):
        """Handle `/live` (speaker-safe) and `/live barge` (full-duplex headphones)."""
        if not get_api_key():
            self._ui.render_warn(
                "GOOGLE_API_KEY is not set. Add your Gemini API key in "
                "buddy_agent/.env to use BuddyAI Live."
            )
            return
        mode = arguments.strip().lower()
        barge_in = mode in ("barge", "headphones", "duplex")
        if barge_in:
            self._ui.render_muted(
                "BuddyAI Live on (full-duplex barge-in — use headphones). "
                'Speak freely; say "stop" or press Ctrl+C to return to text chat.'
            )
        else:
            self._ui.render_muted(
                "BuddyAI Live on (speaker-safe). Speak to BuddyAI. Press Space "
                'or Enter to interrupt, or say "stop" / press Ctrl+C to exit.'
            )
        try:
            session = self._app.start_voice_session(
                on_text=self._render_voice_text,
                echo_guard=not barge_in,
            )
            self._app.run_voice(session)
        except BuddyError as exc:
            self._ui.render_error(f"{type(exc).__name__}: {exc}")
        finally:
            self._ui.render_muted("BuddyAI Live ended. Back to the text chat.")

    def _voice_command(self, arguments):
        """Handle `/voice`: stream live speech-to-text, then pre-fill the regular text prompt."""
        if not get_api_key():
            self._ui.render_warn(
                "GOOGLE_API_KEY is not set. Add your Gemini API key in "
                "buddy_agent/.env to use voice dictation."
            )
            return

        if self._ui.interactive:
            from rich.live import Live
            from rich.text import Text

            prompt_glyph = self._ui.glyphs["prompt"]

            def _build_live_view(current_text):
                view = Text()
                view.append(
                    "Listening... speak now (Enter to finish, Esc/Ctrl+C to cancel)\n",
                    style="muted",
                )
                view.append(f"{prompt_glyph} ", style="user.prompt")
                if current_text:
                    view.append(current_text, style="user.text")
                else:
                    view.append("...", style="muted")
                return view

            try:
                with Live(
                    _build_live_view(""),
                    console=self._ui.console,
                    refresh_per_second=12,
                    transient=True,
                ) as live:
                    transcript = self._app.transcribe_voice(
                        on_update=lambda text: live.update(_build_live_view(text))
                    )
            except KeyboardInterrupt:
                self._ui.render_muted("Dictation cancelled.")
                return
            except BuddyError as exc:
                self._ui.render_error(f"{type(exc).__name__}: {exc}")
                return
        else:
            self._ui.render_muted(
                "Listening... speak now, then press Enter to transcribe (Ctrl+C to cancel)."
            )
            try:
                transcript = self._app.transcribe_voice()
            except KeyboardInterrupt:
                self._ui.render_muted("Dictation cancelled.")
                return
            except BuddyError as exc:
                self._ui.render_error(f"{type(exc).__name__}: {exc}")
                return

        if not transcript:
            self._ui.render_muted("No speech detected.")
            return
        self._pending_input = transcript
        self._ui.render_ok(
            "Transcribed. Review or edit below, then press Enter to send."
        )

    @staticmethod
    def _parse_file_command(raw_args):
        """Parse `/file <path> [message]`, where the path may contain spaces."""
        text = raw_args.strip()
        if not text:
            return None, ""

        # A quoted path ends at the matching quote; the rest is the message.
        if text[0] in ('"', "'"):
            closing = text.find(text[0], 1)
            if closing != -1:
                return text[1:closing].strip(), text[closing + 1:].strip()
            text = text[1:]

        # Unquoted: prefer the longest run of words that is a real file, so a path
        # such as C:\Users\Juan Cruz\brief.pdf is not cut at the space.
        words = text.split(" ")
        for count in range(len(words), 0, -1):
            candidate = " ".join(words[:count]).strip()
            if os.path.isfile(candidate):
                return candidate, " ".join(words[count:]).strip()

        # No such file: stop at the first word that ends in an extension so the
        # error names the whole path instead of half of it.
        for count in range(1, len(words) + 1):
            candidate = " ".join(words[:count]).strip()
            if os.path.splitext(candidate)[1]:
                return candidate, " ".join(words[count:]).strip()
        return words[0], " ".join(words[1:]).strip()

    # --- Direct commands that change data without calling the model ---

    def _task_command(self, arguments):
        """Handle `/task add`, `/task edit` and `/task delete`."""
        subcommand, _, rest = arguments.strip().partition(" ")
        methods = {
            "add": self._task_add,
            "edit": self._task_edit,
            "delete": self._task_delete,
        }
        method = methods.get(subcommand.lower())
        if method is None:
            self._ui.render_warn(self.TASK_USAGE)
            return
        method(self._split_fields(rest))

    def _task_add(self, fields):
        """Handle `/task add <title> | <due> | <priority>`."""
        if not 1 <= len(fields) <= 3 or not fields[0]:
            self._ui.render_warn(self.TASK_USAGE)
            return

        title = fields[0]
        due = fields[1] if len(fields) > 1 else ""
        priority = fields[2] if len(fields) > 2 and fields[2] else "medium"
        result = self._app.toolkit.add_task(title, due=due, priority=priority)
        self._show_result(result, "task", "Added task")

    def _task_edit(self, fields):
        """Handle `/task edit <task> | <title> | <due> | <priority>`."""
        if not 1 <= len(fields) <= 4 or not fields[0]:
            self._ui.render_warn(self.TASK_USAGE)
            return

        # Missing fields are treated like empty ones: the task keeps its value.
        task = fields[0]
        title, due, priority = (fields[1:] + ["", "", ""])[:3]
        if not (title or due or priority):
            self._ui.render_warn(self.TASK_USAGE)
            return

        result = self._app.toolkit.update_task(
            task, title=title, due=due, priority=priority
        )
        self._show_result(result, "task", "Updated task")

    def _task_delete(self, fields):
        """Handle `/task delete <task>`."""
        if len(fields) != 1 or not fields[0]:
            self._ui.render_warn(self.TASK_USAGE)
            return

        result = self._app.toolkit.delete_task(fields[0])
        self._show_result(result, "task", "Deleted task")

    def _meet_command(self, arguments):
        """Handle `/meet add`, `/meet move`, `/meet edit` and `/meet cancel`."""
        subcommand, _, rest = arguments.strip().partition(" ")
        methods = {
            "add": self._meet_add,
            "move": self._meet_move,
            "edit": self._meet_edit,
            "cancel": self._meet_cancel,
        }
        method = methods.get(subcommand.lower())
        if method is None:
            self._ui.render_warn(self.MEET_USAGE)
            return
        method(self._split_fields(rest))

    def _meet_add(self, fields):
        """Handle `/meet add <title> | <start> | <end>`."""
        if len(fields) != 3 or not all(fields):
            self._ui.render_warn(self.MEET_USAGE)
            return

        title, start, end = fields
        result = self._app.toolkit.schedule_meeting(title, start, end)
        self._show_result(result, "meeting", "Scheduled meeting")

    def _meet_move(self, fields):
        """Handle `/meet move <meeting> | <start> | <end>`."""
        if len(fields) != 3 or not all(fields):
            self._ui.render_warn(self.MEET_USAGE)
            return

        meeting, start, end = fields
        result = self._app.toolkit.reschedule_meeting(meeting, start, end)
        self._show_result(result, "meeting", "Moved meeting")

    def _meet_edit(self, fields):
        """Handle `/meet edit <meeting> | <title> | <location>`."""
        if not 1 <= len(fields) <= 3 or not fields[0]:
            self._ui.render_warn(self.MEET_USAGE)
            return

        # Missing fields are treated like empty ones: the meeting keeps its value.
        meeting = fields[0]
        title, location = (fields[1:] + ["", ""])[:2]
        if not (title or location):
            self._ui.render_warn(self.MEET_USAGE)
            return

        result = self._app.toolkit.update_meeting(
            meeting, title=title, location=location
        )
        self._show_result(result, "meeting", "Updated meeting")

    def _meet_cancel(self, fields):
        """Handle `/meet cancel <meeting>`."""
        if len(fields) != 1 or not fields[0]:
            self._ui.render_warn(self.MEET_USAGE)
            return

        result = self._app.toolkit.cancel_meeting(fields[0])
        self._show_result(result, "meeting", "Cancelled meeting")

    def _done_command(self, arguments):
        """Handle `/done <task id or title>`."""
        task = arguments.strip()
        if not task:
            self._ui.render_warn(self.DONE_USAGE)
            return
        result = self._app.toolkit.complete_task(task)
        self._show_result(result, "task", "Completed task")

    @staticmethod
    def _split_fields(text):
        """Split `a | b | c` into a list of stripped fields."""
        if not text.strip():
            return []
        return [part.strip() for part in text.split("|")]

    def _show_result(self, result, item_key, success_label):
        """Show a toolkit result: a green line on success, a red error line otherwise."""
        if result.get("status") == "success":
            item = result[item_key]
            self._ui.render_ok(f"{success_label}: {item['title']} (id: {item['item_id']})")
            return

        self._ui.render_error(f"{result['error_type']}: {result['message']}")
        suggested = result.get("suggested_start")
        if suggested:
            start = datetime.fromisoformat(suggested)
            self._ui.render_muted(
                f"Suggested free start: {start.strftime('%Y-%m-%d %H:%M')}"
            )
