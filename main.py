"""Terminal chat entry point for BuddyAI."""

import logging
import os
import sys

from dotenv import load_dotenv

from buddyai.app import BuddyApp
from buddyai.cli import BuddyPrompt, TerminalUI
from buddyai.config import ENV_FILE, PROJECT_ROOT, get_api_key
from buddyai.model_catalog import ModelCatalog

LOG_FILE = os.path.join(PROJECT_ROOT, "buddyai.log")

HELP_TEXT = """Commands:
  /model [number or name]  Show or pick from available Gemini models
  /file <path> [message]   Attach a PDF, PNG, JPG, or TXT file to summarize
  /brief                   Show today's daily briefing (instant)
  /tasks                   Show open tasks & pending proposals (instant)
  /status                  Show session & workspace summary
  /clear                   Clear screen and show header
  /help                    Show this help message
  /quit                    Exit BuddyAI"""


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


def _configure_logging():
    """Send library warnings and tracebacks to a log file, not the chat window."""
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )


def _configure_stdio():
    """Enable UTF-8 output on Windows consoles when supported."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _handle_model_command(app, ui, user_input):
    """Handle `/model` (interactive picker or list) and `/model <arg>`."""
    parts = user_input.split(None, 1)
    if len(parts) == 1:
        chosen = ui.pick_model_interactive(app)
        if not ui.interactive:
            return
        if chosen is None:
            ui.render_muted("Model unchanged.")
            return
        reply = app.handle_command(f"/model {chosen}")
    else:
        reply = app.handle_command(user_input)

    if reply is None:
        return
    if reply.startswith("Switched to "):
        if app.model_catalog.reason_for(app.current_model) == ModelCatalog.DAILY_LIMIT:
            ui.render_warn(reply)
        else:
            ui.render_ok(reply)
    elif "daily limit" in reply.lower() or "free request limit" in reply.lower():
        ui.render_warn(reply)
    else:
        ui.render_error(reply)


def _run_chat_turn(app, ui, prompt_text, files=None):
    """Execute one BuddyApp turn with a live thinking indicator and Ctrl+C handling."""
    try:
        with ui.thinking_context() as indicator:
            reply = app.ask(prompt_text, files=files, on_status=indicator.update)
        ui.render_buddy_reply(
            reply,
            agents=indicator.agents,
            elapsed=indicator.elapsed,
        )
    except KeyboardInterrupt:
        ui.render_warn("Cancelled.")


def main():
    """Run the interactive BuddyAI terminal chat."""
    _configure_logging()
    _configure_stdio()
    load_dotenv(ENV_FILE)

    ui = TerminalUI()
    if not get_api_key():
        ui.render_error("GOOGLE_API_KEY is not set.")
        ui.render_muted(
            "Setup: copy buddy_agent/.env.example to buddy_agent/.env and set "
            "GOOGLE_API_KEY=<your Gemini API key>."
        )
        return 1

    app = BuddyApp()
    prompt = BuddyPrompt(lambda: app.current_model)
    ui.render_welcome(app)

    pending_exit = False
    try:
        while True:
            try:
                user_input = prompt.read_input()
            except EOFError:
                ui.render_muted("Goodbye!")
                break
            except KeyboardInterrupt:
                if pending_exit or not ui.interactive:
                    ui.render_muted("Goodbye!")
                    break
                pending_exit = True
                ui.render_muted("Press Ctrl+C again or type /quit to exit.")
                continue

            pending_exit = False
            if not user_input:
                continue

            lowered = user_input.lower()
            if lowered in ("/quit", "/exit"):
                ui.render_muted("Goodbye!")
                break
            if lowered == "/help":
                ui.render_help()
                continue
            if lowered == "/clear":
                ui.clear_and_reset(app)
                continue
            if lowered == "/status":
                ui.render_status(app)
                continue
            if lowered == "/tasks":
                ui.render_tasks(app)
                continue
            if lowered == "/brief":
                ui.render_brief(app)
                continue

            first_word = lowered.split(None, 1)[0]
            if first_word in ("/model", "/models"):
                _handle_model_command(app, ui, user_input)
                continue

            if user_input.startswith("/file"):
                remainder = user_input[len("/file"):]
                file_path, note_prompt = _parse_file_command(remainder)
                if not file_path:
                    ui.render_warn("Usage: /file <path> [optional message]")
                    continue
                _run_chat_turn(app, ui, note_prompt, files=[file_path])
                continue

            _run_chat_turn(app, ui, user_input)
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
