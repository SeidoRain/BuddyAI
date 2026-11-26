"""Workspace coordinating managers, data sources, and polymorphic day queries."""

from buddyai.config import ensure_aware
from buddyai.managers.agenda import Agenda
from buddyai.managers.notebook import Notebook
from buddyai.managers.task_manager import TaskManager
from buddyai.models.meeting import Meeting
from buddyai.models.note import Note
from buddyai.models.reminder import Reminder
from buddyai.models.task import Task


# Composition & Aggregation: creates and owns its managers, aggregates external DataSources.
class Workspace:
    """Central coordinator tying TaskManager, Agenda, Notebook, and DataSources together."""

    def __init__(self, sources=None):
        self._tasks = TaskManager()
        self._agenda = Agenda()
        self._notebook = Notebook()
        self._sources = list(sources) if sources else []
        self._synced = []
        self._save_count = 0

    @property
    def save_count(self):
        """How many times save() has run; lets callers notice that data changed."""
        return self._save_count

    @property
    def tasks(self):
        return self._tasks

    @property
    def agenda(self):
        return self._agenda

    @property
    def notebook(self):
        return self._notebook

    @property
    def sources(self):
        return list(self._sources)

    def replace_source(self, source):
        """Replace any source with the same name, then append the given source."""
        self._sources = [
            existing for existing in self._sources if existing.name != source.name
        ]
        self._sources.append(source)

    def remove_source(self, name):
        """Remove any source with the given name; return True if one was removed."""
        before = len(self._sources)
        self._sources = [
            existing for existing in self._sources if existing.name != name
        ]
        return len(self._sources) < before

    def load(self):
        """Rebuild local managers from every writable data source."""
        self._tasks = TaskManager()
        self._agenda = Agenda()
        self._notebook = Notebook()

        for source in self._sources:
            if source.is_read_only:
                continue
            for item in source.fetch_items():
                if isinstance(item, (Task, Reminder)):
                    self._tasks.restore(item)
                elif isinstance(item, Meeting):
                    self._agenda.restore(item)
                elif isinstance(item, Note):
                    self._notebook.restore(item)

    def sync(self):
        """Fetch items from read-only sources and push external meetings to Agenda."""
        synced_items = []
        for source in self._sources:
            if source.is_read_only:
                synced_items.extend(source.fetch_items())
        self._synced = synced_items
        external_meetings = [
            item for item in self._synced if isinstance(item, Meeting)
        ]
        self._agenda.set_external(external_meetings)

    def _local_items(self):
        items = []
        items.extend(self._tasks.list_all_tasks())
        items.extend(self._tasks.list_reminders())
        items.extend(self._agenda.list_local_meetings())
        items.extend(self._notebook.list_notes())
        return items

    def save(self):
        """Write all local items to every writable data source (never synced items)."""
        local_items = self._local_items()
        for source in self._sources:
            if not source.is_read_only:
                source.save_all(local_items)
        self._save_count += 1

    def all_items(self):
        """Return every local and synced item held by the workspace."""
        items = self._local_items()
        items.extend(self._synced)
        return items

    # Polymorphism: iterates mixed WorkItems with no type checks using is_due/priority_score.
    def items_for_day(self, now):
        """Return all local and synced items due on now's day, highest score first."""
        aware_now = ensure_aware(now)
        due_items = [item for item in self.all_items() if item.is_due(aware_now)]
        return sorted(
            due_items,
            key=lambda item: (-item.priority_score(aware_now), item.title.lower()),
        )
