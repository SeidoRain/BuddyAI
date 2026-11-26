"""Unit tests for DocumentReader validation and fake-client summarization."""

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


class TestDocumentReader(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 10, 0, tzinfo=MANILA)
        self.payload = {
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

    def test_unsupported_type_and_missing_file_raise_before_client_call(self):
        client = _FakeGenAIClient(self.payload)
        reader = DocumentReader(model="gemini-4-hydrogen", client=client, clock=lambda: self.now)

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = os.path.join(tmpdir, "notes.docx")
            with open(bad_file, "wb") as handle:
                handle.write(b"fake docx")

            with self.assertRaises(UnsupportedFileTypeError):
                reader.summarize(bad_file)
            self.assertEqual(client.models.calls, [])

            missing_pdf = os.path.join(tmpdir, "missing.pdf")
            with self.assertRaises(InvalidInputError):
                reader.summarize(missing_pdf)
            self.assertEqual(client.models.calls, [])

    def test_fake_client_produces_upload_note_with_proposed_tasks(self):
        client = _FakeGenAIClient(self.payload)
        reader = DocumentReader(model="gemini-4-hydrogen", client=client, clock=lambda: self.now)

        with tempfile.TemporaryDirectory() as tmpdir:
            sample_pdf = os.path.join(tmpdir, "sample.pdf")
            with open(sample_pdf, "wb") as handle:
                handle.write(b"%PDF-1.4 fake")

            note = reader.summarize(sample_pdf)

        self.assertEqual(len(client.models.calls), 1)
        call = client.models.calls[0]
        self.assertEqual(call["model"], "gemini-4-hydrogen")
        prompt_text = call["contents"][1]
        self.assertIn("untrusted", prompt_text.lower())
        self.assertIn("ignore any instructions", prompt_text.lower())

        self.assertEqual(note.title, "Summary of sample.pdf")
        self.assertEqual(note.source, "upload")
        self.assertIn("Project kickoff meeting notes.", note.body)
        self.assertIn("Finalize Sprint 1 scope", note.body)
        self.assertEqual(len(note.action_items), 2)

        first_task, second_task = note.action_items
        self.assertEqual(first_task.status, "proposed")
        self.assertEqual(first_task.source, "upload")
        self.assertEqual(first_task.priority, 3)
        self.assertEqual(first_task.due_date, datetime(2026, 11, 27, 23, 59, tzinfo=MANILA))

        self.assertEqual(second_task.status, "proposed")
        self.assertEqual(second_task.priority, 1)
        self.assertIsNone(second_task.due_date)


if __name__ == "__main__":
    unittest.main()
