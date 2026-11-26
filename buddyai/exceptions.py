"""Custom exception hierarchy for BuddyAI domain and persistence errors."""


# Inheritance: common base class so callers and tools can catch any domain error.
class BuddyError(Exception):
    """Base exception for all expected BuddyAI errors."""


# Inheritance: raised when a request to the AI model fails (busy, quota, network).
class ModelRequestError(BuddyError):
    """Raised when the AI model could not answer a request."""


# Inheritance: raised when a task ID or title matches no task.
class TaskNotFoundError(BuddyError):
    """Raised when a requested task cannot be found."""


# Inheritance: raised when a meeting ID or title matches no meeting.
class MeetingNotFoundError(BuddyError):
    """Raised when a requested meeting cannot be found."""


# Encapsulation: stores a copy of matching items behind a read-only property.
class AmbiguousItemError(BuddyError):
    """Raised when a title lookup matches more than one item."""

    def __init__(self, message, matches=None):
        super().__init__(message)
        self._matches = list(matches) if matches else []

    @property
    def matches(self):
        return list(self._matches)


# Inheritance: separates due-date validation errors from general input errors.
class InvalidDueDateError(BuddyError):
    """Raised when a task due date is in the past or cannot be parsed."""


# Inheritance: raised for invalid titles, priorities, time ranges, or missing files.
class InvalidInputError(BuddyError):
    """Raised when user or caller input fails domain validation."""


# Encapsulation: carries conflicting meetings and a suggested free start slot.
class SchedulingConflictError(BuddyError):
    """Raised when a meeting overlaps one or more existing meetings."""

    def __init__(self, message, conflicts=None, suggested_start=None):
        super().__init__(message)
        self._conflicts = list(conflicts) if conflicts else []
        self._suggested_start = suggested_start

    @property
    def conflicts(self):
        return list(self._conflicts)

    @property
    def suggested_start(self):
        return self._suggested_start


# Inheritance: raised when a document path has an unsupported file extension.
class UnsupportedFileTypeError(BuddyError):
    """Raised when a file is not a supported PDF, PNG, JPG, or TXT file."""


# Inheritance: base exception for local and external data source failures.
class DataSourceError(BuddyError):
    """Raised when reading from or writing to a data source fails."""


# Inheritance: raised when code attempts to modify a read-only data source.
class ReadOnlySourceError(DataSourceError):
    """Raised when a write operation is attempted on a read-only data source."""


# Inheritance: defined in Sprint 1 for Sprint 2 external Google authentication.
class AuthenticationRequiredError(DataSourceError):
    """Raised when external source sign-in is missing or expired."""
