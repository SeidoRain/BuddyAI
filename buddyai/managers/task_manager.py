"""TaskManager class owning local Task and Reminder collections."""

from buddyai.config import ensure_aware
from buddyai.exceptions import (
    AmbiguousItemError,
    InvalidDueDateError,
    InvalidInputError,
    ReminderNotFoundError,
    TaskNotFoundError,
)
from buddyai.models.reminder import Reminder
from buddyai.models.task import Task


# Encapsulation & Composition: manages task/reminder lifecycles and validation rules.
class TaskManager:
    """Owns tasks and reminders and enforces creation, lookup, and ranking rules."""

    def __init__(self):
        self._tasks = {}
        self._reminders = {}

    def add_task(self, task, now):
        """Add an active task after verifying its due date is not in the past."""
        if not isinstance(task, Task):
            raise InvalidInputError("Expected a Task instance.")
        aware_now = ensure_aware(now, error_cls=InvalidDueDateError)
        if task.due_date is not None and task.due_date < aware_now:
            raise InvalidDueDateError(
                f"Due date {task.due_date.strftime('%Y-%m-%d %H:%M')} is in the past."
            )
        self._tasks[task.item_id] = task
        return task

    def propose(self, task):
        """Store a proposed task without past-date checks."""
        if not isinstance(task, Task):
            raise InvalidInputError("Expected a Task instance.")
        if task.status != "proposed":
            raise InvalidInputError("Only tasks with status 'proposed' can be proposed.")
        self._tasks[task.item_id] = task
        return task

    def confirm(self, task_id):
        """Confirm a proposed task so its status becomes 'open'."""
        task = self.get_task(task_id)
        task.confirm()
        return task

    def confirm_all(self, task_ids):
        """Confirm several proposed tasks, or none of them if any ID is invalid."""
        tasks = []
        for task_id in task_ids:
            task = self.get_task(task_id)
            if task.status != "proposed":
                raise InvalidInputError(
                    f"Task '{task.title}' ({task.item_id}) cannot be confirmed "
                    f"because its status is '{task.status}'."
                )
            if task not in tasks:
                tasks.append(task)
        # Every ID was checked above, so no confirm() below can fail halfway.
        # Assumption: the loop above kept only tasks that are still proposed.
        assert all(task.status == "proposed" for task in tasks)
        for task in tasks:
            task.confirm()
        return tasks

    def get_task(self, task_id):
        """Retrieve a task by exact ID or raise TaskNotFoundError."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise TaskNotFoundError("Task ID cannot be empty.")
        key = task_id.strip()
        if key not in self._tasks:
            raise TaskNotFoundError(f"Task '{key}' was not found.")
        return self._tasks[key]

    @staticmethod
    def _match_by_title(candidates, query, kind):
        """Return the one item whose title matches the query, or None if none do.

        An exact (case-insensitive) title wins over a partial one. Several
        matches at the same level raise AmbiguousItemError.
        """
        query_lower = query.lower()
        exact_matches = [
            item for item in candidates if item.title.lower() == query_lower
        ]
        partial_matches = [
            item for item in candidates if query_lower in item.title.lower()
        ]
        matches = exact_matches if exact_matches else partial_matches
        if len(matches) > 1:
            labels = ", ".join(f"{item.item_id} ({item.title})" for item in matches)
            raise AmbiguousItemError(
                f"Multiple {kind} match '{query}': {labels}.",
                matches=matches,
            )
        if matches:
            return matches[0]
        return None

    def find_task(self, id_or_title, include_done=False):
        """Find a task by exact ID first, then by title among active tasks.

        Done tasks are searched by title only when include_done is True and no
        active task matches.
        """
        if not isinstance(id_or_title, str) or not id_or_title.strip():
            raise InvalidInputError("Task ID or title cannot be empty.")
        query = id_or_title.strip()
        if query in self._tasks:
            return self._tasks[query]

        active = [task for task in self._tasks.values() if task.status != "done"]
        found = self._match_by_title(active, query, "tasks")
        if found is None and include_done:
            done = [task for task in self._tasks.values() if task.status == "done"]
            found = self._match_by_title(done, query, "tasks")
        if found is None:
            scope = "task" if include_done else "active task"
            raise TaskNotFoundError(f"No {scope} found matching '{query}'.")
        return found

    def find_reminder(self, id_or_title):
        """Find a reminder by exact ID first, then by exact or partial title."""
        if not isinstance(id_or_title, str) or not id_or_title.strip():
            raise InvalidInputError("Reminder ID or title cannot be empty.")
        query = id_or_title.strip()
        if query in self._reminders:
            return self._reminders[query]

        found = self._match_by_title(self._reminders.values(), query, "reminders")
        if found is None:
            raise ReminderNotFoundError(f"No reminder found matching '{query}'.")
        return found

    def update_task(self, task_id, title=None, due_date=None, priority=None, now=None):
        """Validate and apply updates to an existing task."""
        task = self.get_task(task_id)

        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise InvalidInputError("Title cannot be empty.")

        if priority is not None:
            if isinstance(priority, bool) or priority not in Task.VALID_PRIORITIES:
                raise InvalidInputError(
                    "Priority must be 1 (low), 2 (medium), or 3 (high)."
                )

        validated_due = None
        if due_date is not None:
            if now is None:
                raise InvalidDueDateError("Current time is required to validate due date.")
            aware_now = ensure_aware(now, error_cls=InvalidDueDateError)
            validated_due = ensure_aware(due_date, error_cls=InvalidDueDateError)
            if validated_due < aware_now:
                raise InvalidDueDateError(
                    f"Due date {validated_due.strftime('%Y-%m-%d %H:%M')} is in the past."
                )

        if title is not None:
            task.rename(title)
        if priority is not None:
            task.set_priority(priority)
        if due_date is not None:
            task.set_due_date(validated_due, now)
        return task

    def complete_task(self, task_id):
        """Mark the specified task as done."""
        task = self.get_task(task_id)
        task.mark_done()
        return task

    def remove_task(self, task_id):
        """Delete the specified task and return it."""
        task = self.get_task(task_id)
        return self._tasks.pop(task.item_id)

    def list_by_priority(self, now):
        """Return open tasks ranked by priority score, earliest due date, then title."""
        aware_now = ensure_aware(now, error_cls=InvalidInputError)
        open_tasks = [
            task for task in self._tasks.values() if task.status == "open"
        ]
        ranked = sorted(
            open_tasks,
            key=lambda task: (
                -task.priority_score(aware_now),
                1 if task.due_date is None else 0,
                task.due_date.timestamp() if task.due_date is not None else 0.0,
                task.title.lower(),
            ),
        )
        # Assumption: ranking only reorders the open tasks; it never adds or drops one.
        assert len(ranked) == len(open_tasks)
        assert all(task.status == "open" for task in ranked)
        return ranked

    def list_proposals(self):
        """Return all tasks currently waiting for confirmation."""
        return [
            task for task in self._tasks.values() if task.status == "proposed"
        ]

    def list_all_tasks(self):
        """Return all tasks across all statuses."""
        return list(self._tasks.values())

    def add_reminder(self, reminder, now=None):
        """Store a Reminder; with `now`, refuse a one-off reminder already past."""
        if not isinstance(reminder, Reminder):
            raise InvalidInputError("Expected a Reminder instance.")
        if now is not None:
            aware_now = ensure_aware(now, error_cls=InvalidInputError)
            if reminder.repeat == "none" and reminder.remind_at < aware_now:
                raise InvalidInputError(
                    f"Reminder time {reminder.remind_at.strftime('%Y-%m-%d %H:%M')} "
                    "is in the past."
                )
        self._reminders[reminder.item_id] = reminder
        return reminder

    def list_reminders(self):
        """Return all stored reminders ordered by trigger time."""
        return sorted(
            self._reminders.values(),
            key=lambda rem: rem.remind_at.timestamp(),
        )

    def remove_reminder(self, reminder_id):
        """Remove a reminder by exact ID or raise ReminderNotFoundError."""
        if not isinstance(reminder_id, str) or reminder_id.strip() not in self._reminders:
            raise ReminderNotFoundError(f"Reminder '{reminder_id}' was not found.")
        return self._reminders.pop(reminder_id.strip())

    def restore(self, item):
        """Restore a loaded Task or Reminder without creation-time checks."""
        if isinstance(item, Task):
            self._tasks[item.item_id] = item
            return item
        if isinstance(item, Reminder):
            self._reminders[item.item_id] = item
            return item
        raise InvalidInputError("TaskManager can only restore Task or Reminder items.")
