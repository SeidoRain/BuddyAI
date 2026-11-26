"""Daily briefing generation built polymorphically from Workspace items, weather, and PH headlines."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time

from buddyai.config import (
    ensure_aware,
    get_weather_location,
    parse_date,
    parse_datetime,
    parse_time,
)
from buddyai.exceptions import BuddyError

_USE_NOW = object()


def resolve_briefing_window(now, day="", at_time=""):
    """Resolve optional day/time strings into (briefing_now, weather_at) for a briefing.

    For today's date, `briefing_now` always keeps the real current clock (`now`)
    so tasks and reminders are not falsely marked overdue or passed when asking
    for weather at a later time of day.
    """
    aware_now = ensure_aware(now)
    day_text = (day or "").strip()
    time_text = (at_time or "").strip()

    if time_text and ("T" in time_text or " " in time_text):
        parsed_dt = parse_datetime(time_text, tz=aware_now.tzinfo)
        if day_text:
            target_day = parse_date(day_text)
            weather_at = datetime.combine(target_day, parsed_dt.timetz())
        else:
            target_day = parsed_dt.date()
            weather_at = parsed_dt
    elif time_text:
        parsed_time = parse_time(time_text)
        target_day = parse_date(day_text) if day_text else aware_now.date()
        weather_at = datetime.combine(target_day, parsed_time, tzinfo=aware_now.tzinfo)
    else:
        target_day = parse_date(day_text) if day_text else aware_now.date()
        weather_at = aware_now if target_day == aware_now.date() else target_day

    if target_day == aware_now.date():
        briefing_now = aware_now
    else:
        briefing_now = datetime.combine(target_day, time(0, 0), tzinfo=aware_now.tzinfo)
    return briefing_now, weather_at


# Encapsulation: wraps the generated briefing date, due WorkItem list, weather, and headlines.
class DailyBriefing:
    """Represents the user's schedule, weather summary, and top PH headlines for one day."""

    def __init__(
        self,
        day,
        items,
        now=None,
        weather=None,
        headlines=None,
        weather_error="",
        headlines_error="",
        display_time=_USE_NOW,
    ):
        self._day = day
        self._items = list(items)
        self._now = now
        self._display_time = now if display_time is _USE_NOW else display_time
        self._weather = dict(weather) if weather is not None else None
        self._headlines = (
            [dict(item) for item in headlines] if headlines is not None else None
        )
        self._weather_error = str(weather_error or "")
        self._headlines_error = str(headlines_error or "")

    @property
    def day(self):
        return self._day

    @property
    def display_time(self):
        return self._display_time

    @property
    def items(self):
        return list(self._items)

    @property
    def weather(self):
        return dict(self._weather) if self._weather is not None else None

    @property
    def headlines(self):
        return (
            [dict(item) for item in self._headlines]
            if self._headlines is not None
            else None
        )

    @property
    def weather_error(self):
        return self._weather_error

    @property
    def headlines_error(self):
        return self._headlines_error

    @staticmethod
    def format_headline_label(item):
        """Format a headline's title and source without duplicating trailing source names."""
        title = (item.get("title") or "").strip()
        source = (item.get("source") or "").strip()
        if source and not title.endswith(f"- {source}"):
            return f"{title} ({source})"
        return title

    def schedule_lines(self):
        """Return formatted lines for scheduled meetings, due tasks, and reminders."""
        if not self._items:
            return ["Nothing due or scheduled for today."]
        lines = []
        for index, item in enumerate(self._items, start=1):
            line = f"{index}. {item.summarize()}"
            if self._now is not None:
                note = item.status_note(self._now)
                if note:
                    line = f"{line} [{note}]"
            lines.append(line)
        return lines

    def has_live_sections(self):
        """Return True when weather or headline sections (or their errors) are populated."""
        return (
            self._weather is not None
            or self._headlines is not None
            or bool(self._weather_error)
            or bool(self._headlines_error)
        )

    def header_text(self):
        """Return the briefing header with both date and time when available."""
        date_text = self._day.strftime("%A, %B %d, %Y")
        if isinstance(self._display_time, datetime):
            time_text = self._display_time.strftime("%I:%M %p").lstrip("0")
            return f"Daily Briefing for {date_text} at {time_text}"
        return f"Daily Briefing for {date_text}"

    def to_text(self):
        """Render the daily briefing in canonical Markdown for both /brief and chat replies."""
        header = self.header_text()
        schedule_lines = self.schedule_lines()
        if not self.has_live_sections():
            return "\n".join([header] + schedule_lines)

        sections = [
            f"**{header}**",
            "\n".join(["### Schedule & Due Items"] + schedule_lines),
        ]

        if self._weather is not None:
            sections.append(f"### Weather\n{self._weather.get('summary', '')}")
        elif self._weather_error:
            sections.append(f"### Weather\nUnavailable ({self._weather_error})")

        if self._headlines is not None:
            if self._headlines:
                headline_lines = ["### Top 5 Headlines (Philippines)"]
                for index, item in enumerate(self._headlines, start=1):
                    label = self.format_headline_label(item)
                    url = (item.get("url") or "").strip()
                    if url:
                        safe_label = label.replace("[", r"\[").replace("]", r"\]")
                        headline_lines.append(f"{index}. [{safe_label}]({url})")
                    else:
                        headline_lines.append(f"{index}. {label}")
                sections.append("\n".join(headline_lines))
            else:
                sections.append("### Top 5 Headlines (Philippines)\nNo headlines available.")
        elif self._headlines_error:
            sections.append(
                f"### Top 5 Headlines (Philippines)\nUnavailable ({self._headlines_error})"
            )

        return "\n\n".join(sections)


# Composition/Dependency: queries Workspace and WebLookup to assemble a DailyBriefing.
class BriefingService:
    """Builds DailyBriefing summaries from Workspace items, weather, and PH headlines."""

    HEADLINE_COUNT = 5
    HEADLINE_COUNTRY = "PH"

    def __init__(self, workspace, web_lookup=None, default_location=None):
        self._workspace = workspace
        self._web_lookup = web_lookup
        self._default_location = (default_location or "").strip() or get_weather_location()

    def _fetch_weather(self, place, target_weather_at):
        try:
            return self._web_lookup.get_weather(place, at_time=target_weather_at), ""
        except BuddyError as exc:
            return None, str(exc)

    def _fetch_headlines(self):
        try:
            payload = self._web_lookup.get_headlines(
                limit=self.HEADLINE_COUNT,
                country=self.HEADLINE_COUNTRY,
            )
            return payload.get("headlines", []), ""
        except BuddyError as exc:
            return None, str(exc)

    def build_briefing(self, now, location=None, weather_at=None, include_live=True):
        """Collect due items, weather summary, and top 5 PH headlines into a DailyBriefing."""
        aware_now = ensure_aware(now)
        items = self._workspace.items_for_day(aware_now)

        weather = None
        headlines = None
        weather_error = ""
        headlines_error = ""

        target_weather_at = weather_at if weather_at is not None else aware_now
        display_time = (
            target_weather_at if isinstance(target_weather_at, datetime) else None
        )

        if include_live and self._web_lookup is not None:
            place = (location or "").strip() or self._default_location
            with ThreadPoolExecutor(max_workers=2) as pool:
                weather_future = pool.submit(
                    self._fetch_weather, place, target_weather_at
                )
                headlines_future = pool.submit(self._fetch_headlines)
                weather, weather_error = weather_future.result()
                headlines, headlines_error = headlines_future.result()

        return DailyBriefing(
            day=aware_now.date(),
            items=items,
            now=aware_now,
            weather=weather,
            headlines=headlines,
            weather_error=weather_error,
            headlines_error=headlines_error,
            display_time=display_time,
        )
