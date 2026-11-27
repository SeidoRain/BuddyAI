"""Unit tests for telling the user that a model's free daily limit is reached
and that they must switch models (terminal chat and browser chat)."""

from datetime import datetime
import logging
import os
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from buddyai.app import BuddyApp
from buddyai.model_limits import ModelLimitLog

MANILA = ZoneInfo("Asia/Manila")
CHOICES = ["gemini-3.5-flash-lite", "gemini-4-hydrogen", "gemini-3.6-flash"]
# 3 PM in Manila is 11 PM the previous day in US Pacific time: one hour before the reset.
BEFORE_RESET = datetime(2026, 11, 24, 15, 0, tzinfo=MANILA)
AFTER_RESET = datetime(2026, 11, 24, 16, 30, tzinfo=MANILA)


class _DailyLimitError(Exception):
    code = 429

    def __init__(self):
        super().__init__(
            "429 RESOURCE_EXHAUSTED. GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        )


class _BusyError(Exception):
    code = 503

    def __init__(self):
        super().__init__("503 UNAVAILABLE. This model is currently experiencing high demand.")


class _CountingLlm(BaseLlm):
    """Stand-in model: 'gemini-4-hydrogen' is out of requests, 'gemini-3.6-flash'
    is busy, anything else answers. It counts how many requests it received."""

    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        if llm_request.model == "gemini-4-hydrogen":
            raise _DailyLimitError()
        if llm_request.model == "gemini-3.6-flash":
            raise _BusyError()
        text = f"answered by {llm_request.model}"
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )


class TestModelLimitLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.now = BEFORE_RESET
        self.log = ModelLimitLog(self._tmp.name, clock=lambda: self.now)

    def tearDown(self):
        self._tmp.cleanup()

    def test_nothing_is_limited_before_anything_is_recorded(self):
        self.assertEqual(self.log.limited_today(), [])

    def test_a_recorded_model_is_listed(self):
        self.log.record("gemini-4-hydrogen")
        self.assertEqual(self.log.limited_today(), ["gemini-4-hydrogen"])

    def test_the_same_model_is_listed_once(self):
        self.log.record("gemini-4-hydrogen")
        self.log.record("gemini-4-hydrogen")
        self.assertEqual(self.log.limited_today(), ["gemini-4-hydrogen"])

    def test_the_list_survives_a_restart(self):
        self.log.record("gemini-4-hydrogen")
        reopened = ModelLimitLog(self._tmp.name, clock=lambda: self.now)
        self.assertEqual(reopened.limited_today(), ["gemini-4-hydrogen"])

    def test_the_list_is_empty_again_after_the_daily_reset(self):
        self.log.record("gemini-4-hydrogen")
        self.now = AFTER_RESET
        self.assertEqual(self.log.limited_today(), [])

    def test_an_unreadable_file_is_treated_as_empty(self):
        with open(os.path.join(self._tmp.name, ModelLimitLog.FILE_NAME), "w") as handle:
            handle.write("{ not json")
        self.assertEqual(self.log.limited_today(), [])

    def test_a_models_value_that_is_not_a_list_is_treated_as_empty(self):
        quota_day = self.log._quota_day()
        for bad_value in ("null", "5"):
            with self.subTest(models=bad_value):
                with open(
                    os.path.join(self._tmp.name, ModelLimitLog.FILE_NAME), "w"
                ) as handle:
                    handle.write(f'{{"quota_day": "{quota_day}", "models": {bad_value}}}')
                self.assertEqual(self.log.limited_today(), [])

    def test_next_reset_is_midnight_pacific_shown_in_local_time(self):
        self.assertEqual(
            self.log.next_reset(), datetime(2026, 11, 24, 16, 0, tzinfo=MANILA)
        )


class TestUserMustSwitchWhenAutomaticSwitchingIsOff(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)      # the simulated failures are expected
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "test-key",
                "BUDDYAI_MODELS": ",".join(CHOICES),
                "BUDDYAI_AUTO_SWITCH": "0",     # the user chooses the next model
            },
        )
        self._env.start()
        self.llm = _CountingLlm(model="gemini-4-hydrogen")
        self.app = self._open(self.llm)

    def _open(self, llm):
        return BuddyApp(data_dir=self._tmp.name, model=llm, clock=lambda: BEFORE_RESET)

    def tearDown(self):
        self.app.close()
        self._env.stop()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_the_reply_names_the_model_and_says_the_limit_is_reached(self):
        reply = self.app.ask("hello")
        self.assertIn("gemini-4-hydrogen has reached today's free request limit", reply)

    def test_the_reply_says_a_switch_is_needed_and_lists_the_models(self):
        reply = self.app.ask("hello")
        self.assertIn("You need to switch models to continue.", reply)
        self.assertIn("1. gemini-3.5-flash-lite", reply)
        self.assertIn("2. gemini-4-hydrogen (in use, daily limit reached)", reply)

    def test_the_reply_says_when_the_limit_resets(self):
        self.assertIn("after 4:00 PM on Tuesday", self.app.ask("hello"))

    def test_buddyai_does_not_switch_by_itself(self):
        self.app.ask("hello")
        self.assertEqual(self.app.current_model, "gemini-4-hydrogen")

    def test_further_messages_are_refused_without_calling_the_model(self):
        self.app.ask("hello")
        calls_after_first = self.llm.calls
        reply = self.app.ask("add a task to buy milk")
        self.assertIn("You need to switch models to continue.", reply)
        self.assertEqual(self.llm.calls, calls_after_first)

    def test_after_switching_the_message_goes_through(self):
        self.app.ask("hello")
        self.assertIn("Switched to gemini-3.5-flash-lite", self.app.ask("/model 1"))
        self.assertEqual(self.app.ask("hello"), "answered by gemini-3.5-flash-lite")

    def test_switching_back_to_the_used_up_model_repeats_the_notice(self):
        self.app.ask("hello")
        self.app.ask("/model 1")
        reply = self.app.ask("/model hydrogen")
        self.assertIn("gemini-4-hydrogen has reached today's free request limit", reply)

    def test_the_limit_is_known_as_soon_as_buddyai_is_opened_again(self):
        self.app.ask("hello")
        self.app.close()
        self.app = self._open(_CountingLlm(model="gemini-4-hydrogen"))
        notice = self.app.startup_notice()
        self.assertIn("gemini-4-hydrogen has reached today's free request limit", notice)
        self.assertIn("You need to switch models to continue.", notice)

    def test_a_fresh_start_on_a_usable_model_shows_the_normal_line(self):
        self.app.close()
        self.app = self._open(_CountingLlm(model="gemini-3.5-flash-lite"))
        self.assertEqual(
            self.app.startup_notice(),
            "Model: gemini-3.5-flash-lite (type /model to switch)",
        )

    def test_a_busy_model_is_reported_but_not_blocked(self):
        self.app.ask("/model 3")                         # gemini-3.6-flash is busy
        reply = self.app.ask("hello")
        self.assertIn("Gemini is busy right now", reply)
        self.assertEqual(self.app.current_model, "gemini-3.6-flash")
        calls = self.llm.calls
        self.app.ask("hello")                            # a retry is allowed
        self.assertGreater(self.llm.calls, calls)

    def test_the_notice_says_so_when_no_other_model_is_usable(self):
        self.app.ask("hello")
        for name in ("gemini-3.5-flash-lite", "gemini-3.6-flash"):
            self.app.model_catalog.mark_exhausted(name)
            self.app._limit_log.record(name)
        self.assertIn("Every other model in the list is also unusable", self.app.ask("hello"))

    def test_the_browser_chat_gets_the_same_notice(self):
        self.app.ask("hello")
        hook = self.app.root_agent.before_model_callback
        request = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part(text="hi again")])]
        )
        response = hook(None, request)
        self.assertIn(
            "You need to switch models to continue.", response.content.parts[0].text
        )


if __name__ == "__main__":
    unittest.main()
