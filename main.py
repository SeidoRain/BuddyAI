"""Terminal chat entry point for BuddyAI."""

import logging
import os
import sys

from dotenv import load_dotenv

from buddyai.app import BuddyApp
from buddyai.cli import BuddyPrompt, CommandRouter, TerminalUI
from buddyai.config import ENV_FILE, PROJECT_ROOT, get_api_key
from buddyai.exceptions import BuddyError

LOG_FILE = os.path.join(PROJECT_ROOT, "buddyai.log")


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

    try:
        app = BuddyApp()
    except BuddyError as exc:
        ui.render_error(f"{type(exc).__name__}: {exc}")
        ui.render_muted(
            "Fix or remove the file named above, then start BuddyAI again."
        )
        return 1
    prompt = BuddyPrompt(lambda: app.current_model)
    router = CommandRouter(app, ui)
    ui.render_welcome(app)
    if app.calendar_error:
        ui.render_warn(app.calendar_error)

    pending_exit = False
    try:
        while True:
            try:
                prefill = router.take_pending_input()
                user_input = prompt.read_input(default=prefill)
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

            outcome = router.handle(user_input)
            if outcome == CommandRouter.EXIT:
                break
            if outcome == CommandRouter.NOT_A_COMMAND:
                router.send(user_input)
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
