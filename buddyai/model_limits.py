"""ModelLimitLog: remembers which models reached their free daily limit today."""

from datetime import datetime, time, timedelta
import json
import os
import tempfile
from zoneinfo import ZoneInfo


# Encapsulation: hides the small JSON file that lets BuddyAI know, the moment it
# opens, that a model already ran out of free requests earlier the same day.
class ModelLimitLog:
    """Keeps the list of models that hit their daily limit since the last reset."""

    FILE_NAME = "model_limits.json"
    # Google counts a "day" of free requests from midnight US Pacific time.
    RESET_ZONE = "America/Los_Angeles"

    def __init__(self, data_dir, clock):
        self._path = os.path.join(os.fspath(data_dir), self.FILE_NAME)
        self._clock = clock

    def _quota_day(self):
        """Return today's date as Google counts it (US Pacific time)."""
        pacific_now = self._clock().astimezone(ZoneInfo(self.RESET_ZONE))
        return pacific_now.date().isoformat()

    def limited_today(self):
        """Return the models that reached their daily limit since the last reset."""
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []           # no file yet, or unreadable: nothing is known
        if not isinstance(data, dict) or data.get("quota_day") != self._quota_day():
            return []           # the list is from an earlier day, so it has reset
        models = data.get("models")
        if not isinstance(models, list):
            return []           # a damaged list: treat it as empty
        return [name for name in models if isinstance(name, str)]

    def record(self, name):
        """Remember that a model has no free requests left until the next reset."""
        names = self.limited_today()
        if name in names:
            return
        names.append(name)
        folder = os.path.dirname(self._path)
        os.makedirs(folder, exist_ok=True)
        record = {"quota_day": self._quota_day(), "models": names}
        # Same safe-save steps as JsonStore: write a temporary file, then swap it in.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=folder, suffix=".tmp", delete=False
        ) as handle:
            json.dump(record, handle, indent=2)
            temp_path = handle.name
        os.replace(temp_path, self._path)

    def next_reset(self):
        """Return when the daily limits reset next, in the clock's own time zone."""
        now = self._clock()
        zone = ZoneInfo(self.RESET_ZONE)
        tomorrow = now.astimezone(zone).date() + timedelta(days=1)
        return datetime.combine(tomorrow, time(0, 0), tzinfo=zone).astimezone(now.tzinfo)
