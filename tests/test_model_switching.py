"""Unit tests for switching Gemini models from the chat (/model)."""

import logging
import os
import tempfile
import unittest
from unittest.mock import patch

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from buddyai.app import BuddyApp
from buddyai.exceptions import InvalidInputError
from buddyai.model_catalog import ModelCatalog

CHOICES = ["gemini-3.5-flash-lite", "gemini-4-hydrogen", "gemini-3.6-flash"]


class _RecordingLlm(BaseLlm):
    """Stand-in model that answers with the model name each request was sent to."""

    async def generate_content_async(self, llm_request, stream=False):
        text = f"answered by {llm_request.model}"
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )


class _DailyLimitError(Exception):
    code = 429

    def __init__(self):
        super().__init__(
            "429 RESOURCE_EXHAUSTED. GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        )


class _LimitedOnHydrogen(BaseLlm):
    """Stand-in model whose 'gemini-4-hydrogen' has no free requests left today."""

    async def generate_content_async(self, llm_request, stream=False):
        if llm_request.model == "gemini-4-hydrogen":
            raise _DailyLimitError()
        text = f"answered by {llm_request.model}"
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )


def _user_request(text):
    return LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text=text)])]
    )


class TestModelCatalog(unittest.TestCase):
    def setUp(self):
        self.catalog = ModelCatalog(CHOICES, "gemini-4-hydrogen")

    def test_starts_on_the_given_model(self):
        self.assertEqual(self.catalog.current, "gemini-4-hydrogen")

    def test_a_current_model_missing_from_the_list_is_added(self):
        catalog = ModelCatalog(CHOICES, "gemini-9-custom")
        self.assertIn("gemini-9-custom", catalog.names)

    def test_switch_by_number(self):
        self.assertEqual(self.catalog.switch("1"), "gemini-3.5-flash-lite")

    def test_switch_by_full_name_ignoring_case(self):
        self.assertEqual(self.catalog.switch("GEMINI-3.6-FLASH"), "gemini-3.6-flash")

    def test_switch_by_part_of_a_name(self):
        self.assertEqual(self.catalog.switch("lite"), "gemini-3.5-flash-lite")

    def test_part_of_a_name_matching_two_models_is_refused(self):
        with self.assertRaises(InvalidInputError):
            self.catalog.switch("flash")

    def test_unknown_model_is_refused_and_the_current_one_kept(self):
        with self.assertRaises(InvalidInputError):
            self.catalog.switch("gpt-4")
        self.assertEqual(self.catalog.current, "gemini-4-hydrogen")

    def test_number_out_of_range_is_refused(self):
        with self.assertRaises(InvalidInputError):
            self.catalog.switch("9")

    def test_next_moves_down_the_list_and_wraps_around(self):
        self.assertEqual(self.catalog.switch("next"), "gemini-3.6-flash")
        self.assertEqual(self.catalog.switch("next"), "gemini-3.5-flash-lite")

    def test_next_skips_a_model_that_reached_its_daily_limit(self):
        self.catalog.mark_exhausted("gemini-3.6-flash")
        self.assertEqual(self.catalog.switch("next"), "gemini-3.5-flash-lite")

    def test_next_fails_when_every_other_model_is_used_up(self):
        self.catalog.mark_exhausted("gemini-3.6-flash")
        self.catalog.mark_exhausted("gemini-3.5-flash-lite")
        with self.assertRaises(InvalidInputError):
            self.catalog.switch("next")

    def test_best_available_is_the_first_usable_model_in_the_list(self):
        self.assertEqual(self.catalog.best_available(), "gemini-3.5-flash-lite")
        self.catalog.mark_exhausted("gemini-3.5-flash-lite")
        self.assertEqual(self.catalog.best_available(), "gemini-3.6-flash")

    def test_temporary_marks_can_be_cleared_but_daily_limits_stay(self):
        self.catalog.mark_unavailable("gemini-3.6-flash", ModelCatalog.NOT_RESPONDING)
        self.catalog.mark_exhausted("gemini-3.5-flash-lite")
        self.catalog.clear_temporary()
        self.assertTrue(self.catalog.is_available("gemini-3.6-flash"))
        self.assertFalse(self.catalog.is_available("gemini-3.5-flash-lite"))

    def test_describe_marks_the_model_in_use_and_the_used_up_one(self):
        self.catalog.mark_exhausted("gemini-3.6-flash")
        text = self.catalog.describe()
        self.assertIn("2. gemini-4-hydrogen (in use)", text)
        self.assertIn("3. gemini-3.6-flash (daily limit reached)", text)


class TestSwitchingInTheApp(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)      # keeps ADK's own warnings out of the test output
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {"GOOGLE_API_KEY": "test-key", "BUDDYAI_MODELS": ",".join(CHOICES)},
        )
        self._env.start()
        self.app = BuddyApp(
            data_dir=self._tmp.name, model=_RecordingLlm(model="gemini-4-hydrogen")
        )

    def tearDown(self):
        self.app.close()
        self._env.stop()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_all_five_agents_share_one_model_object(self):
        root = self.app.root_agent
        for agent in root.sub_agents:
            self.assertIs(agent.model, root.model)

    def test_model_command_lists_the_models(self):
        reply = self.app.ask("/model")
        self.assertIn("Current model: gemini-4-hydrogen", reply)
        self.assertIn("1. gemini-3.5-flash-lite", reply)

    def test_model_command_switches_and_the_next_request_uses_the_new_model(self):
        self.assertIn("Switched to gemini-3.5-flash-lite", self.app.ask("/model 1"))
        self.assertEqual(self.app.ask("hello"), "answered by gemini-3.5-flash-lite")

    def test_switching_also_changes_the_file_reading_model(self):
        self.app.ask("/model lite")
        self.assertEqual(self.app._document_reader.model, "gemini-3.5-flash-lite")

    def test_unknown_model_gives_a_message_and_changes_nothing(self):
        reply = self.app.ask("/model gpt-4")
        self.assertIn("Unknown model", reply)
        self.assertEqual(self.app.current_model, "gemini-4-hydrogen")

    def test_model_command_works_without_an_api_key(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}):
            self.assertIn("Switched to", self.app.ask("/model next"))

    def test_an_ordinary_message_is_not_treated_as_a_command(self):
        self.assertIsNone(self.app.handle_command("which model is best for essays?"))


class TestSwitchingInTheBrowserChat(unittest.TestCase):
    """The ADK web UI never calls BuddyApp.ask, so the coordinator's
    before-model hook must answer /model itself."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {"BUDDYAI_MODELS": ",".join(CHOICES)})
        self._env.start()
        self.app = BuddyApp(
            data_dir=self._tmp.name, model=_RecordingLlm(model="gemini-4-hydrogen")
        )
        self.hook = self.app.root_agent.before_model_callback

    def tearDown(self):
        self.app.close()
        self._env.stop()
        self._tmp.cleanup()

    def test_hook_answers_the_model_command_without_a_model_call(self):
        response = self.hook(None, _user_request("/model 3"))
        self.assertIn("Switched to gemini-3.6-flash", response.content.parts[0].text)
        self.assertEqual(self.app.root_agent.model.model, "gemini-3.6-flash")

    def test_hook_lets_an_ordinary_message_through(self):
        self.assertIsNone(self.hook(None, _user_request("add a task to buy milk")))


class TestAutomaticSwitchOnDailyLimit(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)      # the simulated failure is expected
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "test-key",
                "BUDDYAI_MODELS": ",".join(CHOICES),
                "BUDDYAI_AUTO_SWITCH": "",          # unset means on
            },
        )
        self._env.start()
        self.app = self._open("gemini-4-hydrogen")

    def _open(self, model_name):
        return BuddyApp(data_dir=self._tmp.name, model=_LimitedOnHydrogen(model=model_name))

    def tearDown(self):
        self.app.close()
        self._env.stop()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_the_reply_says_which_model_ran_out_and_which_took_over(self):
        reply = self.app.ask("hello")
        self.assertIn(
            "gemini-4-hydrogen has reached today's free request limit, "
            "so I switched to gemini-3.5-flash-lite.",
            reply,
        )

    def test_the_same_message_is_answered_without_sending_it_again(self):
        self.assertTrue(self.app.ask("hello").endswith("answered by gemini-3.5-flash-lite"))

    def test_it_moves_to_the_best_usable_model_in_the_list(self):
        self.app.ask("hello")
        self.assertEqual(self.app.current_model, "gemini-3.5-flash-lite")

    def test_later_replies_carry_no_switch_note(self):
        self.app.ask("hello")
        self.assertEqual(self.app.ask("hello"), "answered by gemini-3.5-flash-lite")

    def test_the_used_up_model_is_marked_in_the_list(self):
        self.app.ask("hello")
        self.assertIn("gemini-4-hydrogen (daily limit reached)", self.app.ask("/model"))

    def test_the_user_can_still_pick_a_model_by_hand(self):
        self.app.ask("hello")
        self.assertIn("Switched to gemini-3.6-flash", self.app.ask("/model 3"))
        self.assertEqual(self.app.ask("hello"), "answered by gemini-3.6-flash")

    def test_picking_the_used_up_model_by_hand_explains_what_will_happen(self):
        self.app.ask("hello")
        reply = self.app.ask("/model hydrogen")
        self.assertIn("it has reached today's free request limit", reply)
        self.assertIn("BuddyAI will move to the next usable model", reply)

    def test_a_message_sent_to_a_known_used_up_model_is_moved_first(self):
        self.app.ask("hello")
        self.app.ask("/model hydrogen")
        reply = self.app.ask("hello")
        self.assertIn("so I switched to gemini-3.5-flash-lite.", reply)
        self.assertTrue(reply.endswith("answered by gemini-3.5-flash-lite"))

    def test_reopening_starts_on_a_usable_model_and_says_so(self):
        self.app.ask("hello")
        self.app.close()
        self.app = self._open("gemini-4-hydrogen")
        self.assertEqual(self.app.current_model, "gemini-3.5-flash-lite")
        self.assertIn(
            "gemini-4-hydrogen reached today's free request limit earlier, so "
            "BuddyAI is starting on gemini-3.5-flash-lite.",
            self.app.startup_notice(),
        )

    def test_in_the_browser_the_start_note_arrives_with_the_first_reply(self):
        self.app.ask("hello")
        self.app.close()
        self.app = self._open("gemini-4-hydrogen")      # startup_notice() is never called
        reply = self.app.ask("hello")
        self.assertIn("BuddyAI is starting on gemini-3.5-flash-lite.", reply)
        self.assertTrue(reply.endswith("answered by gemini-3.5-flash-lite"))


if __name__ == "__main__":
    unittest.main()
