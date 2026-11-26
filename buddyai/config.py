"""Configuration and timezone-aware date/time helpers for BuddyAI."""

from datetime import date, datetime, time
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from buddyai.exceptions import InvalidDueDateError, InvalidInputError

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_ROOT, "buddy_agent", ".env")
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.6-flash"
DEFAULT_VOICE_MODEL = "gemini-3.8-live"
DEFAULT_TIMEZONE = "Asia/Manila"
DEFAULT_WEATHER_LOCATION = "Manila"
# Models BuddyAI may use, in order. When one runs out of free requests
# BuddyAI moves to the first one in this list that still works, and the user
# can pick any of them with /model. Free daily limits seen on 2026-11-24:
# 500 requests for each Flash Lite model, 20 for Hydrogen and the Flash models.
# The second Flash Lite model comes next, so a per-minute limit on the first
# moves BuddyAI to the other 500-per-day model, not to a 20-per-day one.
DEFAULT_MODEL_CHOICES = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
]
# Longest a single request to Gemini may take before it is abandoned, so a call
# that never answers cannot freeze the chat. The SDK's own retry option is not
# used: in google-genai 2.34 it hangs when a model answers "503 high demand".
REQUEST_TIMEOUT_SECONDS = 45
# Reading a long PDF takes much longer than a chat reply.
DOCUMENT_TIMEOUT_SECONDS = 180


def get_api_key():
    """Return the configured Google Gemini API key, or an empty string."""
    return os.environ.get("GOOGLE_API_KEY", "").strip()


def get_model():
    """Return the configured model name for BuddyAI agents."""
    value = os.environ.get("BUDDYAI_MODEL", "").strip()
    return value if value else DEFAULT_MODEL


def get_model_choices():
    """Return the models offered by /model: BUDDYAI_MODELS, or the default list."""
    value = os.environ.get("BUDDYAI_MODELS", "").strip()
    if not value:
        return list(DEFAULT_MODEL_CHOICES)
    return [name.strip() for name in value.split(",") if name.strip()]


def get_auto_switch():
    """Return True if BuddyAI may change models by itself (BUDDYAI_AUTO_SWITCH).

    On by default. Set it to 0 to be told the model is used up and choose the
    next one yourself.
    """
    value = os.environ.get("BUDDYAI_AUTO_SWITCH", "").strip().lower()
    return value not in ("0", "false", "no", "off")


def get_doc_model():
    """Return the configured model name for DocumentReader."""
    value = os.environ.get("BUDDYAI_DOC_MODEL", "").strip()
    return value if value else get_model()


def get_voice_model():
    """Return the configured Gemini Live model name for voice mode."""
    value = os.environ.get("BUDDYAI_VOICE_MODEL", "").strip()
    return value if value else DEFAULT_VOICE_MODEL


def _resolve_path(value):
    """Resolve a path setting: keep absolute paths, join relative ones to PROJECT_ROOT."""
    if os.path.isabs(value):
        return value
    return os.path.abspath(os.path.join(PROJECT_ROOT, value))


def get_data_dir():
    """Return the directory where JSON persistence files are stored."""
    value = os.environ.get("BUDDYAI_DATA_DIR", "").strip()
    if not value:
        return os.path.join(PROJECT_ROOT, "data")
    return _resolve_path(value)


def get_ics_file():
    """Return the configured iCalendar (.ics) file path, or an empty string."""
    value = os.environ.get("BUDDYAI_ICS_FILE", "").strip()
    if not value:
        return ""
    return _resolve_path(value)


def get_timezone_name():
    """Return the configured IANA timezone name."""
    value = os.environ.get("BUDDYAI_TIMEZONE", "").strip()
    return value if value else DEFAULT_TIMEZONE


def get_weather_location():
    """Return the configured default city or place name for weather briefings."""
    value = os.environ.get("BUDDYAI_LOCATION", "").strip()
    return value if value else DEFAULT_WEATHER_LOCATION


def get_timezone():
    """Return the configured ZoneInfo object."""
    tz_name = get_timezone_name()
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise InvalidInputError(f"Unknown timezone '{tz_name}'.") from exc


def default_clock():
    """Return the current timezone-aware datetime in the configured timezone."""
    return datetime.now(get_timezone())


def ensure_aware(dt, tz=None, error_cls=InvalidInputError):
    """Validate that dt is a timezone-aware datetime and optionally convert tz."""
    if not isinstance(dt, datetime):
        raise error_cls("Expected a datetime value.")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise error_cls("Datetime must be timezone-aware.")
    if tz is not None:
        return dt.astimezone(tz)
    return dt


def parse_date(text):
    """Parse a YYYY-MM-DD string into a date object."""
    if not isinstance(text, str) or not text.strip():
        raise InvalidInputError("Date cannot be empty. Use YYYY-MM-DD.")
    cleaned = text.strip()
    if len(cleaned) != 10 or cleaned[4] != "-" or cleaned[7] != "-":
        raise InvalidInputError(
            f"Could not read date '{text}'. Use YYYY-MM-DD."
        )
    try:
        return date.fromisoformat(cleaned)
    except ValueError as exc:
        raise InvalidInputError(
            f"Could not read date '{text}'. Use YYYY-MM-DD."
        ) from exc


def parse_time(text):
    """Parse an HH:MM (or HH:MM:SS) string into a time object."""
    if not isinstance(text, str) or not text.strip():
        raise InvalidInputError("Time cannot be empty. Use HH:MM.")
    cleaned = text.strip()
    if ":" not in cleaned:
        raise InvalidInputError(
            f"Could not read time '{text}'. Use HH:MM."
        )
    try:
        parsed = time.fromisoformat(cleaned)
    except ValueError as exc:
        raise InvalidInputError(
            f"Could not read time '{text}'. Use HH:MM."
        ) from exc
    if parsed.tzinfo is not None:
        raise InvalidInputError(
            f"Time '{text}' must not include a timezone offset. Use HH:MM."
        )
    return parsed


def _parse_iso_datetime(text, tz, error_cls, allow_date_only):
    """Parse an ISO date or datetime string into an aware datetime."""
    if not isinstance(text, str) or not text.strip():
        raise error_cls("Date/time cannot be empty.")
    cleaned = text.strip()
    zone = tz if tz is not None else get_timezone()

    is_date_only = (
        len(cleaned) == 10 and cleaned[4] == "-" and cleaned[7] == "-"
    )
    if is_date_only:
        if not allow_date_only:
            raise error_cls(
                f"Date '{text}' must include a time. Use YYYY-MM-DDTHH:MM."
            )
        try:
            parsed_date = date.fromisoformat(cleaned)
        except ValueError as exc:
            raise error_cls(
                f"Could not read date '{text}'. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM."
            ) from exc
        return datetime.combine(parsed_date, time(23, 59), tzinfo=zone)

    if "T" not in cleaned and " " not in cleaned:
        raise error_cls(
            f"Could not read date/time '{text}'. Use YYYY-MM-DDTHH:MM."
        )

    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise error_cls(
            f"Could not read date/time '{text}'. Use YYYY-MM-DDTHH:MM."
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def parse_due_date(text, tz=None):
    """Parse a task due date (YYYY-MM-DD or YYYY-MM-DDTHH:MM) into an aware datetime."""
    return _parse_iso_datetime(
        text,
        tz=tz,
        error_cls=InvalidDueDateError,
        allow_date_only=True,
    )


def parse_datetime(text, tz=None):
    """Parse a date and time (YYYY-MM-DDTHH:MM) into an aware datetime."""
    return _parse_iso_datetime(
        text,
        tz=tz,
        error_cls=InvalidInputError,
        allow_date_only=False,
    )


def parse_stored_datetime(text, tz=None):
    """Parse a stored ISO datetime string that must already include timezone info."""
    if not isinstance(text, str) or not text.strip():
        raise InvalidInputError("Stored datetime cannot be empty.")
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise InvalidInputError(f"Invalid stored datetime '{text}'.") from exc
    return ensure_aware(parsed, tz=tz, error_cls=InvalidInputError)
