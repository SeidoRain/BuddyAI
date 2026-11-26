"""Notebook manager owning Note objects and keyword search."""

from buddyai.exceptions import (
    AmbiguousItemError,
    InvalidInputError,
    NoteNotFoundError,
)
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
        """Retrieve a note by exact ID or raise NoteNotFoundError."""
        if not isinstance(note_id, str) or note_id.strip() not in self._notes:
            raise NoteNotFoundError(f"Note '{note_id}' was not found.")
        return self._notes[note_id.strip()]

    def find_note(self, id_or_title):
        """Find a note by exact ID first, then by exact or partial title."""
        if not isinstance(id_or_title, str) or not id_or_title.strip():
            raise InvalidInputError("Note ID or title cannot be empty.")
        query = id_or_title.strip()
        if query in self._notes:
            return self._notes[query]

        query_lower = query.lower()
        notes = self.list_notes()
        exact_matches = [note for note in notes if note.title.lower() == query_lower]
        partial_matches = [note for note in notes if query_lower in note.title.lower()]
        matches = exact_matches if exact_matches else partial_matches
        if not matches:
            raise NoteNotFoundError(f"No note found matching '{query}'.")
        if len(matches) > 1:
            labels = ", ".join(f"{note.item_id} ({note.title})" for note in matches)
            raise AmbiguousItemError(
                f"Multiple notes match '{query}': {labels}.",
                matches=matches,
            )
        return matches[0]

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
