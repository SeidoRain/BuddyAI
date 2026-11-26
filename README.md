# BuddyAI (Sprint 1)

BuddyAI is an object-oriented Python executive assistant built with Google ADK and Gemini. You talk to it in plain language and it keeps tasks, meetings, reminders, notes and document summaries, saved to JSON files, and gives a daily briefing.

## Quick start (Windows)

1. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Double-click **`run_cli.bat`** (terminal chat) or **`run_web.bat`** (browser chat).
3. The first run creates the virtual environment, installs the packages, and creates `buddy_agent\.env`. Open that file, paste your key after `GOOGLE_API_KEY=`, and run the launcher again.

After that, either launcher starts BuddyAI directly.

| Launcher | What you get |
|---|---|
| `run_cli.bat` | The terminal chat. This is the graded demo. |
| `run_web.bat` | ADK's browser chat at `http://127.0.0.1:8000`. It opens the page for you and shows which agent and tool handled each message. Keep the window open; press Ctrl+C in it to stop. |

Run only one of them at a time. Each keeps its own copy of the data in memory, so two running together overwrite each other's saves.

Put the key in `buddy_agent\.env`, never in `.env.example`: the example file is shared with the team and the real one is ignored by git.

## Running without the launchers

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item buddy_agent\.env.example buddy_agent\.env   # then add your key

python main.py        # terminal chat
adk web --port 8000   # browser chat, run from this folder, then pick buddy_agent
```

## Using the chat

Things to try:

- `Add a high priority task to submit the thesis draft by Friday.`
- `What should I do first?`
- `Schedule a thesis meeting tomorrow from 2pm to 3pm.`
- `Move my thesis meeting to a free slot tomorrow afternoon and remind me to bring the draft.`
- `Give me my briefing for tomorrow.`

Terminal commands (type `/` for autocomplete, `↑`/`↓` for history, and `Tab` after `/file ` for path completion):

| Command | What it does |
|---|---|
| `/file <path> [message]` | Summarizes a PDF, PNG, JPG or TXT file and proposes tasks from it. The path may contain spaces; quotes are optional. |
| `/model` | Opens the interactive model picker (or lists models in piped mode). Also works in the browser chat. |
| `/model 2`, `/model lite`, `/model next` | Switches model by number, by name or part of a name, or to the next one in the list. Also works in the browser chat. |
| `/brief` | Prints today's daily briefing locally with zero API calls. |
| `/tasks` | Shows open tasks and pending proposals in a formatted table. |
| `/status` | Shows active model, timezone, and workspace item counts. |
| `/clear` | Clears the screen and re-renders the compact header. |
| `/help` | Lists the commands. |
| `/quit` | Exits. |

Three ways to give BuddyAI a file:

- Terminal: `/file C:\path\to\brief.pdf`.
- Either chat: type the path in a message, for example `C:\path\to\brief.pdf summarize`.
- Browser chat: attach it with the **+** button and say what you want. BuddyAI saves a copy in `data\uploads` and reads it from there.

All three go through the same file check and produce the same summary and task proposals.

Tasks suggested from a file are proposals. They become real tasks only after you tell BuddyAI which ones to keep.

## Models: automatic switching, and switching by hand

Each Gemini model has its own free limits. BuddyAI keeps a list of models, best first, and handles a model that stops working by itself.

**Automatic.** When the model in use has reached its daily limit, has hit its requests-per-minute limit, or is not responding, BuddyAI moves to the best model in the list that still works, answers the same message with it, and tells you:

```
You> Add a task to buy milk tomorrow.
gemini-4-hydrogen has reached today's free request limit, so I switched to gemini-3.5-flash-lite.

I have added the task "Buy milk", due tomorrow.
```

- You do not need to send the message again. If that model fails too, BuddyAI tries the next one, and reports each switch.
- A daily limit is remembered in `data\model_limits.json` until Google resets it (midnight US Pacific time, 4 PM in Manila). If you open BuddyAI again that day, it starts on the next best model and says so: at the top of the terminal chat, or with the first reply in the browser chat.
- A model that only says "high demand" is retried twice, a few seconds apart, before BuddyAI leaves it.
- If no model in the list works, BuddyAI says so and stops.

**By hand.** Type `/model` in either chat at any time:

```
You> /model
Current model: gemini-3.5-flash-lite

Available models:

1. gemini-3.5-flash-lite (in use)
2. gemini-3.6-flash
3. gemini-3.8-flash
4. gemini-4-hydrogen
5. gemini-3.1-flash-lite

You> /model 2
Switched to gemini-3.6-flash. Your tasks, meetings and notes are unchanged.
```

- Pick by number, by name or part of a name (`/model lite` only works when one name matches), or `/model next`.
- A switch applies to all five agents and to file reading, needs no model request, and lasts until you close BuddyAI. The model it starts on is `BUDDYAI_MODEL` in `buddy_agent\.env`.
- To change the list or its order, set `BUDDYAI_MODELS` in `buddy_agent\.env` to a comma-separated list, best first. No code change is needed.
- To switch only by hand, set `BUDDYAI_AUTO_SWITCH=0`. BuddyAI then tells you the model is used up, lists the others, and waits for your `/model` choice.

## Model and free-tier limits

Settings live in `buddy_agent\.env`:

| Setting | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | none | Your Gemini API key |
| `BUDDYAI_MODEL` | `gemini-3.5-flash-lite` | Model BuddyAI starts on |
| `BUDDYAI_MODELS` | the five models listed above | Models BuddyAI may use, best first, comma-separated |
| `BUDDYAI_AUTO_SWITCH` | on | Set to `0` to choose the next model yourself |
| `BUDDYAI_DOC_MODEL` | same as `BUDDYAI_MODEL` | Model that reads files |
| `BUDDYAI_TIMEZONE` | `Asia/Manila` | Time zone for all dates |
| `BUDDYAI_DATA_DIR` | `data` in this folder | Where the JSON files are kept |

One chat message costs at least four model requests (coordinator, specialist twice, coordinator), and a two-part message costs more. The free tier counts requests, so the model choice matters. Measured with a free key on 2026-11-24:

| Model | Free-tier limit seen | Result |
|---|---|---|
| `gemini-4-hydrogen` | 20 per day, 5 per minute | Used up after about four messages. Also returned "high demand" errors. |
| `gemini-3.5-flash-lite` | 500 per day, 15 per minute | Fastest. Handled tasks, briefings, proposals and a 9 MB PDF correctly. |
| `gemini-3.1-flash-lite` | 500 per day, 15 per minute | Answered a test request; slower than 3.5 Flash Lite. |
| `gemini-3.6-flash` | 20 per day, 5 per minute | Used up after about four messages. |
| `gemini-3.8-flash` | 20 per day, 5 per minute | Answered "high demand" or nothing at all on most attempts that day. |

These limits are from the project's rate-limit page in Google AI Studio. Every model also has a limit of 250,000 input tokens per minute.

Why a reply can be slow: every message is at least four model requests one after another, a large file adds a long reading step (about 25 seconds for a 9 MB PDF), and a busy model adds waiting and retries. `gemini-3.5-flash-lite` is the quickest choice for development.

Google does not publish these numbers and can change them. Your own limits are shown at <https://ai.dev/rate-limit>. Daily limits reset at midnight US Pacific time (4 PM in Manila).

## Messages you may see

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

## Tests

The `unittest` suite runs offline, with no API key:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
