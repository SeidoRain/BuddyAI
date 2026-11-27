# Product Backlog and User Stories

Status values: **Done** (built and tested) and **Dropped** (removed from the project). Status is as of 2026-11-27.

## Backlog

| ID | Story | Priority | Sprint | Status |
|---|---|---|---|---|
| [US-01](#us-01-add-a-task-in-a-normal-sentence) | Add a task by typing a normal sentence | High | 1 | Done |
| [US-02](#us-02-see-tasks-in-order-of-urgency) | See my tasks in order of urgency | High | 1 | Done |
| [US-03](#us-03-schedule-a-meeting-and-be-warned-about-conflicts) | Schedule a meeting and be warned about conflicts | High | 1 | Done |
| [US-04](#us-04-get-key-points-and-action-items-from-a-file) | Get key points and action items from a PDF, photo or Word file | Medium | 1 | Done |
| [US-05](#us-05-keep-my-data-between-sessions) | Keep my data between sessions | High | 1 | Done |
| [US-06](#us-06-handle-errors-with-custom-exceptions) | Handle errors through custom exceptions | High | 1 | Done |
| [US-07](#us-07-include-the-events-in-my-calendar-file) | Include the events in my calendar file | High | 2 | Done |
| [US-08](#us-08-scan-recent-emails-for-requests) | Scan my recent emails for requests | Medium | 2 | Dropped |
| [US-09](#us-09-daily-briefing) | Daily briefing | High | 1 | Done |
| [US-10](#us-10-talk-to-buddyai-by-voice) | Talk to BuddyAI by voice | Medium | 2 | Done |
| [US-11](#us-11-ask-about-a-drive-file-or-google-doc) | Ask about a Drive file or Google Doc | Low | Stretch | Dropped |
| [US-12](#us-12-suggested-tasks-wait-for-my-approval) | Suggested tasks wait for my approval | High | 1 | Done |
| [US-13](#us-13-keep-working-when-a-gemini-model-runs-out-of-free-requests) | Keep working when a Gemini model runs out of free requests | High | 1 | Done |
| [US-14](#us-14-add-a-task-or-meeting-with-a-typed-command) | Add a task or meeting with a typed command | Medium | 2 | Done |
| [US-15](#us-15-instant-views-of-my-day) | Instant views of my day | Low | 2 | Done |
| [US-16](#us-16-change-or-remove-anything-i-added) | Change or remove anything I added | High | 2 | Done |
| [US-17](#us-17-ask-about-the-weather-and-current-news) | Ask about the weather and current news | Medium | 2 | Done |

## Stories

### US-01: Add a task in a normal sentence

As a user, I want to add a task by typing a normal sentence so that I do not fill in forms.

- The task agent extracts the title, due date and priority from the sentence and calls `add_task`. It is told to turn words such as "tomorrow" or "Friday" into an ISO date using the current date.
- `BuddyToolkit.add_task` creates a `Task` and saves it to `tasks.json` (`tests/test_toolkit.py`).
- A due date in the past raises `InvalidDueDateError`. The toolkit returns it as an error result and the task agent is told to explain it and suggest the next step (`tests/test_managers.py`, `tests/test_toolkit.py`).

### US-02: See tasks in order of urgency

As a user, I want to see my tasks in order of urgency so that I know what to do first.

- Open tasks are sorted by `priority_score()` (priority times 10, plus a bonus for a deadline that is overdue, today or within three days), then by due date and title (`tests/test_models.py`, `tests/test_managers.py`).
- `list_tasks` flags each overdue task with `overdue: true` and returns its score.

### US-03: Schedule a meeting and be warned about conflicts

As a user, I want to schedule a meeting and be warned about conflicts so that I am not double-booked.

- A meeting that overlaps another raises `SchedulingConflictError` and is not saved (`tests/test_managers.py`, `tests/test_cli_commands.py`).
- The error message names the conflicting meeting and its times and gives the next free start time. The schedule agent is told to state the conflicts and offer that slot (`tests/test_sprint1_fixes.py` checks the suggestion is never in the past).
- A meeting can be moved (`reschedule_meeting`), renamed or given a location (`update_meeting`, see US-16) and cancelled (`cancel_meeting`). A move that would conflict leaves the meeting unchanged.

### US-04: Get key points and action items from a file

As a user, I want to give BuddyAI a PDF, photo or Word file and get its key points and action items so that I do not have to read the whole file to find what I must do.

- PDF, PNG, JPG, TXT and Word (`.docx`) files are accepted. Any other type, including the old `.doc` format, raises `UnsupportedFileTypeError` before any model request (`tests/test_document_reader.py`).
- Gemini does not read `.docx` files, so `DocumentReader` unpacks the file with the standard library, reads `word/document.xml` and sends the paragraph text as plain text, one line per paragraph. A file that is not a readable Word file (also a damaged or encrypted one), a document with a DTD and a document with no text are refused with `InvalidInputError` before any model request (`TestDocxReading` in `tests/test_document_reader.py`). A document body over 20 MB is refused the same way; this limit is enforced in `DocumentReader._extract_docx_text` but is not covered by a test. An empty file of any type is refused before any model request too (`tests/test_document_reader.py`).
- In the terminal chat a file is attached by writing `@path` inside an ordinary message, for example `Summarize @notes.txt and list the action items`; a path with spaces goes in double quotes. `CommandRouter.send` checks each file with `BuddyApp.check_file(path)` before any model request, so a missing file shows `InvalidInputError` and an unsupported type shows `UnsupportedFileTypeError`, and no request is made. A word after `@` counts as a file only when it is quoted, ends in a supported file type, contains a folder separator or names a file that exists. A message that is only a mention asks for a summary, and `ana@example.com`, `@Ana` or `@ana.cruz` stay ordinary text (`tests/test_cli_commands.py`, `tests/test_cli_ui.py`, `tests/test_profiles_and_app.py`).
- The summary and key points are saved as a note. The action items are held as proposals and are saved as tasks only after confirmation (`tests/test_document_reader.py`; see US-12).
- Reading a file marks the request as having read untrusted text, so nothing can be deleted or cancelled in that request (`tests/test_untrusted_content_guard.py`).

### US-05: Keep my data between sessions

As a user, I want my data kept between sessions so that nothing is lost when BuddyAI restarts.

- Tasks, meetings, reminders and notes are written to JSON files after each change and loaded again when BuddyAI starts.
- Items reload with the same values, including overdue tasks (`tests/test_models.py`, `tests/test_managers.py`).
- Each file is written to a temporary file and then moved into place, so a failed save does not leave a half-written file (`tests/test_storage_and_workspace.py`).

### US-06: Handle errors with custom exceptions

As a developer, I want errors handled through custom exceptions so that BuddyAI never crashes mid-conversation.

- Every `BuddyToolkit` method catches errors and returns a result with `status`, `error_type` and a readable `message`. An error that is not a `BuddyError` gets a generic message and is written to the log (`tests/test_toolkit.py`).
- The custom exceptions in `buddyai/exceptions.py` all extend `BuddyError`, and each one is used in at least one unit test.
- The terminal chat shows the exception's class name for the typed commands (`tests/test_cli_commands.py`).

### US-07: Include the events in my calendar file

As a user, I want the events in my calendar file included so that conflict checks see my whole schedule.

- `IcsCalendarSource` (`buddyai/sources/ics_calendar_source.py`) reads a local `.ics` file as read-only `Meeting` objects with `source="calendar_file"`, supporting UTC, IANA `TZID`, and floating times, line unfolding, and text escapes (`tests/test_ics_calendar_source.py`).
- Imported meetings are loaded via `BUDDYAI_ICS_FILE` or `/calendar <path>`, appear in `list_events` and the daily briefing (tagged `[calendar file]`), block conflicting new meetings and free slots, and are never written to `meetings.json` (`tests/test_calendar_integration.py`, `tests/test_calendar_command.py`).
- Attempting to move or cancel an imported meeting raises `ReadOnlySourceError` (`tests/test_calendar_integration.py`).

### US-08: Scan recent emails for requests

As a user, I want my recent emails scanned for requests so that I do not miss a deadline.

Dropped. This was a read-only Gmail story. Google services were removed from the project scope on 2026-11-26.

### US-09: Daily briefing

As a user, I want a daily briefing so that I start the day knowing what is ahead.

- `BriefingService` gathers today's meetings, tasks that are due today or overdue, and reminders that occur today into one `DailyBriefing`, highest score first (`tests/test_toolkit.py`).
- A reminder scheduled for today stays in the briefing after its time has passed and is marked `[time has passed]`. This was fixed in Sprint 2 (`tests/test_models.py`, `tests/test_storage_and_workspace.py`).
- The briefing also has a weather section for a chosen time and place (`BUDDYAI_LOCATION`, `Manila` by default) and the top five Philippine headlines with links. Both are fetched from the internet by `WebLookup` (`tests/test_web_lookup.py`, `tests/test_cli_commands.py`). Without internet, each section shows `Unavailable (...)` and the schedule part still works.
- The briefing is available through the chat and through `/brief`, which makes no model request.

### US-10: Talk to BuddyAI by voice

As a user, I want to talk to BuddyAI by voice so that I can use it hands-free.

- `/live` starts a `VoiceSession` (`buddyai/voice/voice_session.py`) over ADK `Runner.run_live` using `VoiceCoordinatorProfile` and a Gemini Live model (`gemini-3.8-live` by default), delegating requests to the same four specialists and `Workspace` (`tests/test_voice_session.py`).
- `AudioDevice` and `SoundDeviceAudio` (`buddyai/voice/audio_device.py`) stream 16 kHz microphone input and 24 kHz speaker output in thread-safe 40 ms slices, raising `VoiceUnavailableError` cleanly if `sounddevice` or hardware is missing (`tests/test_voice_audio_device.py`).
- `/live` enables speaker-safe mic gating by default (Space/Enter to interrupt playback) and `/live barge` enables full-duplex voice barge-in with headphones; saying `"stop"` or pressing Ctrl+C returns cleanly to text chat (`tests/test_voice_session.py`).
- `/voice` (`VoiceTranscriber` in `buddyai/voice/transcriber.py`) streams speech live to a fixed transcription model (`gemini-3.5-transcribe-live`) and pre-fills the transcribed text directly into the regular chat prompt for review/editing before sending (`tests/test_voice_session.py`).

### US-11: Ask about a Drive file or Google Doc

As a user, I want to ask about a Drive file or Google Doc so that I do not have to open and read it myself.

Dropped. This was a read-only Google Drive story. Google services were removed from the project scope on 2026-11-26.

### US-12: Suggested tasks wait for my approval

As a user, I want suggested tasks to wait for my approval so that nothing is added without my say.

- Tasks suggested from a file are stored with the status `proposed` and stay out of the open task list (`tests/test_managers.py`, `tests/test_document_reader.py`).
- `confirm_tasks` turns the chosen proposals into open tasks. It is all-or-nothing: if one ID is wrong or already open, none are confirmed (`tests/test_sprint1_fixes.py`).
- The coordinator agent is told to ask the user first and to confirm only the IDs the user names.
- Reading a file cannot lead to a deletion: after `summarize_document`, `delete_task`, `delete_reminder`, `cancel_meeting` and `delete_note` refuse with `UnsafeDeletionError` for the rest of that request (`tests/test_untrusted_content_guard.py`; see US-16).

### US-13: Keep working when a Gemini model runs out of free requests

As a user, I want BuddyAI to keep working when a Gemini model runs out of free requests so that a limit does not stop my work.

- `ModelCatalog` holds an ordered list of models.
- When the current model is used up, rate-limited, not responding or not available for the API key, BuddyAI moves to the best usable model (the first in the list that still works), answers the same message and says so (`tests/test_model_switching.py`, `tests/test_uploads_and_failover.py`). A busy or per-minute mark lasts until the next message.
- `/model` switches by hand, by number, by name or with `next`.
- A daily limit is remembered in `data/model_limits.json` until Google's reset (`tests/test_model_limits.py`).

### US-14: Add a task or meeting with a typed command

As a user, I want to add a task or meeting with a typed command so that I can still work when the AI model is unavailable.

- These commands call the same `BuddyToolkit` methods as the agents, with no model request (`tests/test_cli_commands.py`):
  - `/task add <title> | <due> | <priority>`
  - `/task edit <task> | <title> | <due> | <priority>` (an empty field keeps the old value)
  - `/task delete <task>`
  - `/meet add <title> | <start> | <end>`
  - `/meet move <meeting> | <start> | <end>`
  - `/meet edit <meeting> | <title> | <location>` (an empty field keeps the old value)
  - `/meet cancel <meeting>`
  - `/task done <task id or title>`
- Invalid input shows the exception's class name and message, for example `InvalidDueDateError` or `SchedulingConflictError`, and nothing is saved. Missing parts print the usage lines.
- A mistyped `/command` gets a warning and is not sent to the model. When it is close to a real command, the warning suggests it, for example "Unknown command /tsk. Did you mean /task? Type /help to see the commands." (`tests/test_cli_commands.py`).
- `/help` lists the commands in groups: Session (`/help`, `/status`, `/clear`, `/model`, `/quit`), Your day (`/brief`, `/tasks`), Change data (no AI) (`/task`, `/meet`) and Input (`@path`, `/calendar`, `/live`, `/voice`), then says that anything else can be asked in plain language. The older names `/done`, `/file`, `/models` and `/exit` still work but are not listed and are not offered by autocomplete (`tests/test_cli_commands.py`, `tests/test_cli_ui.py`).
- Reminders and notes have no typed commands; they are changed through the chat.

### US-15: Instant views of my day

As a user, I want instant views of my day so that checking my list does not cost a model request.

- `/tasks` and `/status` read local data and print it without calling the model (`tests/test_cli_ui.py`, `tests/test_cli_commands.py`).
- `/brief [today|tomorrow|HH:MM|YYYY-MM-DD [HH:MM]] [| location]` makes no model request, but it does fetch the weather and the top five headlines from the internet (see US-09 and US-17). Without internet those two sections show `Unavailable (...)` (`tests/test_cli_commands.py`).

### US-16: Change or remove anything I added

As a user, I want to change or remove the tasks, meetings, reminders and notes I added so that my lists stay correct.

- Meetings can be renamed or given a location with `BuddyToolkit.update_meeting(meeting, title="", location="")`. `Agenda.update_meeting` checks everything before it changes anything, so a bad title leaves the location unchanged. A meeting from a calendar file is refused with `ReadOnlySourceError`. An empty field means unchanged, so a location cannot be cleared this way (`tests/test_edit_and_delete.py`).
- Reminders can be listed and deleted with `list_reminders` and `delete_reminder` (ID or title). Notes can be deleted with `delete_note` (ID or title); tasks proposed from that note stay. `TaskManager.find_reminder` and `Notebook.find_note` find an item by exact ID, then by exact or partial title, and an unclear title raises `AmbiguousItemError`. An unknown one raises `ReminderNotFoundError` or `NoteNotFoundError` (`tests/test_edit_and_delete.py`).
- A completed task can be found by title when it is updated or deleted (`TaskManager.find_task(..., include_done=True)`), and an exact title wins over part of a title. `complete_task` still looks for a title among tasks that are not done yet, and a task that is already done is refused. Deleting a task also removes it from the note it was proposed from (`tests/test_edit_and_delete.py`).
- Tasks and meetings also have typed commands (`/task edit`, `/task delete`, `/meet move`, `/meet edit`, `/meet cancel`; see US-14) (`tests/test_cli_commands.py`).
- Every agent's instruction contains one honesty rule (`AgentProfile._honesty_rule()`): report a change as done only when a tool returned success for that exact change, and say BuddyAI cannot do it when no tool can. A live test on 2026-11-27 showed a model saying it had renamed a meeting when no tool existed. `tests/test_edit_and_delete.py` checks that every profile contains the rule. The rule is an instruction to the model, not a check in code.
- After a request has read a file, web results or headlines, `delete_task`, `delete_reminder`, `cancel_meeting` and `delete_note` refuse with `UnsafeDeletionError` for the rest of that request. Adding and editing still work, and the user sends the deletion as its own message (`tests/test_untrusted_content_guard.py`).
- Reminders and notes cannot be edited, only added and deleted.

### US-17: Ask about the weather and current news

As a user, I want to ask about the weather and current news so that I do not have to leave BuddyAI to look them up.

- The coordinator agent has two tools, `get_weather` and `search_web`, which call `WebLookup` (`buddyai/web_lookup.py`). It uses free public services that need no key (Open-Meteo for weather, Google News RSS and Wikipedia for search) and the standard library only (`tests/test_web_lookup.py`).
- Lookups need an internet connection. If a service cannot be reached, the tool returns an error result with a readable message and the chat does not crash.
- The daily briefing uses the same lookup for its weather section (a time within the 7-day forecast, at a place) and its five Philippine headlines (see US-09).
- `search_web` marks the request as having read untrusted text, so no deletion can follow in that request (see US-16).
