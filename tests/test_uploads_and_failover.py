"""Unit tests for files attached in the browser chat and for moving off a model
that is busy or silent."""

import logging
import os
import tempfile
import unittest
from unittest.mock import patch

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from buddyai.agents.patient_gemini import PatientGemini
from buddyai.app import BuddyApp
from buddyai.document_reader import DocumentReader
from buddyai.exceptions import ModelRequestError

CHOICES = ["gemini-3.5-flash-lite", "gemini-4-hydrogen", "gemini-3.6-flash"]
PDF_BYTES = b"%PDF-1.4 sample brief"


class _Echo(BaseLlm):
    """Stand-in model that repeats the last user text it was given."""

    async def generate_content_async(self, llm_request, stream=False):
        text = ""
        for content in llm_request.contents:
            for part in content.parts or []:
                if content.role == "user" and part.text:
                    text = part.text
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )


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


class _BusyOnHydrogen(BaseLlm):
    """Stand-in model whose 'gemini-4-hydrogen' always answers 'high demand'."""

    async def generate_content_async(self, llm_request, stream=False):
        if llm_request.model == "gemini-4-hydrogen":
            raise _BusyError()
        text = f"answered by {llm_request.model}"
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )


def _request_with_file(data, mime_type, name):
    blob = types.Blob(data=data, mime_type=mime_type, display_name=name)
    parts = [types.Part(text="summarize"), types.Part(inline_data=blob)]
    return LlmRequest(contents=[types.Content(role="user", parts=parts)])


class TestFilesAttachedInTheBrowserChat(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app = BuddyApp(data_dir=self._tmp.name, model=_Echo(model="echo"))
        self.uploads = os.path.join(self._tmp.name, "uploads")
        self.hook = self.app.root_agent.before_model_callback

    def tearDown(self):
        self.app.close()
        self._tmp.cleanup()

    def test_a_pdf_is_saved_and_replaced_by_its_path(self):
        note = self.app.save_upload(PDF_BYTES, "application/pdf", "client brief.pdf")
        self.assertTrue(note.startswith("Attached file path to summarize: "))
        path = note.split(": ", 1)[1]
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), PDF_BYTES)

    def test_the_saved_name_keeps_the_original_name_and_extension(self):
        note = self.app.save_upload(PDF_BYTES, "application/pdf", "client brief.pdf")
        filename = os.path.basename(note.split(": ", 1)[1])
        self.assertTrue(filename.startswith("client brief-"))
        self.assertTrue(filename.endswith(".pdf"))

    def test_the_same_file_is_stored_only_once(self):
        self.app.save_upload(PDF_BYTES, "application/pdf", "brief.pdf")
        self.app.save_upload(PDF_BYTES, "application/pdf", "brief.pdf")
        self.assertEqual(len(os.listdir(self.uploads)), 1)

    def test_a_file_without_a_name_gets_one_from_its_type(self):
        note = self.app.save_upload(b"\x89PNG data", "image/png", "")
        self.assertTrue(note.endswith(".png"))

    def test_an_unsupported_type_is_not_saved(self):
        note = self.app.save_upload(b"PK data", "application/zip", "archive.zip")
        self.assertIn("can only read PDF, PNG, JPG and TXT", note)
        self.assertFalse(os.path.isdir(self.uploads))

    def test_hook_swaps_the_attached_file_for_text_before_the_model_sees_it(self):
        request = _request_with_file(PDF_BYTES, "application/pdf", "brief.pdf")
        self.assertIsNone(self.hook(None, request))
        parts = request.contents[0].parts
        self.assertIsNone(parts[1].inline_data)
        self.assertIn("Attached file path to summarize: ", parts[1].text)

    def test_hook_leaves_a_plain_message_untouched(self):
        request = LlmRequest(
            contents=[types.Content(role="user", parts=[types.Part(text="hello")])]
        )
        self.hook(None, request)
        self.assertEqual(request.contents[0].parts[0].text, "hello")


class TestMovingOffABusyModel(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)      # the simulated failure is expected
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {"GOOGLE_API_KEY": "test-key", "BUDDYAI_MODELS": ",".join(CHOICES)},
        )
        self._env.start()
        self.app = BuddyApp(
            data_dir=self._tmp.name, model=_BusyOnHydrogen(model="gemini-4-hydrogen")
        )

    def tearDown(self):
        self.app.close()
        self._env.stop()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_the_reply_says_the_busy_model_was_left(self):
        reply = self.app.ask("hello")
        self.assertIn(
            "gemini-4-hydrogen is not responding right now, "
            "so I switched to gemini-3.5-flash-lite.",
            reply,
        )

    def test_the_same_message_is_answered_by_the_next_best_model(self):
        self.assertTrue(self.app.ask("hello").endswith("answered by gemini-3.5-flash-lite"))
        self.assertEqual(self.app.current_model, "gemini-3.5-flash-lite")

    def test_the_busy_model_is_marked_in_the_list(self):
        self.app.ask("hello")
        self.assertIn("gemini-4-hydrogen (not responding)", self.app.ask("/model"))

    def test_choosing_the_busy_model_again_clears_its_mark(self):
        self.app.ask("hello")
        self.app.ask("/model hydrogen")
        self.assertIn("gemini-4-hydrogen (in use)", self.app.ask("/model"))

    def test_next_skips_the_busy_model(self):
        self.app.ask("hello")                       # now on gemini-3.5-flash-lite
        self.app.ask("/model next")
        self.assertEqual(self.app.current_model, "gemini-3.6-flash")


class _OnlyFlashAnswers(BaseLlm):
    """Stand-in: Hydrogen is used up for the day, Flash Lite is busy, 3.6 Flash answers."""

    async def generate_content_async(self, llm_request, stream=False):
        if llm_request.model == "gemini-4-hydrogen":
            raise _DailyLimitError()
        if llm_request.model == "gemini-3.5-flash-lite":
            raise _BusyError()
        text = f"answered by {llm_request.model}"
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )


class _NothingAnswers(BaseLlm):
    """Stand-in: every model is busy."""

    async def generate_content_async(self, llm_request, stream=False):
        raise _BusyError()
        yield                                   # makes this an async generator


class TestFailoverWalksDownTheList(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {"GOOGLE_API_KEY": "test-key", "BUDDYAI_MODELS": ",".join(CHOICES)},
        )
        self._env.start()

    def _open(self, llm):
        self.app = BuddyApp(data_dir=self._tmp.name, model=llm)
        return self.app

    def tearDown(self):
        self.app.close()
        self._env.stop()
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_it_keeps_going_until_a_model_answers(self):
        reply = self._open(_OnlyFlashAnswers(model="gemini-4-hydrogen")).ask("hello")
        self.assertTrue(reply.endswith("answered by gemini-3.6-flash"))

    def test_every_switch_is_reported(self):
        reply = self._open(_OnlyFlashAnswers(model="gemini-4-hydrogen")).ask("hello")
        self.assertIn("so I switched to gemini-3.5-flash-lite.", reply)
        self.assertIn(
            "gemini-3.5-flash-lite is not responding right now, "
            "so I switched to gemini-3.6-flash.",
            reply,
        )

    def test_when_no_model_answers_the_reply_says_so_and_stops(self):
        reply = self._open(_NothingAnswers(model="gemini-4-hydrogen")).ask("hello")
        self.assertIn("Gemini is busy right now", reply)

    def test_a_per_minute_limit_also_moves_to_the_next_model(self):
        class _PerMinute(Exception):
            code = 429

            def __init__(self):
                super().__init__(
                    "429 RESOURCE_EXHAUSTED. GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
                )

        class _RateLimitedHydrogen(BaseLlm):
            async def generate_content_async(self, llm_request, stream=False):
                if llm_request.model == "gemini-4-hydrogen":
                    raise _PerMinute()
                text = f"answered by {llm_request.model}"
                yield LlmResponse(
                    content=types.Content(role="model", parts=[types.Part(text=text)])
                )

        reply = self._open(_RateLimitedHydrogen(model="gemini-4-hydrogen")).ask("hello")
        self.assertIn(
            "gemini-4-hydrogen has reached its requests-per-minute limit, "
            "so I switched to gemini-3.5-flash-lite.",
            reply,
        )


class _FlakyParent:
    """Replaces Gemini.generate_content_async: busy a set number of times, then answers."""

    def __init__(self, failures, error=None):
        self.failures = failures
        self.error = error if error is not None else _BusyError()
        self.calls = 0

    async def __call__(self, llm_request, stream=False):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="ready")])
        )


class TestPatientGemini(unittest.IsolatedAsyncioTestCase):
    async def _ask(self, parent):
        model = PatientGemini(model="gemini-3.5-flash-lite")
        target = "google.adk.models.Gemini.generate_content_async"
        with patch(target, new=parent), patch.object(PatientGemini, "BUSY_WAIT_SECONDS", 0):
            request = LlmRequest(model="gemini-3.5-flash-lite", contents=[])
            return [r async for r in model.generate_content_async(request)]

    async def test_a_busy_answer_is_retried_until_the_model_replies(self):
        parent = _FlakyParent(failures=2)
        responses = await self._ask(parent)
        self.assertEqual(responses[0].content.parts[0].text, "ready")
        self.assertEqual(parent.calls, 3)

    async def test_it_gives_up_after_the_allowed_retries(self):
        parent = _FlakyParent(failures=5)
        with self.assertRaises(_BusyError):
            await self._ask(parent)
        self.assertEqual(parent.calls, 3)

    async def test_other_errors_are_not_retried(self):
        parent = _FlakyParent(failures=5, error=ValueError("bad request"))
        with self.assertRaises(ValueError):
            await self._ask(parent)
        self.assertEqual(parent.calls, 1)


class _BusyModels:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def generate_content(self, model=None, contents=None, config=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise _BusyError()

        class Response:
            text = '{"summary": "A brief.", "key_points": [], "action_items": []}'

        return Response()


class _BusyClient:
    def __init__(self, failures):
        self.models = _BusyModels(failures)


class TestDocumentReaderWhenTheModelIsBusy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "brief.txt")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("brief")
        self._no_wait = patch.object(DocumentReader, "BUSY_WAIT_SECONDS", 0)
        self._no_wait.start()

    def tearDown(self):
        self._no_wait.stop()
        self._tmp.cleanup()

    def test_a_busy_answer_is_retried(self):
        client = _BusyClient(failures=2)
        note = DocumentReader(model="gemini-3.5-flash-lite", client=client).summarize(self.path)
        self.assertEqual(note.body, "A brief.")
        self.assertEqual(client.models.calls, 3)

    def test_a_model_that_stays_busy_raises_a_clear_error(self):
        client = _BusyClient(failures=9)
        with self.assertRaises(ModelRequestError) as caught:
            DocumentReader(model="gemini-3.5-flash-lite", client=client).summarize(self.path)
        self.assertIn("/model next", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
