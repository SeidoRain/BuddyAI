# AI Usage Log

This file records AI-assisted implementation work for IT121AL (BuddyAI Sprint 1).

- **Date:** 2026-11-24
- **Tool:** Antigravity (AI coding assistant)
- **Scope:** Implemented the Sprint 1 architecture, domain classes, persistence layer, ADK agent integration, documentation, and offline unit tests according to the written Sprint 1 brief.

## Files Produced with AI Assistance

| Path | Purpose |
|---|---|
| `.gitignore`, `requirements.txt`, `buddy_agent/.env.example` | Environment, dependency, and ignore configuration |
| `buddyai/__init__.py`, `buddyai/config.py`, `buddyai/exceptions.py` | Package root, env settings, timezone-aware parsers, custom exception tree |
| `buddyai/models/*` | `WorkItem`, `Task`, `Meeting`, `Reminder`, `Note`, `Contact` |
| `buddyai/managers/*` | `TaskManager`, `Agenda`, `Notebook` |
| `buddyai/sources/*` | `DataSource` and atomic `JsonStore` |
| `buddyai/workspace.py`, `buddyai/briefing.py`, `buddyai/document_reader.py` | Workspace composition/polymorphism, `BriefingService`, `DocumentReader` |
| `buddyai/toolkit.py`, `buddyai/agents/*`, `buddyai/app.py` | `BuddyToolkit` (18 ADK tools), 5 `AgentProfile` classes, `BuddyApp` facade |
| `main.py`, `buddy_agent/__init__.py`, `buddy_agent/agent.py` | Terminal REPL and `adk web` entry points |
| `tests/*` | Offline `unittest` suite covering all domain, storage, toolkit, and ADK profile layers |
| `README.md`, `docs/AI_USAGE.md`, `SPRINT1_NOTES.md` | Setup guide, AI usage log, and Sprint 1 reviewer notes |

## Design Review, Testing and Fixes

- **Date:** 2026-11-24
- **Tool:** Claude Code (AI coding assistant)
- **Scope:** Reviewed the approved proposal and revised it as version 2, wrote the Sprint 1 implementation brief, tested the Sprint 1 build offline (unit tests, an independent acceptance check, the terminal chat, and the ADK browser chat driven by Playwright with a scripted stand-in model), and fixed the issues found.

| Path | Purpose |
|---|---|
| `IT121AL_Project_Proposal_BuddyAI_v2.docx` | Revised proposal text, tables and both UML figures |
| `main.py` | `/file` paths with spaces; library tracebacks go to `buddyai.log` |
| `buddyai/agents/profiles.py` | UTC offset in the time line instead of "PST"; confirmation rule moved to the coordinator |
| `buddyai/managers/task_manager.py` | `confirm_all` (all-or-nothing); past one-off reminders refused |
| `buddyai/managers/agenda.py` | No free slots or new meetings in the past; quarter-hour rounding |
| `buddyai/toolkit.py` | Passes the current time to the rules above |
| `tests/test_sprint1_fixes.py` | 32 single-purpose tests for the fixes |
| `.gitignore`, `README.md` | Ignore `.adk/` and `*.log`; quick start, model limits and error messages |

Live testing with a real Gemini key followed on the same day (terminal chat and browser chat), and led to these further changes:

| Path | Purpose |
|---|---|
| `buddyai/config.py`, `buddyai/agents/profiles.py`, `buddyai/document_reader.py` | Retry temporary Gemini server errors (5xx) automatically |
| `buddyai/app.py`, `buddyai/workspace.py` | Clear replies for daily-limit, rate-limit, busy and timeout errors; a note when part of a request was already saved; a time limit per turn |
| `setup.bat`, `run_cli.bat`, `run_web.bat` | One-step setup and launchers for both entry points |
| `buddyai/model_catalog.py`, `buddyai/app.py`, `buddyai/agents/profiles.py`, `buddyai/config.py`, `main.py` | Switching Gemini models from either chat with `/model`; automatic move to the next model when a daily limit is reached |
| `tests/test_model_switching.py` | 24 tests for the model catalog and switching |
| `buddyai/agents/patient_gemini.py`, `buddyai/app.py`, `buddyai/document_reader.py`, `buddyai/exceptions.py` | Short retry when Gemini is busy; one automatic model switch per message; clear replies for failed model calls in both chats; removed an SDK retry setting that made a busy model hang |
| `buddyai/agents/profiles.py`, `buddyai/app.py` | Files attached with the browser chat's upload button are saved and read through `DocumentReader` |
| `tests/test_uploads_and_failover.py` | 19 tests for uploads, retries and failover |
| `buddyai/model_limits.py`, `buddyai/app.py`, `buddyai/model_catalog.py`, `buddyai/config.py`, `main.py` | When a model reaches its daily limit, both chats say so and require the user to switch; the limit is remembered between runs |
| `tests/test_model_limits.py` | 19 tests for the daily-limit notice |
| `buddyai/app.py`, `buddyai/model_catalog.py`, `buddyai/config.py` | Automatic move to the next best model when one is used up, rate-limited or not responding, answering the same message and telling the user; switching by hand kept; manual-only mode behind `BUDDYAI_AUTO_SWITCH=0` |
