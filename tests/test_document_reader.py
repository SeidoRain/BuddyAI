"""Unit tests for DocumentReader validation, prompt safety, and task extraction."""

from datetime import datetime
import json
import os
import tempfile
import unittest
import zipfile
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
        bad_file = os.path.join(self._tmp.name, "notes.doc")
        with open(bad_file, "wb") as handle:
            handle.write(b"old Word format")
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


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _write_docx(path, body_xml, include_body=True):
    """Write a minimal Word file: a zip holding word/document.xml."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if include_body:
            archive.writestr(
                "word/document.xml",
                f'<w:document xmlns:w="{_WORD_NS}"><w:body>{body_xml}</w:body></w:document>',
            )


def _paragraph(text):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


class TestDocxReading(unittest.TestCase):
    """Checks that a Word file's text, not the file itself, is sent to the model."""

    def setUp(self):
        self.now = datetime(2026, 11, 27, 10, 0, tzinfo=MANILA)
        self._tmp = tempfile.TemporaryDirectory()
        self.client = _FakeGenAIClient(
            {"summary": "Thesis notes.", "key_points": [], "action_items": []}
        )
        self.reader = DocumentReader(
            model="gemini-3.5-flash-lite", client=self.client, clock=lambda: self.now
        )
        self.path = os.path.join(self._tmp.name, "notes.docx")

    def tearDown(self):
        self._tmp.cleanup()

    def _sent_text(self):
        part = self.client.models.calls[0]["contents"][0]
        return part.inline_data.mime_type, part.inline_data.data.decode("utf-8")

    def test_a_docx_file_passes_validation(self):
        _write_docx(self.path, _paragraph("Hello"))
        abs_path, mime_type = self.reader.validate_file(self.path)
        self.assertEqual(mime_type, DocumentReader.DOCX_TYPE)

    def test_the_text_is_sent_as_plain_text_one_line_per_paragraph(self):
        _write_docx(self.path, _paragraph("Thesis meeting") + _paragraph("Submit draft by Friday"))
        self.reader.summarize(self.path)
        mime_type, text = self._sent_text()
        self.assertEqual(mime_type, "text/plain")
        self.assertEqual(text, "Thesis meeting\nSubmit draft by Friday")

    def test_text_split_across_runs_is_joined(self):
        _write_docx(self.path, "<w:p><w:r><w:t>Book a </w:t></w:r><w:r><w:t>room</w:t></w:r></w:p>")
        self.reader.summarize(self.path)
        self.assertEqual(self._sent_text()[1], "Book a room")

    def test_table_cells_are_read(self):
        table = (
            "<w:tbl><w:tr><w:tc>" + _paragraph("Owner")
            + "</w:tc><w:tc>" + _paragraph("Ana") + "</w:tc></w:tr></w:tbl>"
        )
        _write_docx(self.path, table)
        self.reader.summarize(self.path)
        self.assertEqual(self._sent_text()[1], "Owner\nAna")

    def test_deleted_text_from_tracked_changes_is_left_out(self):
        body = (
            "<w:p><w:r><w:t>Due Friday</w:t></w:r>"
            "<w:del><w:r><w:delText> Monday</w:delText></w:r></w:del></w:p>"
        )
        _write_docx(self.path, body)
        self.reader.summarize(self.path)
        self.assertEqual(self._sent_text()[1], "Due Friday")

    def test_the_note_is_named_after_the_word_file(self):
        _write_docx(self.path, _paragraph("Hello"))
        note = self.reader.summarize(self.path)
        self.assertEqual(note.title, "Summary of notes.docx")

    def test_a_file_that_is_not_a_zip_is_refused_without_calling_the_model(self):
        with open(self.path, "wb") as handle:
            handle.write(b"plain bytes, not a Word file")
        with self.assertRaises(InvalidInputError):
            self.reader.summarize(self.path)
        self.assertEqual(self.client.models.calls, [])

    def test_a_zip_without_a_document_body_is_refused(self):
        _write_docx(self.path, "", include_body=False)
        with self.assertRaises(InvalidInputError):
            self.reader.summarize(self.path)
        self.assertEqual(self.client.models.calls, [])

    def test_a_document_with_no_text_is_refused(self):
        _write_docx(self.path, "<w:p></w:p>")
        with self.assertRaises(InvalidInputError) as ctx:
            self.reader.summarize(self.path)
        self.assertIn("no text", str(ctx.exception))

    def test_a_document_with_a_dtd_is_refused_before_parsing(self):
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<!DOCTYPE x [<!ENTITY a "aaaa">]>'
                f'<w:document xmlns:w="{_WORD_NS}"><w:body>{_paragraph("&a;")}</w:body></w:document>',
            )
        with self.assertRaises(InvalidInputError):
            self.reader.summarize(self.path)
        self.assertEqual(self.client.models.calls, [])

    def test_an_uploaded_word_file_is_recognised_by_its_type(self):
        self.assertEqual(
            DocumentReader.extension_for("", DocumentReader.DOCX_TYPE), ".docx"
        )

    def test_the_old_doc_format_is_still_unsupported(self):
        with open(os.path.join(self._tmp.name, "old.doc"), "wb") as handle:
            handle.write(b"x")
        with self.assertRaises(UnsupportedFileTypeError):
            self.reader.validate_file(os.path.join(self._tmp.name, "old.doc"))


if __name__ == "__main__":
    unittest.main()
