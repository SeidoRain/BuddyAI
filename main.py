"""Terminal chat entry point for BuddyAI Sprint 1."""

import logging
import os
import sys

from dotenv import load_dotenv

from buddyai.app import BuddyApp
from buddyai.config import ENV_FILE, PROJECT_ROOT, get_api_key

LOG_FILE = os.path.join(PROJECT_ROOT, "buddyai.log")

HELP_TEXT = """Commands:
  /file <path> [message]   Attach a PDF, PNG, JPG, or TXT file to summarize
                           (the path may contain spaces; quotes are optional)
  /model [number or name]  Show the Gemini models, or switch to another one
                           (/model next picks the next model in the list)
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


def main():
    """Run the interactive BuddyAI terminal chat."""
    _configure_logging()
    load_dotenv(ENV_FILE)
    if not get_api_key():
        print("GOOGLE_API_KEY is not set.")
        print(
            "Setup: copy buddy_agent/.env.example to buddy_agent/.env and set "
            "GOOGLE_API_KEY=<your Gemini API key>."
        )
        return 1

    app = BuddyApp()
    print("BuddyAI Terminal Assistant (type /help for commands, /quit to exit)")
    print(app.startup_notice())
    try:
        while True:
            try:
                user_input = input("\nYou> ").strip()
            except EOFError:
                print("\nGoodbye!")
                break
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break

            if not user_input:
                continue
            if user_input.lower() in ("/quit", "/exit"):
                print("Goodbye!")
                break
            if user_input.lower() == "/help":
                print(HELP_TEXT)
                continue

            if user_input.startswith("/file"):
                remainder = user_input[len("/file"):]
                file_path, note_prompt = _parse_file_command(remainder)
                if not file_path:
                    print("Usage: /file <path> [optional message]")
                    continue
                reply = app.ask(note_prompt, files=[file_path])
                print(f"\nBuddyAI> {reply}")
                continue

            reply = app.ask(user_input)
            print(f"\nBuddyAI> {reply}")
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
