# BuddyAI

## Project Description

BuddyAI is an AI executive assistant written in Python with Google ADK and Gemini. You talk to it in plain language. It keeps your tasks, meetings, reminders, notes and file summaries, saves them to JSON files, and gives you a daily briefing.

It is the semester capstone project of IT121AL (Computer Programming 2, object-oriented programming). A coordinator agent and four specialist agents (tasks, schedule, notes, briefing) call tools on one class, `BuddyToolkit`. The toolkit works on plain Python domain classes: `Task`, `Meeting`, `Reminder` and `Note` extend one abstract base class, `WorkItem`, and are managed by `TaskManager`, `Agenda` and `Notebook`. The terminal chat is the graded interface.

More documentation:

- [Technical documentation](docs/submission/BuddyAI_Technical_Documentation_v2.pdf)
- [Project proposal](docs/submission/IT121AL_Project_Proposal_BuddyAI_v3.docx)
- [Product backlog and user stories](docs/BACKLOG.md)
- [UML diagrams](docs/uml/)
- [AI usage log](docs/AI_USAGE.md)

## Features

Everything in this list works in the current version.

- **Tasks.** Add, update, complete and delete tasks with a due date and a priority. Tasks are ranked by urgency, and overdue tasks are flagged. A due date in the past is refused (`InvalidDueDateError`). A completed task can still be renamed or deleted by its title; completing a task by title looks at open tasks only.
- **Schedule.** Schedule, move, rename, change the location of, and cancel meetings. A meeting that overlaps another is refused (`SchedulingConflictError`) and the reply gives the nearest free start time. BuddyAI can also find a free slot for a given length of time.
- **Calendar file.** Load a read-only iCalendar (`.ics`) file with `/calendar <path>` or `BUDDYAI_ICS_FILE`. Imported meetings appear in the schedule and daily briefing (tagged `[calendar file]`), block conflicting new meetings, are never written to `meetings.json`, and cannot be moved, renamed or cancelled (`ReadOnlySourceError`).
- **BuddyAI Live & Voice-to-Text.** Use `/live` for two-way spoken conversation over ADK live streaming (`gemini-3.8-live`, speaker-safe echo guard by default, Space/Enter to interrupt, or `/live barge` for full-duplex headphones), and `/voice` to stream live speech-to-text word-by-word directly into the regular text chat prompt so you can review or edit before sending to whichever text model you chose. `/voice` always uses the fixed Live model `gemini-3.5-transcribe-live`; `/model` does not change it. `/live` shares the same coordinator, specialists, tools and workspace data as the text chat.
- **Weather and web lookup.** Ask for current weather or recent news and facts in the text chat or in `/live`. The coordinator agent has two tools, `get_weather` and `search_web`, which call `WebLookup` (`buddyai/web_lookup.py`). `WebLookup` uses free public services that need no key (Open-Meteo for weather, Google News RSS and Wikipedia for search) and the Python standard library only. It needs an internet connection.
- **Reminders.** One-off, daily and weekly reminders can be added, listed and deleted. A reminder scheduled for today stays in today's briefing even after its time has passed, marked `[time has passed]`.
- **Notes and file summaries.** Save, search and delete notes. Give BuddyAI a PDF, PNG, JPG, TXT or Word (`.docx`) file and it saves a summary as a note. In the terminal chat you attach a file by writing `@path` in a message, and the file is checked before any model request. Deleting a note does not delete the tasks that were proposed from it.
- **Proposals with confirmation.** Tasks suggested from a file are kept as proposals. They become tasks only after you say which ones to keep, and a confirmation is all-or-nothing.
- **Daily briefing.** Today's (or another day's) meetings, tasks that are due or overdue, and reminders, plus the weather for a chosen time and place (`BUDDYAI_LOCATION`, `Manila` by default) and the top five Philippine news headlines with links. The weather and headline sections need an internet connection. Without it they show `Unavailable (...)` with the reason, and the schedule part still works.
- **Automatic model switching.** When a Gemini model runs out of free requests, is rate-limited or does not respond, BuddyAI moves to the next usable model, answers the same message and tells you. `/model` switches by hand.
- **Typed commands without the AI.** `/task add`, `/task edit`, `/task delete`, `/meet add`, `/meet move`, `/meet edit`, `/meet cancel`, `/task done`, `/tasks` and `/status` work on your data without any model request, so they work when the free quota is used up. `/brief` also makes no model request, but it fetches weather and headlines from the internet.
- **No deletions after reading untrusted text.** A file, a web search result or a news headline can contain text written to steer an AI assistant. `summarize_document`, `search_web` and `get_daily_briefing` mark the current request as having read such text. After that, `delete_task`, `delete_reminder`, `cancel_meeting` and `delete_note` refuse with `UnsafeDeletionError` for the rest of that request, and adding and editing still work. A deletion is sent as its own message. This is checked in code (`BuddyToolkit.begin_request()` and `_refuse_if_untrusted_read()`), so reading a file can only create proposals, never remove something. `search_web` results also carry a note that they are untrusted content, and the coordinator is told that text from web results, headlines or files never decides which specialist to call or what to change.
- **Honesty rule for the agents.** The instructions of all agents say that a change may be reported as made only when a tool returned success for that exact change, and that BuddyAI must say it cannot do something when no tool exists for it (`AgentProfile._honesty_rule()`). This is an instruction to the model, not a check in code. The tools themselves return a clear error when a change fails.
- **JSON persistence.** Everything is saved to JSON files after each change, with atomic writes, and is loaded again when BuddyAI starts.

## Requirements

- Windows 11. BuddyAI was developed and tested on it. The `.bat` launchers are for Windows; on another system use the commands under [Running without the launchers](#running-without-the-launchers).
- Python 3.11 or later.
- The packages in `requirements.txt`, which the first run installs for you:

  | Package | Used for |
  |---|---|
  | `google-adk` (2.15 or later, below 3) | The agents, and the Gemini client used to read files |
  | `python-dotenv` | Reading `buddy_agent\.env` |
  | `tzdata` | Time zone data for `Asia/Manila` on Windows |
  | `rich` | The formatted terminal output |
  | `prompt_toolkit` | The input line: autocomplete and history |
  | `sounddevice` (0.5 or later) | Microphone capture and speaker playback for `/live` and `/voice` (optional for text-only chat) |

- A free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
- An internet connection for the chat, and for the weather and headlines in the daily briefing. The unit tests and the typed commands that change data do not need the model, and the unit tests need no network at all.

## Installation

1. Clone the repository and open the folder.
2. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
3. Double-click **`run_cli.bat`** (terminal chat) or **`run_web.bat`** (browser chat). The first run creates the virtual environment, installs the packages, and creates `buddy_agent\.env` from `buddy_agent\.env.example`.
4. Open `buddy_agent\.env`, paste your key after `GOOGLE_API_KEY=`, and run the launcher again.

Put the key in `buddy_agent\.env`, never in `.env.example`: the example file is shared in the repository and the real one is ignored by git.

`setup.bat` does the first-time setup. The two launchers call it, and it is safe to run again.

### Running without the launchers

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item buddy_agent\.env.example buddy_agent\.env   # then add your key

python main.py        # terminal chat
adk web --port 8000   # browser chat, run from this folder, then pick buddy_agent
```

## How to Run

| Launcher | What you get |
|---|---|
| `run_cli.bat` | The terminal chat. This is the graded demo. |
| `run_web.bat` | ADK's browser chat at `http://127.0.0.1:8000`. It opens the page for you and shows which agent and tool handled each message. Keep the window open; press Ctrl+C in it to stop. |

Run only one of them at a time. Each keeps its own copy of the data in memory, so two running together overwrite each other's saves.

In the terminal chat, type `/quit` to leave. The browser chat is a development view: it understands `/model` but not the other commands in the table below.

## How to Use

Things to try in the chat:

- `Add a high priority task to submit the thesis draft by Friday.`
- `What should I do first?`
- `Schedule a thesis meeting tomorrow from 2pm to 3pm.`
- `Move my thesis meeting to a free slot tomorrow afternoon and remind me to bring the draft.`
- `Give me my briefing for tomorrow.`
- `Rename my thesis meeting to Thesis defense and set the location to Room 204.`
- `Delete the reminder to bring the draft.`
- `What is the weather in Cebu this afternoon?`
- `Summarize @sample_data\sample_meeting_notes.txt and list the action items` (the `@path` attaches a file; see [Giving BuddyAI a file](#giving-buddyai-a-file))

Terminal commands. Type `/` for autocomplete, `↑`/`↓` for history, and `Tab` after `@` or after `/calendar ` for path completion. `/help` lists the commands in four groups: Session, Your day, Change data (no AI) and Input. Anything that is not a command is sent to BuddyAI as plain language. The dim line under the prompt shows the current model, and for 30 seconds after a model switch it also says which model BuddyAI switched from.

| Command | What it does |
|---|---|
| `/task add <title> \| <due> \| <priority>` | Adds a task with no model request. `<due>` and `<priority>` are optional. Priority is `low`, `medium` (the default) or `high`. |
| `/task edit <task> \| <title> \| <due> \| <priority>` | Changes a task with no model request. `<task>` is an ID or a title (a completed task can be found by title too). Leave a field empty to keep it, for example `/task edit Demo task \|\| 2026-12-05 \|`. At least one field must have a value. |
| `/task delete <task>` | Deletes a task, even a completed one, with no model request. |
| `/task done <task id or title>` | Marks a task done with no model request. Part of a title is enough if it matches one open task. |
| `/meet add <title> \| <start> \| <end>` | Schedules a meeting with no model request. All three parts are required. A conflict is refused and the nearest free start is shown. |
| `/meet move <meeting> \| <start> \| <end>` | Moves a meeting to a new time with no model request. All three parts are required. A conflict is refused and the meeting stays where it was. |
| `/meet edit <meeting> \| <title> \| <location>` | Renames a meeting or sets its location with no model request. Leave a field empty to keep it. At least one field must have a value. |
| `/meet cancel <meeting>` | Cancels a meeting with no model request. |
| `@path` inside a message | Attaches a PDF, PNG, JPG, TXT or Word (`.docx`) file to an ordinary message, for example `Summarize @notes.txt and list the action items`. A path with spaces goes in double quotes: `@"C:\Users\Juan Cruz\brief.pdf"`. See [Giving BuddyAI a file](#giving-buddyai-a-file). |
| `/calendar [path \| off]` | Loads a read-only `.ics` calendar file, shows the currently loaded file and counts, or unloads it with `off`. |
| `/live [barge]` | Starts BuddyAI Live two-way spoken conversation (speaker-safe by default; press Space/Enter to interrupt, or `/live barge` with headphones). |
| `/voice` | Dictates speech into the regular text prompt (voice-to-text) so you can edit and press Enter to send. |
| `/model` | Opens the interactive model picker (or lists models in piped mode). Also works in the browser chat. |
| `/model 2`, `/model lite`, `/model next` | Switches model by number, by name or part of a name, or to the next one in the list. Also works in the browser chat. |
| `/brief [today\|tomorrow\|HH:MM\|YYYY-MM-DD [HH:MM]] [\| location]` | Prints the daily briefing with no model request: the schedule, the weather and the top five Philippine headlines. The weather and headlines are fetched from the internet. `/brief` alone is for now, `/brief tomorrow 15:00 \| Cebu` is for tomorrow at 3 PM in Cebu, and `/brief Cebu` is for now in Cebu. The weather forecast covers 7 days. |
| `/tasks` | Shows open tasks and pending proposals in a formatted table. |
| `/status` | Shows active model, timezone, and workspace item counts. |
| `/clear` | Clears the screen and re-renders the compact header. |
| `/help` | Lists the commands in groups, then reminds you that anything else can be asked in plain language. |
| `/quit` | Exits. |

Dates in `/task add`, `/task edit`, `/meet add` and `/meet move` are written `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM` or `YYYY-MM-DD HH:MM`. A task due date with no time means 23:59 on that day. A meeting needs a date and a time for both start and end. Words such as "tomorrow" are understood in the chat but not in these commands (only `/brief` accepts `today` and `tomorrow`). Times use the time zone in `BUDDYAI_TIMEZONE` (`Asia/Manila` by default).

The `/task` and `/meet` commands print a green line when they work and a red line with the error's class name when they do not, and a refused command saves nothing. Typing `/task` or `/meet` with no valid sub-command, or with missing parts, prints the usage lines. A first word that looks like a command but is not one gets a warning and is not sent to the model. When it is close to a real command, the warning suggests it: `/tsk` gives "Unknown command /tsk. Did you mean /task? Type /help to see the commands."

Four older names still work, but `/help` and autocomplete do not list them: `/done <task>` (the same as `/task done`), `/file <path> [message]` (the same as writing `@path`), `/models` (the same as `/model`) and `/exit` (the same as `/quit`).

### Changing and removing things

Tasks, meetings, reminders and notes can be removed through the chat, and tasks and meetings can also be changed there. Some of these have typed commands too:

| Item | Through the chat | Typed command |
|---|---|---|
| Task | update (title, due date, priority), complete, delete | `/task edit`, `/task delete`, `/task done` |
| Meeting | move, rename, change the location, cancel | `/meet move`, `/meet edit`, `/meet cancel` |
| Reminder | add, list, delete | none |
| Note | add, search, delete | none |

A deletion or cancellation is refused with `UnsafeDeletionError` in a chat request that already read a file, searched the web or built a briefing; send it as its own message or use a typed command (see Features). Reminders and notes have no typed commands, and they cannot be edited, so changing one means deleting it and adding it again. Every item is found by ID or by title; part of a title is enough when it matches one item, and BuddyAI reports an ambiguous title (`AmbiguousItemError`) instead of guessing. Meetings that come from a calendar file cannot be changed (`ReadOnlySourceError`).

### Demo without the AI model

These commands change your data and make no model request, so they work even when the free quota is used up. BuddyAI still needs `GOOGLE_API_KEY` to be set so that it starts. Use dates in the future when you try this; the dates below are examples.

```
You> /task add Demo task | 2026-12-01 | high
✓ Added task: Demo task (id: task-960a72fe)
You> /task add Demo task | 2020-01-01 | high
✕ InvalidDueDateError: Due date 2020-01-01 23:59 is in the past.
You> /meet add Standup | 2026-11-30 14:00 | 2026-11-30 15:00
✓ Scheduled meeting: Standup (id: mtg-6c5512cc)
You> /meet add Clash | 2026-11-30 14:30 | 2026-11-30 15:30
✕ SchedulingConflictError: Meeting 'Clash' conflicts with 'Standup' (2026-11-30 14:00-15:00). Next free slot starts at 2026-11-30 15:00.
Suggested free start: 2026-11-30 15:00
```

The task ID and meeting ID are different on every run. Now type `/quit`, start BuddyAI again and check that the data was saved:

```
You> /tasks
(a table that lists "Demo task")
You> /meet add Clash | 2026-11-30 14:30 | 2026-11-30 15:30
✕ SchedulingConflictError: Meeting 'Clash' conflicts with 'Standup' (2026-11-30 14:00-15:00). Next free slot starts at 2026-11-30 15:00.
Suggested free start: 2026-11-30 15:00
You> /task done Demo task
✓ Completed task: Demo task (id: task-960a72fe)
```

The same conflict after the restart shows that the Standup meeting was loaded from `data\meetings.json`.

### Sample data

The `sample_data/` folder contains a generator script (`make_sample_data.py`), a committed read-only snapshot (`sample_data/example/`), and a short self-written meeting notes file (`sample_data/sample_meeting_notes.txt`) for testing file attachments with `@path`.

To generate fresh sample data around today's date and start BuddyAI on it (in PowerShell, only for the current shell):

```powershell
.\.venv\Scripts\python.exe sample_data\make_sample_data.py
$env:BUDDYAI_DATA_DIR = "sample_data\generated"
.\.venv\Scripts\python.exe main.py
```

`sample_data/example/` is a fixed-date snapshot for reading the file format only; do not point `BUDDYAI_DATA_DIR` at it because BuddyAI writes back to the data folder on every change.

To test document summarization without an external PDF, type `Summarize @sample_data\sample_meeting_notes.txt and list the action items` inside the terminal chat. This needs the model, so it is not part of the demo without the AI model.

### Calendar file

BuddyAI can read events from a local iCalendar (`.ics`) file as read-only meetings. Export an `.ics` file from your calendar app (for example, Google Calendar Settings -> Import & export -> Export, or Apple Calendar File -> Export), then load it either temporarily or at startup:

- **For the current session:** `/calendar C:\path\to\calendar.ics` (quotes are supported if the path has spaces; `Tab` completes paths after `/calendar `; `/calendar` shows what is loaded; `/calendar off` unloads it).
- **At every startup:** set `BUDDYAI_ICS_FILE` in `buddy_agent\.env` (relative paths resolve from the project folder).

With the generated sample data, try this flow:

```
You> /calendar sample_data\generated\sample_calendar.ics
✓ ...sample_calendar.ics: 5 events loaded (1 recurring, first occurrence only), 1 all-day events skipped, 1 skipped as unreadable
You> Schedule a call tomorrow from 10:30 to 11:30
(refused with SchedulingConflictError naming "Department meeting")
You> Move the Department meeting to 2pm
(refused with ReadOnlySourceError because calendar-file meetings are read-only)
```

Supported subset and rules:

- Reads `VEVENT` blocks inside `VCALENDAR`, ignoring `VTIMEZONE`, `VALARM`, `VTODO` and `VJOURNAL`.
- Supports UTC (`...Z`), IANA `TZID`, and floating date-times, folded lines, and escaped text in `SUMMARY` and `LOCATION`.
- Imported meetings are read-only (`ReadOnlySourceError` on move, rename or cancel) and are never saved to `data\meetings.json`.
- Limitations: recurring rules (`RRULE`) load only the event's first occurrence (no expansion); all-day (`VALUE=DATE`) events are skipped; `DURATION` without `DTEND` is not parsed; Windows timezone names not in IANA `zoneinfo` are skipped; `STATUS:CANCELLED` events are not filtered out; the file is read when loaded, so run `/calendar <path>` again after updating it.

### Voice modes: BuddyAI Live (`/live`) and Voice-to-Text (`/voice`)

BuddyAI supports two distinct voice workflows, both sharing the same workspace data and `AudioDevice` layer:

- **`/live` (BuddyAI Live — two-way spoken conversation):** streams microphone audio (16 kHz mono PCM) to a Gemini Live model (`gemini-3.8-live` by default) and plays spoken replies (24 kHz mono PCM) while delegating tasks, meetings, notes and briefings to the same four specialist agents.
  - **Speaker-safe by default:** mutes microphone upload while BuddyAI is speaking (plus a brief echo tail) so laptop speakers do not cut BuddyAI off. Press **Space** or **Enter** at any time to interrupt BuddyAI mid-reply and start talking.
  - **Full-duplex headphones mode (`/live barge`):** leaves the microphone open continuously so you can talk over BuddyAI hands-free while wearing headphones.
  - **Stopping:** say `"stop"` or `"stop live"`, or press **Ctrl+C**, to return cleanly to the text chat with all created items intact.
- **`/voice` (Real-time Voice-to-Text dictation in regular chat):** streams your microphone live to the Live model `gemini-3.5-transcribe-live` (`SMART` mode) so you see words form in real time as you speak; press **Enter** to drop the finalized text straight into the regular editable prompt (or `Esc`/`Ctrl+C` to cancel). When you press Enter again, the text is sent to whichever text model is active (replies in text only, keeping the same text conversation history). The dictation model itself is fixed in `VoiceTranscriber`: neither `/model` nor `BUDDYAI_VOICE_MODEL` changes it.
- **Existing environments:** if your `.venv` was created earlier, run `pip install -r requirements.txt` once to install `sounddevice` (if missing or no audio device is available, `/live` and `/voice` show `VoiceUnavailableError` and the text chat keeps working).
- **Model override:** set `BUDDYAI_VOICE_MODEL` in `buddy_agent\.env` for `/live` (for example `gemini-3.1-flash-live-preview`). `/model` changes the text model used by the text chat and the specialists (also the specialists that `/live` calls), not the `/live` model and not the `/voice` dictation model.
- **Limits:** both modes require internet and a Gemini API key (`/live` requires a Live-capable key); each spoken request in `/live` that calls a specialist still spends text-model requests; `/live` conversation memory is separate from the text chat session, while text dictated with `/voice` is sent in the text chat session.

### Giving BuddyAI a file

Three ways:

- Terminal: write `@path` inside an ordinary message, for example `Summarize @sample_data\sample_meeting_notes.txt and list the action items`. A path with spaces goes in double quotes: `@"C:\Users\Juan Cruz\brief.pdf"`. `Tab` completes the path after `@`.
- Either chat: type the path in a message, for example `C:\path\to\brief.pdf summarize`.
- Browser chat: attach it with the **+** button and say what you want. BuddyAI saves a copy in `data\uploads` and reads it from there.

All three produce the same summary and task proposals. A file of any other type is refused with `UnsupportedFileTypeError`, including the old Word format `.doc` (only `.docx` is supported).

Word files are read differently from the other types. Gemini does not read `.docx` files directly, so `DocumentReader` opens the file with the standard library (`zipfile` and `xml.etree.ElementTree`, no new package), reads the text of the main body from `word/document.xml`, and sends it to the model as plain text, one line per paragraph. Text split across formatting runs is joined, tabs and line breaks are kept, each table cell comes out on its own line, and text deleted in tracked changes is left out. After that the file is handled like any other: the same summary prompt that treats the file as untrusted, the same note, proposed tasks that need your confirmation, and the same rule that a request which read a file cannot delete anything. A Word file is refused with `InvalidInputError`, before any model request, when:

- it is not a readable `.docx` file (not a zip archive, or no `word/document.xml` inside);
- its document body is larger than 20 MB;
- it contains a DTD (`<!DOCTYPE`). Word never writes one, and refusing it shuts out XML entity tricks such as "billion laughs";
- it has no text to summarize.

How `@path` works in the terminal chat:

- Only an `@` at the start of a word counts, and only if the word is in quotes, has a file extension or contains a folder separator. So `ana@example.com` and `@Ana` stay ordinary text.
- The mention is replaced by the file name in the message that is sent. A message that is only a mention asks BuddyAI to summarize the file and list suggested action items. Punctuation right after a mention, as in `@notes.txt,`, is not part of the path.
- Each file is checked before any model request, so a mistake costs no request. A missing file shows a red `InvalidInputError` line and a file of an unsupported type shows a red `UnsupportedFileTypeError` line. The type is checked first, so a missing file with an unsupported extension shows `UnsupportedFileTypeError`.
- A message can hold more than one `@path`.

Tasks suggested from a file are proposals. They become real tasks only after you tell BuddyAI which ones to keep.

### Models: automatic switching, and switching by hand

Each Gemini model has its own free limits. BuddyAI keeps a list of models, best first, and handles a model that stops working by itself.

**Automatic.** When the model in use has reached its daily limit, has hit its requests-per-minute limit, or is not responding, BuddyAI moves to the best model in the list that still works, answers the same message with it, and tells you:

```
You> Add a task to buy milk tomorrow.
gemini-3.5-flash-lite has reached today's free request limit, so I switched to gemini-3.1-flash-lite.

I have added the task "Buy milk", due tomorrow.
```

- You do not need to send the message again. If that model fails too, BuddyAI tries the next one, and reports each switch.
- The default order puts the two models with 500 free requests a day first (`gemini-3.5-flash-lite`, then `gemini-3.1-flash-lite`) and the three models with 20 a day after them. On 2026-11-27 a per-minute limit on `gemini-3.5-flash-lite` sent BuddyAI to two 20-per-day models that did not respond, and the reply took 101 seconds. With the current order it moves to the other 500-per-day model first.
- A daily limit is remembered in `data\model_limits.json` until Google resets it (midnight US Pacific time, 4 PM in Manila). If you open BuddyAI again that day, it starts on the next best model and says so: at the top of the terminal chat, or with the first reply in the browser chat.
- A model that only says "high demand" is retried twice, a few seconds apart, before BuddyAI leaves it.
- If no model in the list works, BuddyAI says so and stops.

**By hand.** Type `/model` in either chat at any time:

```
You> /model
Current model: gemini-3.5-flash-lite

Available models:

1. gemini-3.5-flash-lite (in use)
2. gemini-3.1-flash-lite
3. gemini-3.6-flash
4. gemini-3.8-flash
5. gemini-4-hydrogen

To switch, type /model and a number or name, for example /model 2. /model next picks the next usable model in the list.

You> /model 3
Switched to gemini-3.6-flash. Your tasks, meetings and notes are unchanged.
```

- Pick by number, by name or part of a name (`/model lite` only works when one name matches), or `/model next`.
- A switch applies to all five agents and to file reading, needs no model request, and lasts until you close BuddyAI. The model it starts on is `BUDDYAI_MODEL` in `buddy_agent\.env`.
- To change the list or its order, set `BUDDYAI_MODELS` in `buddy_agent\.env` to a comma-separated list, best first. No code change is needed.
- To switch only by hand, set `BUDDYAI_AUTO_SWITCH=0`. BuddyAI then tells you the model is used up, lists the others, and waits for your `/model` choice.

### Settings and free-tier limits

Settings live in `buddy_agent\.env`:

| Setting | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | none | Your Gemini API key |
| `BUDDYAI_MODEL` | `gemini-3.5-flash-lite` | Model BuddyAI starts on |
| `BUDDYAI_MODELS` | `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.6-flash`, `gemini-3.8-flash`, `gemini-4-hydrogen` | Models BuddyAI may use, best first, comma-separated |
| `BUDDYAI_AUTO_SWITCH` | on | Set to `0` to choose the next model yourself |
| `BUDDYAI_DOC_MODEL` | same as `BUDDYAI_MODEL` | Model that reads files |
| `BUDDYAI_TIMEZONE` | `Asia/Manila` | Time zone for all dates |
| `BUDDYAI_LOCATION` | `Manila` | Default city or place for the weather in the daily briefing |
| `BUDDYAI_DATA_DIR` | `data` in this folder | Where the JSON files are kept (relative paths resolve from the project folder) |
| `BUDDYAI_ICS_FILE` | none | Optional read-only `.ics` calendar file to load at startup (relative paths resolve from the project folder) |
| `BUDDYAI_VOICE_MODEL` | `gemini-3.8-live` | Gemini Live model used by `/live`. It does not affect `/voice`, which always uses `gemini-3.5-transcribe-live`. |

One chat message costs at least four model requests (coordinator, specialist twice, coordinator), and a two-part message costs more. The free tier counts requests, so the model choice matters. Measured with a free key on 2026-11-24:

| Model | Free-tier limit seen | Result |
|---|---|---|
| `gemini-3.5-flash-lite` | 500 per day, 15 per minute | Fastest. Handled tasks, briefings, proposals and a 9 MB PDF correctly. |
| `gemini-3.1-flash-lite` | 500 per day, 15 per minute | Answered a test request; slower than 3.5 Flash Lite. |
| `gemini-3.6-flash` | 20 per day, 5 per minute | Used up after about four messages. |
| `gemini-3.8-flash` | 20 per day, 5 per minute | Answered "high demand" or nothing at all on most attempts that day. |
| `gemini-4-hydrogen` | 20 per day, 5 per minute | Used up after about four messages. Also returned "high demand" errors. |

These limits are from the project's rate-limit page in Google AI Studio. Every model also has a limit of 250,000 input tokens per minute.

Why a reply can be slow: every message is at least four model requests one after another, a large file adds a long reading step (about 25 seconds for a 9 MB PDF), and a busy model adds waiting and retries. `gemini-3.5-flash-lite` is the quickest choice for development.

Google does not publish these numbers and can change them. Your own limits are shown at <https://ai.dev/rate-limit>. Daily limits reset at midnight US Pacific time (4 PM in Manila).

### Messages you may see

| Message | What to do |
|---|---|
| "... so I switched to ..." followed by an answer | Nothing. BuddyAI moved to another model and answered your message. |
| "... so I switched to .... Please send your message again." | Send the message again. This happens when a whole turn ran out of time. |
| "... reached today's free request limit earlier, so BuddyAI is starting on ..." | Nothing. The model in `.env` is used up for today. |
| "Every other model in the list is also unusable right now." | Wait for the reset time shown, or add another model to `BUDDYAI_MODELS`. |
| "... You need to switch models to continue." (only with `BUDDYAI_AUTO_SWITCH=0`) | Type `/model` and a number from the list, then send your message again. |
| "The Gemini API rate limit was reached." | Wait a minute and send the message again. |
| "Gemini is busy right now." | Send the message again in a moment, or type `/model next`. |
| "Gemini took too long to answer." | Send the message again, or type `/model next`. |
| "The AI model could not read the file right now." | Send the request again, or type `/model next` first. |
| "Part of your request was already saved before this error." | Ask for your tasks or meetings before repeating the request, so nothing is added twice. |
| "Authentication with the Gemini API failed." | Check the key in `buddy_agent\.env`. |

Library warnings and error details go to `buddyai.log` in this folder, not to the chat window.

## Project Structure

```
BuddyAI/
├── main.py                      Terminal chat entry point: setup and the input loop
├── requirements.txt             Python packages
├── setup.bat                    First-time setup: virtual environment, packages, .env file
├── run_cli.bat                  Starts the terminal chat
├── run_web.bat                  Starts ADK's browser chat
├── buddy_agent/                 Entry point that `adk web` loads
│   ├── agent.py                 Exposes the root agent
│   └── .env.example             Settings template (copy to .env and add your key)
├── buddyai/                     The application package
│   ├── models/                  Domain classes
│   │   ├── work_item.py         WorkItem, the abstract base class
│   │   ├── task.py              Task: due date, priority, urgency score
│   │   ├── meeting.py           Meeting: start, end, location, overlap check
│   │   ├── reminder.py          Reminder: one-off, daily or weekly
│   │   ├── note.py              Note: text and the action items found in a file
│   │   └── contact.py           Contact: a meeting attendee
│   ├── managers/                Rules for each kind of item
│   │   ├── task_manager.py      TaskManager: tasks, reminders, proposals, ranking, lookup by ID or title
│   │   ├── agenda.py            Agenda: meetings, conflict check, free slots, rename and move
│   │   └── notebook.py          Notebook: notes, keyword search, lookup by ID or title
│   ├── sources/                 Where data is stored
│   │   ├── data_source.py       DataSource, the abstract storage interface
│   │   ├── json_store.py        JsonStore: atomic JSON files
│   │   └── ics_calendar_source.py IcsCalendarSource: read-only .ics calendar file reader
│   ├── agents/                  The AI agents
│   │   ├── profiles.py          AgentProfile and the coordinator and four specialist profiles
│   │   └── patient_gemini.py    PatientGemini: waits and retries when Gemini is busy
│   ├── cli/                     The terminal interface
│   │   ├── commands.py          CommandRouter: runs each typed command
│   │   ├── ui.py                TerminalUI: all terminal output
│   │   ├── input.py             BuddyPrompt: input line with autocomplete and history
│   │   └── theme.py             Colors, command list and the mascot
│   ├── voice/                   BuddyAI Live and voice-to-text dictation
│   │   ├── audio_device.py      AudioDevice (abstract) and SoundDeviceAudio
│   │   ├── voice_session.py     VoiceSession: ADK live streaming, echo guard, and playback loops
│   │   └── transcriber.py       VoiceTranscriber: streams speech to a fixed Live model for /voice
│   ├── app.py                   BuddyApp: sessions, model failover, file uploads
│   ├── toolkit.py               BuddyToolkit: the tools the agents call
│   ├── workspace.py             Workspace: owns the managers and saves and loads them
│   ├── briefing.py              BriefingService and DailyBriefing: schedule, weather and headlines
│   ├── document_reader.py       DocumentReader: summarizes PDF, PNG, JPG, TXT and Word (.docx) files
│   ├── web_lookup.py            WebLookup: stdlib-only weather (Open-Meteo), headlines and web search (Google News + Wikipedia)
│   ├── model_catalog.py         ModelCatalog: the ordered list of models
│   ├── model_limits.py          ModelLimitLog: remembers daily limits between runs
│   ├── config.py                Settings from .env and date parsing
│   └── exceptions.py            The custom exception hierarchy
├── tests/                       Offline unit tests (unittest), one file per area; test_edit_and_delete.py covers
│                                editing and deleting meetings, reminders, notes and completed tasks, and
│                                test_untrusted_content_guard.py covers the no-deletion rule
├── sample_data/                 Sample data generator and demonstration files
│   ├── make_sample_data.py      Generates sample JSON files and sample_calendar.ics around today's date
│   ├── sample_meeting_notes.txt Sample TXT document for the @path demo
│   └── example/                 Fixed-date snapshot of JSON files and sample_calendar.ics (read-only reference)
├── docs/
│   ├── AI_USAGE.md              AI usage log
│   ├── BACKLOG.md               Product backlog and user stories
│   ├── submission/              The documents the team submits
│   │   ├── BuddyAI_Technical_Documentation_v2.pdf     Technical documentation, version 2.0 (the Word file is beside it)
│   │   ├── IT121AL_Project_Proposal_BuddyAI_v3.docx   Project proposal, current version
│   │   └── earlier_versions/    Earlier versions of the proposal
│   └── uml/                     UML class diagrams (PNG) and the script that draws them
└── data/                        Your JSON files, created on first run, not in git
```

The code is in layers. The domain classes in `models/` do not use the agents or the model. The managers in `managers/` hold the rules, such as the conflict check and the ranking. `Workspace` owns the managers and saves and loads them through a `DataSource`. `BuddyToolkit` is the one class the agents call, and it turns every error into a message instead of crashing. `BuddyApp` connects the agents, the toolkit and the model list, and `main.py` with the `cli/` package is the terminal interface. The typed `/task` and `/meet` commands call the same `BuddyToolkit` methods as the agents, so the same rules apply.

## Testing

The `unittest` suite runs offline, with no API key. Model calls are replaced by stand-in models.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Add `-v` to list each test. Current result: `Ran 560 tests`, `OK`. The tests make no network requests: the web lookup uses an injected fetcher that returns stored replies.

The tests cover:

- the domain classes: urgency score, due dates, overlap, reminder repeats and status notes, saving and loading each item (`test_models.py`)
- the managers: task ranking and lookup, conflicts, free slots, notes (`test_managers.py`)
- storage and the exception hierarchy, including atomic writes and a corrupt file (`test_storage_and_workspace.py`)
- `BuddyToolkit`, the agent profiles, the file reader and `BuddyApp`, including `BuddyApp.check_file` and reading Word (`.docx`) files: the text sent to the model, text split across runs, table cells, tracked-change deletions, and the refusals for a file that is not a zip, a missing document body, no text and a DTD (`test_toolkit.py`, `test_profiles_and_app.py`, `test_document_reader.py`)
- the fixes made after the Sprint 1 review, one behaviour per test (`test_sprint1_fixes.py`)
- model switching, daily limits, retries and failover (`test_model_switching.py`, `test_model_limits.py`, `test_uploads_and_failover.py`)
- editing and deleting: `Meeting.set_location`, `Agenda.update_meeting` (all or nothing, calendar-file meetings refused), `TaskManager.find_reminder`, finding completed tasks by title, `Notebook.find_note`, the toolkit tools `update_meeting`, `list_reminders`, `delete_reminder` and `delete_note`, saving the change to disk, and the honesty rule in every agent's instruction (`test_edit_and_delete.py`)
- the rule that a request which read a file or web content cannot delete anything, and when `BuddyApp` starts a new request (`test_untrusted_content_guard.py`)
- the terminal commands, including `/task add`, `/task edit`, `/task delete`, `/meet add`, `/meet move`, `/meet edit`, `/meet cancel`, `/task done`, `/brief` with a day, time and place, usage messages, unknown commands with a suggestion, the grouped `/help`, and `@path` file mentions with their file check (`test_cli_commands.py`), and the terminal output and the autocomplete of commands and of paths after `@` (`test_cli_ui.py`)
- sample data generation, corrupt-file startup handling, and relative path settings (`test_sample_data.py`, `test_main_startup.py`, `test_config.py`)
- iCalendar (`.ics`) parsing, read-only conflict/briefing integration, and the `/calendar` command (`test_ics_calendar_source.py`, `test_calendar_integration.py`, `test_calendar_command.py`)
- BuddyAI Live audio loops, speaker-safe echo guard, interruption recovery, spoken stop, specialist delegation, `/voice` live streaming dictation (`VoiceTranscriber`), lazy `sounddevice` handling, and `/live` (`test_voice_session.py`, `test_voice_audio_device.py`)
- weather, headline and web lookup parsing, fallback, and toolkit integration (`test_web_lookup.py`), and the weather and headline sections of the briefing (`test_cli_commands.py`, `test_toolkit.py`)

## Sample Credentials

Not applicable. BuddyAI has one user and no sign-in. The only secret is your Gemini API key in `buddy_agent\.env`, which git ignores and which is never committed.

## AI Usage Disclosure

AI coding tools generated most of the Sprint 1 code from written instructions that the team prepared. They also helped with design review, live testing, debugging, the terminal interface tests, the diagrams and the documents. The team reviewed the output, ran the tests, and corrected what was wrong; for example, a retry setting that made the chat freeze was removed and a manual-only model switch was replaced by automatic switching. On 2026-11-27 an AI review pointed out that the new delete tools could be reached after the agents read a file or web page, and a code guard was added. The unit tests run offline, so a passing result comes from running the code. The full log, with the tools used, what they suggested and what the team changed or verified, is in [docs/AI_USAGE.md](docs/AI_USAGE.md).

## Known Limitations

- Chatting needs internet and a Gemini API key. The free tier has limits, and one chat message costs at least four model requests, so replies can be slow. The typed commands that change data (`/task`, `/meet`) and the instant views (`/brief`, `/tasks`, `/status`) work without the model; `/brief` still needs internet for its weather and headlines.
- One user, with no accounts or sign-in. Run only one of the terminal chat and the browser chat at a time: each keeps its own copy of the data in memory.
- The terminal chat is the interface that is built to be used. The browser chat (`adk web`) is a development view and has only the `/model` command.
- Files must be PDF, PNG, JPG, TXT or Word (`.docx`). The old Word format `.doc` is not supported. A `.docx` read covers the main body only: headers, footers, footnotes, comments and images are not read. Text in a text box is read once (Word keeps a second copy for older programs, which BuddyAI skips).
- The typed commands cover tasks and meetings only (add, edit, delete, move, cancel, complete). Reminders and notes are changed through the chat. The typed commands take dates in ISO form only, for example `2026-11-30` or `2026-11-30T14:00`.
- A meeting location cannot be cleared through the chat tool or `/meet edit`, because an empty field means "unchanged". Reminders cannot be edited, only added, listed and deleted. Notes cannot be edited, only added, searched and deleted. The weather and headlines in the daily briefing need an internet connection; without it those two sections show `Unavailable (...)`.
- After a chat message that read a file, searched the web or built a briefing, deleting or cancelling is refused (`UnsafeDeletionError`) until the next chat message starts. The typed commands `/task delete` and `/meet cancel` are not affected, because each typed command starts a new request. Inside one `/live` session the refusal lasts until the session ends, because a voice session counts as one request: after a web search or briefing by voice, deletions must wait for the text chat.
- On the Gemini free tier, Google may use the content you send to improve its products, so use only sample data.
- `buddyai/app.py` is the largest file (about 855 lines: session handling, model failover, uploads) and the hardest part to maintain.
- Calendar file (`.ics`) reading does not expand recurring rules (`RRULE`, first occurrence only), skips all-day (`VALUE=DATE`) and `DURATION`-only events, skips non-IANA Windows timezone names, does not filter `STATUS:CANCELLED` events, and reads the file only when loaded (run `/calendar <path>` again after editing it).
- Voice modes (`/live` and `/voice`) need internet, a Gemini API key (Live-capable for `/live`), and working audio hardware; `/live` uses speaker-safe mic gating by default (press Space/Enter to interrupt) and supports `/live barge` for full-duplex headphones; each spoken request in `/live` that delegates to a specialist still uses text-model requests; and `/live` keeps its own conversation history separate from the text chat (while sharing the same workspace data).
- Windows launchers only. On another system, use the commands under [Running without the launchers](#running-without-the-launchers).
- Google Calendar, Gmail and Google Drive are not part of the project.

## Authors

IT121AL, Computer Programming 2. Capstone project team:

| Member | Role |
|---|---|
| Randolf Daniel Mesa | AI Integration Lead and Lead Software Architect |
| Sarte | Lead Software Developer |
| Bautista | Interface and Integrations Developer |
| Quiros | Persistence and QA Engineer |

All commits in the repository were made from the team lead's GitHub account. The section "Team and ownership" of the technical documentation shows which part of the code each member maintains and explains.
