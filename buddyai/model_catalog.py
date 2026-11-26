"""ModelCatalog: the Gemini models BuddyAI may use and the one in use now."""

from buddyai.exceptions import InvalidInputError


# Encapsulation: the single place that knows the list of models, which one is
# active, and which cannot be used right now (daily limit used up, or not
# responding). Adding a model to the list (BUDDYAI_MODELS in .env) needs no
# code change.
class ModelCatalog:
    """Keeps the selectable models and tracks the active one."""

    def __init__(self, names, current):
        if not isinstance(current, str) or not current.strip():
            raise InvalidInputError("The current model name cannot be empty.")
        self._names = []
        for name in list(names) + [current]:
            cleaned = str(name).strip()
            if cleaned and cleaned not in self._names:
                self._names.append(cleaned)
        self._current = current.strip()
        self._unavailable = {}      # model name -> why it cannot be used right now

    @property
    def current(self):
        return self._current

    @property
    def names(self):
        return list(self._names)

    DAILY_LIMIT = "daily limit reached"
    RATE_LIMITED = "per-minute limit reached"
    NOT_RESPONDING = "not responding"

    def is_available(self, name):
        """Return True unless the model was marked as unusable for now."""
        return name not in self._unavailable

    def mark_unavailable(self, name, reason):
        """Remember that a model cannot be used right now, and why."""
        if name in self._names:
            self._unavailable[name] = reason

    def reason_for(self, name):
        """Return why a model is marked as unusable, or None if it is not marked."""
        return self._unavailable.get(name)

    def set_daily_limited(self, names):
        """Replace the 'daily limit reached' marks with the given list of models."""
        for name in list(self._unavailable):
            if self._unavailable[name] == self.DAILY_LIMIT and name not in names:
                del self._unavailable[name]
        for name in names:
            self.mark_unavailable(name, self.DAILY_LIMIT)

    def mark_exhausted(self, name):
        """Remember that a model has no free requests left today."""
        self.mark_unavailable(name, self.DAILY_LIMIT)

    def clear_temporary(self):
        """Forget the marks that pass by themselves; daily limits stay."""
        for name in list(self._unavailable):
            if self._unavailable[name] != self.DAILY_LIMIT:
                del self._unavailable[name]

    def best_available(self):
        """Return the best usable model other than the current one, or None.

        The list is kept best first, so this is the first usable name in it.
        """
        for name in self._names:
            if name != self._current and name not in self._unavailable:
                return name
        return None

    def next_available(self):
        """Return the next usable model after the current one, or None."""
        start = self._names.index(self._current)
        for step in range(1, len(self._names)):
            candidate = self._names[(start + step) % len(self._names)]
            if candidate not in self._unavailable:
                return candidate
        return None

    def resolve(self, choice):
        """Turn a number, a name, part of a name, or 'next' into a model name."""
        if not isinstance(choice, str) or not choice.strip():
            raise InvalidInputError("Say which model to use. " + self._options_text())
        text = choice.strip().lower()

        if text == "next":
            candidate = self.next_available()
            if candidate is None:
                raise InvalidInputError(
                    "No other model in the list is usable right now."
                )
            return candidate

        if text.isdigit():
            position = int(text)
            if 1 <= position <= len(self._names):
                return self._names[position - 1]
            raise InvalidInputError(
                f"There is no model number {position}. " + self._options_text()
            )

        for name in self._names:
            if name.lower() == text:
                return name
        partial = [name for name in self._names if text in name.lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise InvalidInputError(
                f"'{choice.strip()}' matches more than one model: "
                + ", ".join(partial) + "."
            )
        raise InvalidInputError(
            f"Unknown model '{choice.strip()}'. " + self._options_text()
        )

    def switch(self, choice):
        """Make the chosen model the active one and return its name.

        Choosing a model that was 'not responding' clears that mark, so it gets
        a fresh try. A 'daily limit reached' mark stays: waiting is the only cure.
        """
        self._current = self.resolve(choice)
        if self._unavailable.get(self._current, self.DAILY_LIMIT) != self.DAILY_LIMIT:
            del self._unavailable[self._current]
        return self._current

    def _options_text(self):
        numbered = ", ".join(
            f"{index}. {name}" for index, name in enumerate(self._names, start=1)
        )
        return f"Choices: {numbered}."

    def describe(self):
        """Return the model list as text, marking the active and used-up models."""
        # Blank lines and no angle brackets: the browser chat renders this text
        # as Markdown, which joins single lines and hides anything like <name>.
        lines = [f"Current model: {self._current}", "", "Available models:", ""]
        for index, name in enumerate(self._names, start=1):
            notes = []
            if name == self._current:
                notes.append("in use")
            if name in self._unavailable:
                notes.append(self._unavailable[name])
            suffix = f" ({', '.join(notes)})" if notes else ""
            lines.append(f"{index}. {name}{suffix}")
        # Use a model that can actually be chosen as the example.
        example = 1
        for index, name in enumerate(self._names, start=1):
            if name != self._current and name not in self._unavailable:
                example = index
                break
        lines.append("")
        lines.append(
            f"To switch, type /model and a number or name, for example /model {example}. "
            "/model next picks the next usable model in the list."
        )
        return "\n".join(lines)
