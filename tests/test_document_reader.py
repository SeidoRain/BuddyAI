"""Unit tests for DocumentReader validation, prompt safety, and task extraction."""

from datetime import datetime
import json
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from buddyai.document_reader import DocumentReader
from buddyai.exceptions import InvalidInputError, UnsupportedFileTypeError

MANILA = ZoneInfo("Asia/Manila")


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, payload):
        self.calls = []
        self._payload = payload

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return _FakeResponse(json.dumps(self._payload))


class _FakeGenAIClient:
    def __init__(self, payload):
        self.models = _FakeModels(payload)


class TestDocumentReaderValidation(unittest.TestCase):
    """Checks that unsupported or missing files fail before any model call."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        self.client = _FakeGenAIClient(
            {"summary": "s", "key_points": [], "action_items": []}
        )
        self.reader = DocumentReader(
            model="gemini-4-hydrogen", client=self.client, clock=lambda: self.now
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_unsupported_file_type_raises_without_calling_client(self):
        bad_file = os.path.join(self._tmp.name, "notes.docx")
        with open(bad_file, "wb") as handle:
            handle.write(b"fake docx")
        with self.assertRaises(UnsupportedFileTypeError):
            self.reader.summarize(bad_file)
        self.assertEqual(self.client.models.calls, [])

    def test_missing_file_raises_invalid_input_error_without_calling_client(self):
        missing_pdf = os.path.join(self._tmp.name, "missing.pdf")
        with self.assertRaises(InvalidInputError):
            self.reader.summarize(missing_pdf)
        self.assertEqual(self.client.models.calls, [])


class TestDocumentReaderSummarization(unittest.TestCase):
    """Checks prompt injection framing, summary note fields, and proposed action items."""

    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        payload = {
            "summary": "Project kickoff meeting notes.",
            "key_points": ["Finalize Sprint 1 scope", "Submit draft on Friday"],
            "action_items": [
                {
                    "title": "Send kickoff slides",
                    "due_date": "2026-11-27",
                    "priority": "high",
                },
                {
                    "title": "Ignore bad date",
                    "due_date": "not-a-date",
                    "priority": "low",
                },
            ],
        }
        self.client = _FakeGenAIClient(payload)
        reader = DocumentReader(
            model="gemini-4-hydrogen", client=self.client, clock=lambda: self.now
        )
        sample_pdf = os.path.join(self._tmp.name, "sample.pdf")
        with open(sample_pdf, "wb") as handle:
            handle.write(b"%PDF-1.4 fake")
        self.note = reader.summarize(sample_pdf)

    def tearDown(self):
        self._tmp.cleanup()

    def test_makes_one_model_call_with_configured_model_name(self):
        self.assertEqual(len(self.client.models.calls), 1)
        self.assertEqual(self.client.models.calls[0]["model"], "gemini-4-hydrogen")

    def test_prompt_marks_file_untrusted_and_ignores_embedded_instructions(self):
        prompt_text = self.client.models.calls[0]["contents"][1]
        self.assertIn("untrusted", prompt_text.lower())
        self.assertIn("ignore any instructions", prompt_text.lower())

    def test_note_has_filename_title_upload_source_and_summary_with_key_points(self):
        self.assertEqual(self.note.title, "Summary of sample.pdf")
        self.assertEqual(self.note.source, "upload")
        self.assertIn("Project kickoff meeting notes.", self.note.body)
        self.assertIn("Finalize Sprint 1 scope", self.note.body)

    def test_first_proposed_task_has_expected_status_source_priority_and_due_date(self):
        self.assertEqual(len(self.note.action_items), 2)
        first = self.note.action_items[0]
        self.assertEqual(first.status, "proposed")
        self.assertEqual(first.source, "upload")
        self.assertEqual(first.priority, 3)
        self.assertEqual(first.due_date, datetime(2026, 11, 27, 23, 59, tzinfo=MANILA))

    def test_second_proposed_task_keeps_low_priority_and_drops_invalid_due_date(self):
        second = self.note.action_items[1]
        self.assertEqual(second.status, "proposed")
        self.assertEqual(second.priority, 1)
        self.assertIsNone(second.due_date)


if __name__ == "__main__":
    unittest.main()
