"""BuddyApp wiring domain managers, persistence, ADK agents, and session state."""

import asyncio
import hashlib
import logging
import os

from buddyai.agents.profiles import (
    BriefingAgentProfile,
    CoordinatorProfile,
    NotesAgentProfile,
    ScheduleAgentProfile,
    TaskAgentProfile,
    VoiceCoordinatorProfile,
    make_llm,
)
from buddyai.briefing import BriefingService
from buddyai.config import (
    default_clock,
    get_api_key,
    get_auto_switch,
    get_data_dir,
    get_ics_file,
    get_model,
    get_model_choices,
    get_voice_model,
)
from buddyai.document_reader import DocumentReader
from buddyai.exceptions import BuddyError, DataSourceError
from buddyai.model_catalog import ModelCatalog
from buddyai.model_limits import ModelLimitLog
from buddyai.sources.ics_calendar_source import IcsCalendarSource
from buddyai.sources.json_store import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.web_lookup import WebLookup
from buddyai.workspace import Workspace

logger = logging.getLogger(__name__)


# Encapsulation: pairs a model-command reply with its display level behind read-only properties.
class CommandReply:
    """Result of running a chat command, carrying both message text and severity level."""

    VALID_LEVELS = ("info", "ok", "warn", "error")

    def __init__(self, text, level="info"):
        if level not in self.VALID_LEVELS:
            raise ValueError(f"Unknown CommandReply level '{level}'.")
        self._text = str(text)
        self._level = level

    @property
    def text(self):
        return self._text

    @property
    def level(self):
        return self._level


# Facade & Composition: assembles all layers and manages one ADK session/event loop.
class BuddyApp:
    """Application container for both the terminal chat and ADK web UI."""

    APP_NAME = "buddyai"
    # A model call that never answers must not freeze the chat forever.
    TURN_TIMEOUT_SECONDS = 180
    USER_ID = "local_user"
    SESSION_ID = "main_session"

    def __init__(
        self,
        data_dir=None,
        model=None,
        doc_model=None,
        clock=None,
        doc_client=None,
        extra_sources=None,
        ics_file=None,
        web_lookup=None,
    ):
        resolved_data_dir = data_dir if data_dir is not None else get_data_dir()
        self._uploads_dir = os.path.join(os.fspath(resolved_data_dir), "uploads")
        resolved_clock = clock if clock is not None else default_clock
        self._clock = resolved_clock

        # One model object is shared by all five agents, so changing its model
        # name switches every agent at once (see switch_model).
        if model is None or isinstance(model, str):
            self._llm = make_llm(model if model else get_model())
        else:
            self._llm = model
        self._catalog = ModelCatalog(get_model_choices(), self._llm.model)
        # Daily limits found on an earlier run today are known as soon as BuddyAI opens.
        self._limit_log = ModelLimitLog(resolved_data_dir, resolved_clock)
        self._auto_switch = get_auto_switch()
        self._sync_limits()

        store = JsonStore(resolved_data_dir)
        sources = [store]
        if extra_sources:
            sources.extend(extra_sources)

        self._workspace = Workspace(sources=sources)
        self._workspace.load()

        self._calendar_source = None
        self._calendar_error = ""
        resolved_ics = get_ics_file() if ics_file is None else str(ics_file).strip()
        if resolved_ics:
            try:
                cal_source = IcsCalendarSource(resolved_ics, clock=self._clock)
                cal_source.fetch_items()
            except DataSourceError as exc:
                self._calendar_error = str(exc)
                logger.warning("Could not load calendar file %s: %s", resolved_ics, exc)
            else:
                self._calendar_source = cal_source
                self._workspace.replace_source(cal_source)

        self._workspace.sync()

        self._web_lookup = web_lookup if web_lookup is not None else WebLookup()
        self._briefing_service = BriefingService(
            self._workspace,
            web_lookup=self._web_lookup,
        )
        self._document_reader = DocumentReader(
            model=doc_model,
            client=doc_client,
            clock=resolved_clock,
        )
        self._toolkit = BuddyToolkit(
            workspace=self._workspace,
            briefing_service=self._briefing_service,
            document_reader=self._document_reader,
            clock=resolved_clock,
            web_lookup=self._web_lookup,
        )

        self._specialists = [
            TaskAgentProfile(model=self._llm, toolkit=self._toolkit),
            ScheduleAgentProfile(model=self._llm, toolkit=self._toolkit),
            NotesAgentProfile(model=self._llm, toolkit=self._toolkit),
            BriefingAgentProfile(model=self._llm, toolkit=self._toolkit),
        ]
        self._coordinator_profile = CoordinatorProfile(
            model=self._llm,
            toolkit=self._toolkit,
            specialists=self._specialists,
            command_handler=self.intercept,
            upload_handler=self.save_upload,
        )
        self._root_agent = self._coordinator_profile.build()
        # Every agent answers a failed model call with the same clear reply, in
        # the terminal chat and in the ADK browser chat alike.
        for agent in [self._root_agent] + list(self._root_agent.sub_agents):
            agent.on_model_error_callback = self._on_model_error
        # Notes such as "X is used up, so I switched to Y" wait here until the
        # coordinator's next reply, which carries them to the user.
        self._root_agent.after_model_callback = self._attach_notices
        self._pending_notices = []
        # ADK gives each user message its own invocation ID; a new ID is what
        # starts a new request for the untrusted-content guard.
        self._last_request_invocation = None
        self._root_agent.before_agent_callback = self._start_request
        self._startup_note = ""
        self._saves_at_turn_start = None
        self._last_failed_invocation = None
        self._leave_used_up_model_at_startup()

        self._loop = None
        self._runner = None
        self._session_ready = False

    @property
    def root_agent(self):
        return self._root_agent

    @property
    def workspace(self):
        return self._workspace

    @property
    def toolkit(self):
        return self._toolkit

    @property
    def briefing_service(self):
        return self._briefing_service

    @property
    def current_model(self):
        return self._catalog.current

    @property
    def model_catalog(self):
        return self._catalog

    @property
    def calendar_source(self):
        return self._calendar_source

    @property
    def calendar_error(self):
        return self._calendar_error

    def load_calendar(self, path):
        """Validate and load a read-only .ics calendar file into the workspace."""
        abs_path = os.path.abspath(os.path.expanduser(os.fspath(path)))
        source = IcsCalendarSource(abs_path, clock=self._clock)
        source.fetch_items()
        self._workspace.replace_source(source)
        self._workspace.sync()
        self._calendar_source = source
        self._calendar_error = ""
        return source

    def unload_calendar(self):
        """Remove the loaded .ics calendar source and re-sync the workspace."""
        removed = self._workspace.remove_source(IcsCalendarSource.DEFAULT_NAME)
        self._workspace.sync()
        self._calendar_source = None
        return removed

    def sync_model_limits(self):
        """Refresh today's daily-limit state in the model catalog."""
        self._sync_limits()

    def consume_startup_note(self):
        """Return and clear any startup failover notice without formatting a model banner."""
        self._sync_limits()
        note = self._startup_note
        if note and note in self._pending_notices:
            self._pending_notices.remove(note)
        self._startup_note = ""
        return note

    def switch_model(self, choice):
        """Switch every agent and the file reader to another model; return its name."""
        name = self._catalog.switch(choice)
        self._llm.model = name
        self._document_reader.set_model(name)
        return name

    def check_file(self, path):
        """Check that a file can be summarized, before any model request.

        Returns the absolute path; raises UnsupportedFileTypeError or
        InvalidInputError, so the terminal can show the error at once.
        """
        abs_path, _ = self._document_reader.validate_file(path)
        return abs_path

    def save_upload(self, data, mime_type, name=""):
        """Save a file attached in the browser chat; return the text that replaces it.

        The file goes to the uploads folder inside the data folder. The same
        file is stored once, however many times the chat history is re-sent.
        """
        extension = self._document_reader.extension_for(name, mime_type)
        label = name or "a file"
        if extension is None:
            return (
                f"(The user attached {label} of type '{mime_type or 'unknown'}'. "
                "BuddyAI can only read PDF, PNG, JPG and TXT files, so it was not "
                "opened. Tell the user this.)"
            )
        digest = hashlib.sha1(data).hexdigest()[:8]
        base = os.path.splitext(os.path.basename(name))[0] if name else "upload"
        safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in base).strip()
        filename = f"{safe or 'upload'}-{digest}{extension}"
        path = os.path.join(self._uploads_dir, filename)
        if not os.path.isfile(path):
            os.makedirs(self._uploads_dir, exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
        return f"Attached file path to summarize: {os.path.abspath(path)}"

    def run_model_command(self, text):
        """Answer a /model command with a CommandReply, or return None for other text."""
        words = (text or "").strip().split(None, 1)
        if not words or words[0].lower() not in ("/model", "/models"):
            return None
        self._sync_limits()
        try:
            if len(words) == 1:
                return CommandReply(self._catalog.describe(), "info")
            name = self.switch_model(words[1])
        except BuddyError as exc:
            return CommandReply(str(exc), "error")
        if self._catalog.reason_for(name) == ModelCatalog.DAILY_LIMIT:
            if not self._auto_switch:
                return CommandReply(self._switch_required_message(), "warn")
            return CommandReply(
                f"Switched to {name}, but it has reached today's free request limit "
                f"and will not answer until {self._reset_text()}. BuddyAI will move "
                "to the next usable model when you send a message.",
                "warn",
            )
        return CommandReply(
            f"Switched to {name}. Your tasks, meetings and notes are unchanged.",
            "ok",
        )

    def handle_command(self, text):
        """Answer a chat command (/model); return None for an ordinary message.

        Both entry points use this: ask() for the terminal chat, and the
        coordinator's before-model hook for the ADK browser chat.
        """
        reply = self.run_model_command(text)
        return None if reply is None else reply.text

    def _sync_limits(self):
        """Copy today's 'daily limit reached' list from the log into the catalog."""
        self._catalog.set_daily_limited(self._limit_log.limited_today())

    def _reset_text(self):
        reset = self._limit_log.next_reset()
        return reset.strftime("%I:%M %p").lstrip("0") + reset.strftime(" on %A")

    def _switch_required_message(self):
        """Tell the user the current model is used up and that they must switch."""
        current = self._catalog.current
        lines = [
            f"{current} has reached today's free request limit. "
            f"It will answer again after {self._reset_text()}."
        ]
        if self._catalog.next_available() is None:
            lines.append(
                "Every other model in the list is also unusable right now, so "
                "BuddyAI cannot answer until then."
            )
        else:
            lines.append("You need to switch models to continue.")
        lines.append(self._catalog.describe())
        lines.append("After switching, send your message again.")
        return "\n\n".join(lines)

    def _leave_used_up_model(self, wording):
        """If the current model is used up today, move to the next best one.

        Returns True if the current model can be used after this call. `wording`
        is the note for the user, with {failed} and {replacement} filled in.
        Without automatic switching, or with no usable model left, nothing moves.
        """
        self._sync_limits()
        failed = self._catalog.current
        if self._catalog.reason_for(failed) != ModelCatalog.DAILY_LIMIT:
            return True
        replacement = self._catalog.best_available() if self._auto_switch else None
        if replacement is None:
            return False
        self.switch_model(replacement)
        self._pending_notices.append(
            wording.format(failed=failed, replacement=replacement)
        )
        return True

    def _leave_used_up_model_at_startup(self):
        """Start on a usable model when today's limit for the configured one is known."""
        notes_before = len(self._pending_notices)
        self._leave_used_up_model(
            "{failed} reached today's free request limit earlier, so BuddyAI is "
            "starting on {replacement}."
        )
        if len(self._pending_notices) > notes_before:
            self._startup_note = self._pending_notices[-1]

    def intercept(self, text):
        """Answer a message without calling the model when no call is needed.

        That covers chat commands, and any message sent while the current model
        is known to be out of free requests: asking it again would only fail.
        In that case BuddyAI first moves to the next best model, unless
        automatic switching is off or no model is left.
        """
        reply = self.handle_command(text)
        if reply is not None:
            return reply
        usable = self._leave_used_up_model(
            "{failed} has reached today's free request limit, so I switched to "
            "{replacement}."
        )
        return None if usable else self._switch_required_message()

    def startup_notice(self):
        """Return what the terminal chat shows about the model when it opens."""
        self._sync_limits()
        if self._catalog.reason_for(self._catalog.current) == ModelCatalog.DAILY_LIMIT:
            return self._switch_required_message()
        model_line = f"Model: {self.current_model} (type /model to switch)"
        if not self._startup_note:
            return model_line
        # Shown here, so it does not need repeating in the first reply.
        if self._startup_note in self._pending_notices:
            self._pending_notices.remove(self._startup_note)
        return f"{self._startup_note}\n{model_line}"

    def _take_notices(self):
        """Return the waiting notes as one block of text and clear them."""
        if not self._pending_notices:
            return ""
        text = "\n".join(self._pending_notices)
        self._pending_notices = []
        return text

    def _with_notices(self, response):
        """Put the waiting notes in front of a plain-text model reply."""
        if not self._pending_notices or response is None or response.content is None:
            return response
        if getattr(response, "partial", False):
            return response
        parts = response.content.parts or []
        if any(part.function_call for part in parts):
            return response             # not the final wording yet; keep waiting
        for part in parts:
            if part.text:
                part.text = f"{self._take_notices()}\n\n{part.text}"
                break
        return response

    def _start_request(self, callback_context):
        """ADK calls this when the coordinator starts work on a user message.

        Only a new invocation ID counts as a new request. Text inside the model
        request is not used, because a file or web page could imitate a message.
        """
        invocation = getattr(callback_context, "invocation_id", None)
        if invocation != self._last_request_invocation:
            self._last_request_invocation = invocation
            self._toolkit.begin_request()
        return None

    def _attach_notices(self, callback_context, llm_response):
        """ADK calls this after each coordinator model reply."""
        return self._with_notices(llm_response)

    def _get_event_loop(self):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    async def _ensure_runner(self):
        if self._runner is None:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService

            session_service = InMemorySessionService()
            await session_service.create_session(
                app_name=self.APP_NAME,
                user_id=self.USER_ID,
                session_id=self.SESSION_ID,
            )
            self._runner = Runner(
                agent=self._root_agent,
                app_name=self.APP_NAME,
                session_service=session_service,
            )
            self._session_ready = True
        return self._runner

    _SPECIALIST_NAMES = (
        "task_agent",
        "schedule_agent",
        "notes_agent",
        "briefing_agent",
    )

    @staticmethod
    def _notify_status(on_status, stage, agent=None):
        """Safely invoke an optional UI status callback with a plain stage key."""
        if on_status is None:
            return
        try:
            on_status(stage, agent)
        except Exception:
            pass

    async def _run_turn(self, prompt_text, on_status=None):
        from google.genai import types

        runner = await self._ensure_runner()
        content = types.Content(
            role="user",
            parts=[types.Part(text=prompt_text)],
        )
        self._notify_status(on_status, "thinking", None)
        final_reply = ""
        async for event in runner.run_async(
            user_id=self.USER_ID,
            session_id=self.SESSION_ID,
            new_message=content,
        ):
            author = getattr(event, "author", None)
            if author in self._SPECIALIST_NAMES:
                self._notify_status(on_status, "agent", author)
            if event.content and event.content.parts:
                for part in event.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc is None:
                        continue
                    fc_name = getattr(fc, "name", "")
                    fc_args = getattr(fc, "args", None) or {}
                    if fc_name == "transfer_to_agent":
                        target = fc_args.get("agent_name")
                        if target:
                            self._notify_status(on_status, "agent", target)
                    elif fc_name == "summarize_document":
                        self._notify_status(on_status, "reading_document", "notes_agent")
                    elif fc_name in ("search_web", "get_weather"):
                        self._notify_status(on_status, "searching_web", None)
            if event.is_final_response() and event.content and event.content.parts:
                text_parts = [
                    part.text for part in event.content.parts if getattr(part, "text", None)
                ]
                if text_parts:
                    final_reply = "\n".join(text_parts)
        return final_reply or "I completed that, though I have nothing additional to report."

    @staticmethod
    def _format_api_error(exc):
        detail = str(exc) or type(exc).__name__
        upper = detail.upper()
        # Read the HTTP status from the error object: matching digits in the text
        # is unreliable (a "retry in 16503s" hint contains "503").
        code = getattr(exc, "code", None)
        if BuddyApp._is_timeout(exc):
            return (
                "Gemini took too long to answer, so I stopped waiting. Send your "
                "message again, or type /model next to try another model."
            )
        if code == 429 or "RESOURCE_EXHAUSTED" in upper:
            if "PERDAY" in upper or "PER DAY" in upper:
                return (
                    "Today's free request limit for this Gemini model is used up. It "
                    "resets at midnight US Pacific time. To keep working now, type "
                    "/model next to switch to another model."
                )
            return (
                "The Gemini API rate limit was reached. Please wait a minute and try again."
            )
        if code == 503 or "UNAVAILABLE" in upper:
            return (
                "Gemini is busy right now (this model is under high demand). Send your "
                "message again in a moment, or type /model next to switch to another "
                "model."
            )
        if code in (401, 403) or "API_KEY" in upper or "PERMISSION_DENIED" in upper:
            return (
                "Authentication with the Gemini API failed. Check GOOGLE_API_KEY in buddy_agent/.env."
            )
        logger.exception("Error while running BuddyApp.ask.")
        return (
            f"Sorry, I ran into a problem talking to Gemini ({detail}). Send your "
            "message again, or type /model next to try another model."
        )

    @staticmethod
    def _is_daily_limit(exc):
        """Return True for a 429 that says the per-day free quota is used up."""
        upper = str(exc).upper()
        is_quota = getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in upper
        return is_quota and ("PERDAY" in upper or "PER DAY" in upper)

    @staticmethod
    def _is_timeout(exc):
        return isinstance(exc, asyncio.TimeoutError) or "TIMEOUT" in type(exc).__name__.upper()

    def _unusable_reason(self, exc):
        """Say why the current model cannot be used, or None if the error is not about that."""
        if self._is_daily_limit(exc):
            return ModelCatalog.DAILY_LIMIT
        text = str(exc).upper()
        if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in text:
            return ModelCatalog.RATE_LIMITED
        # 500-504 are Google-side failures: busy, overloaded, or too slow to finish.
        server_side = getattr(exc, "code", None) in (500, 502, 503, 504)
        busy = server_side or "UNAVAILABLE" in text or "DEADLINE_EXCEEDED" in text
        if busy or self._is_timeout(exc):
            return ModelCatalog.NOT_RESPONDING
        return None

    @staticmethod
    def _why(model, reason):
        """Say in plain words why a model was left."""
        if reason == ModelCatalog.DAILY_LIMIT:
            return f"{model} has reached today's free request limit"
        if reason == ModelCatalog.RATE_LIMITED:
            return f"{model} has reached its requests-per-minute limit"
        return f"{model} is not responding right now"

    def _note_failure(self, exc):
        """Record a failed model request; return (model, reason) for the reply."""
        reason = self._unusable_reason(exc)
        failed = self._catalog.current
        # Keep a short record in buddyai.log; the chat only shows the plain reply.
        logger.warning(
            "Model request to %s failed (%s): %s",
            failed, type(exc).__name__, str(exc)[:300],
        )
        if reason == ModelCatalog.DAILY_LIMIT:
            self._limit_log.record(failed)      # remembered until Google's reset
            self._sync_limits()
        elif reason is not None:
            self._catalog.mark_unavailable(failed, reason)
        return failed, reason

    def _nothing_usable_message(self, exc, reason):
        """Reply for a failure when there is no other model to move to."""
        if reason == ModelCatalog.DAILY_LIMIT:
            return self._switch_required_message()
        return self._format_api_error(exc)

    def _reply_to_failure(self, exc):
        """Turn a failed turn into a reply the user can act on.

        Used when the request cannot be repeated from here (the whole turn
        timed out, or automatic switching is off). With automatic switching on,
        BuddyAI moves to the next best model and asks for the message again.
        """
        failed, reason = self._note_failure(exc)
        if self._auto_switch and reason is not None:
            replacement = self._catalog.best_available()
            if replacement is not None:
                self.switch_model(replacement)
                return (
                    f"{self._why(failed, reason)}, so I switched to {replacement}. "
                    "Please send your message again."
                )
        return self._nothing_usable_message(exc, reason)

    async def _ask_current_model(self, llm_request):
        """Send a prepared request to the model that is in use now."""
        llm_request.model = self._llm.model
        answer = None
        async for response in self._llm.generate_content_async(llm_request, stream=False):
            answer = response
        if answer is None:
            raise RuntimeError("The model returned no answer.")
        return answer

    async def _fail_over(self, llm_request, error, is_coordinator):
        """Move down the model list until one answers the request that failed.

        The failed request produced nothing, so repeating it on another model
        cannot do anything twice. Each model that fails is marked, which is
        what stops this loop. The user is told about every switch.
        """
        while True:
            failed, reason = self._note_failure(error)
            replacement = self._catalog.best_available() if reason is not None else None
            if replacement is None:
                return self._text_response(
                    self._nothing_usable_message(error, reason) + self._already_saved_note()
                )
            self.switch_model(replacement)
            self._pending_notices.append(
                f"{self._why(failed, reason)}, so I switched to {replacement}."
            )
            try:
                answer = await self._ask_current_model(llm_request)
            except Exception as exc:
                error = exc
                continue
            # A specialist's answer goes back to the coordinator, whose own
            # reply will carry the note to the user.
            return self._with_notices(answer) if is_coordinator else answer

    @staticmethod
    def _text_response(text):
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types

        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )

    def _already_saved_note(self):
        """Return a warning if a tool saved a change earlier in this terminal turn."""
        started = self._saves_at_turn_start
        if started is None or self._workspace.save_count == started:
            return ""
        return (
            " Part of your request was already saved before this error, "
            "so check your tasks and meetings before repeating it."
        )

    async def _on_model_error(self, callback_context, llm_request, error):
        """ADK calls this when a model request fails; the reply replaces the error."""
        if isinstance(error, asyncio.CancelledError):
            return None                 # the turn was stopped on purpose (time limit)
        # "Busy" and "per-minute limit" marks are only good for one user message.
        invocation = getattr(callback_context, "invocation_id", None)
        if invocation != self._last_failed_invocation:
            self._catalog.clear_temporary()
            self._last_failed_invocation = invocation
        if not self._auto_switch:
            return self._text_response(
                self._reply_to_failure(error) + self._already_saved_note()
            )
        agent_name = getattr(callback_context, "agent_name", None)
        is_coordinator = agent_name == self._root_agent.name
        return await self._fail_over(llm_request, error, is_coordinator)

    def ask(self, message, files=None, on_status=None):
        """Send a user message (and optional file paths) through the ADK coordinator."""
        self._saves_at_turn_start = self._workspace.save_count
        self._toolkit.begin_request()
        try:
            if not isinstance(message, str):
                raise BuddyError("Message must be text.")
            prompt_text = message.strip()

            attached_paths = []
            if files:
                for path in files:
                    abs_path, _ = self._document_reader.validate_file(path)
                    attached_paths.append(abs_path)

            if attached_paths:
                file_lines = "\n".join(
                    f"Attached file path to summarize: {path}"
                    for path in attached_paths
                )
                if prompt_text:
                    prompt_text = f"{prompt_text}\n\n{file_lines}"
                else:
                    prompt_text = (
                        "Please summarize the attached file(s) and list suggested "
                        f"action items.\n\n{file_lines}"
                    )

            if not prompt_text:
                return "Please enter a message, or attach a file by writing @path in it."

            command_reply = self.intercept(prompt_text)
            if command_reply is not None:
                return command_reply

            if not get_api_key():
                return (
                    "GOOGLE_API_KEY is missing. Copy buddy_agent/.env.example to "
                    "buddy_agent/.env and add your Gemini API key."
                )

            loop = self._get_event_loop()
            task = loop.create_task(
                asyncio.wait_for(
                    self._run_turn(prompt_text, on_status=on_status),
                    timeout=self.TURN_TIMEOUT_SECONDS,
                )
            )
            try:
                reply = loop.run_until_complete(task)
            except KeyboardInterrupt:
                task.cancel()
                try:
                    loop.run_until_complete(task)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    pass
                raise
            # Normally a switch note is already in the reply; this catches the rest.
            leftover = self._take_notices()
            return f"{leftover}\n\n{reply}" if leftover else reply
        except KeyboardInterrupt:
            raise
        except BuddyError as exc:
            return str(exc)
        except Exception as exc:
            # A tool may have saved a change before the step that failed.
            return self._reply_to_failure(exc) + self._already_saved_note()
        finally:
            self._saves_at_turn_start = None

    def build_voice_agent(self):
        """Build a fresh coordinator tree using the configured Live model for voice mode."""
        from google.adk.models import Gemini

        # Plain Gemini (not make_llm) so HTTP request timeouts do not interfere with
        # the long-lived Live WebSocket connection.
        voice_llm = Gemini(model=get_voice_model())
        agent = VoiceCoordinatorProfile(
            model=voice_llm,
            toolkit=self._toolkit,
            specialists=self._specialists,
        ).build()
        for sub in agent.sub_agents:
            sub.on_model_error_callback = self._on_model_error
        return agent

    def start_voice_session(self, audio_device=None, on_text=None, echo_guard=True):
        """Create and return a VoiceSession bound to this app's workspace and specialists."""
        from buddyai.voice import SoundDeviceAudio, VoiceSession

        device = audio_device if audio_device is not None else SoundDeviceAudio()
        # One voice session counts as one request for the untrusted-content guard.
        self._toolkit.begin_request()
        return VoiceSession(
            self.build_voice_agent(),
            device,
            on_text=on_text,
            echo_guard=echo_guard,
        )

    def transcribe_voice(
        self,
        audio_device=None,
        on_update=None,
        wait_for_stop=None,
        live_client=None,
    ):
        """Stream speech live to Gemini Live Transcribe on the shared loop and return text."""
        from buddyai.voice import SoundDeviceAudio, VoiceTranscriber

        device = audio_device if audio_device is not None else SoundDeviceAudio()
        transcriber = VoiceTranscriber(live_client=live_client)
        loop = self._get_event_loop()
        task = loop.create_task(
            transcriber.stream_and_transcribe_async(
                device, on_update=on_update, wait_for_stop=wait_for_stop
            )
        )
        try:
            return loop.run_until_complete(task)
        except KeyboardInterrupt:
            task.cancel()
            try:
                loop.run_until_complete(task)
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            raise

    def run_voice(self, session):
        """Run a VoiceSession on BuddyApp's shared event loop until stopped or Ctrl+C."""
        # Share the event loop with ask() so the text model's async HTTP client stays
        # valid when the user returns to the text chat after voice mode ends.
        loop = self._get_event_loop()
        task = loop.create_task(session.run())
        try:
            loop.run_until_complete(task)
        except KeyboardInterrupt:
            session.stop()
            task.cancel()
            try:
                loop.run_until_complete(task)
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass

    def close(self):
        """Close the internal asyncio event loop if one was created."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
