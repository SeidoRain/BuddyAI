"""Notebook manager owning Note objects and keyword search."""

from buddyai.exceptions import InvalidInputError
from buddyai.models.note import Note


# Encapsulation: manages storage, retrieval, and keyword search over Note items.
class Notebook:
    """Owns the user's notes and document summaries."""

    def __init__(self):
        self._notes = {}

    def add_note(self, note):
        """Add a Note to the notebook."""
        if not isinstance(note, Note):
            raise InvalidInputError("Expected a Note instance.")
        self._notes[note.item_id] = note
        return note

    def search(self, keyword):
        """Return notes whose title or body contains keyword (case-insensitive)."""
        if not isinstance(keyword, str) or not keyword.strip():
            raise InvalidInputError("Search keyword cannot be empty.")
        needle = keyword.strip().lower()
        return [
            note
            for note in self.list_notes()
            if needle in note.title.lower() or needle in note.body.lower()
        ]

    def get_note(self, note_id):
        """Retrieve a note by exact ID or raise InvalidInputError."""
        if not isinstance(note_id, str) or note_id.strip() not in self._notes:
            raise InvalidInputError(f"Note '{note_id}' was not found.")
        return self._notes[note_id.strip()]

    def list_notes(self):
        """Return all notes ordered newest first."""
        return sorted(
            self._notes.values(),
            key=lambda note: note.created_at.timestamp(),
            reverse=True,
        )

    def remove_note(self, note_id):
        """Remove a note by exact ID and return it."""
        note = self.get_note(note_id)
        return self._notes.pop(note.item_id)

    def restore(self, note):
        """Restore a loaded Note without extra checks."""
        if not isinstance(note, Note):
            raise InvalidInputError("Expected a Note instance.")
        self._notes[note.item_id] = note
        return note
