"""Abstract DataSource interface for reading and optionally writing work items."""

from abc import ABC, abstractmethod

from buddyai.exceptions import ReadOnlySourceError


# Abstraction: defines a uniform source contract; defaults to read-only writes.
class DataSource(ABC):
    """Abstract source of WorkItem records (read-only unless overridden)."""

    def __init__(self, name):
        self._name = str(name)

    @property
    def name(self):
        return self._name

    @property
    def is_read_only(self):
        return True

    @abstractmethod
    def fetch_items(self):
        """Fetch and return a list of WorkItem instances from this source."""

    def save_item(self, item):
        """Persist a single item; read-only sources raise ReadOnlySourceError."""
        raise ReadOnlySourceError(
            f"Data source '{self._name}' is read-only and cannot save items."
        )

    def remove_item(self, item_id):
        """Delete an item by ID; read-only sources raise ReadOnlySourceError."""
        raise ReadOnlySourceError(
            f"Data source '{self._name}' is read-only and cannot remove items."
        )

    def save_all(self, items):
        """Persist a full collection of items; read-only sources raise ReadOnlySourceError."""
        raise ReadOnlySourceError(
            f"Data source '{self._name}' is read-only and cannot save items."
        )
