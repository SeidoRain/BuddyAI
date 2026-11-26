"""Daily briefing generation built polymorphically from Workspace items."""

from buddyai.config import ensure_aware


# Encapsulation: wraps the generated briefing date and due WorkItem list.
class DailyBriefing:
    """Represents the user's schedule and due work summary for one day."""

    def __init__(self, day, items):
        self._day = day
        self._items = list(items)

    @property
    def day(self):
        return self._day

    @property
    def items(self):
        return list(self._items)

    def to_text(self):
        """Render the daily briefing using each item's summarize() method."""
        header = f"Daily Briefing for {self._day.strftime('%A, %B %d, %Y')}"
        if not self._items:
            return f"{header}\nNothing due or scheduled for today."
        lines = [header]
        for index, item in enumerate(self._items, start=1):
            lines.append(f"{index}. {item.summarize()}")
        return "\n".join(lines)


# Composition/Dependency: queries a Workspace to assemble a DailyBriefing.
class BriefingService:
    """Builds DailyBriefing summaries from local and synced Workspace items."""

    def __init__(self, workspace):
        self._workspace = workspace

    def build_briefing(self, now):
        """Collect due items for now's date and return a DailyBriefing."""
        aware_now = ensure_aware(now)
        items = self._workspace.items_for_day(aware_now)
        return DailyBriefing(day=aware_now.date(), items=items)
