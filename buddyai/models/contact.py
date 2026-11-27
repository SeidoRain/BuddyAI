"""Contact value object aggregated by Meeting records."""

from buddyai.exceptions import InvalidInputError


# Encapsulation: validates contact name and exposes read-only properties.
class Contact:
    """Represents a person invited to or attending a meeting."""

    def __init__(self, name, email="", organization=""):
        if not isinstance(name, str) or not name.strip():
            raise InvalidInputError("Contact name cannot be empty.")
        if not isinstance(email, str):
            raise InvalidInputError("Contact email must be text.")
        if not isinstance(organization, str):
            raise InvalidInputError("Contact organization must be text.")
        self._name = name.strip()
        self._email = email.strip()
        self._organization = organization.strip()

    @property
    def name(self):
        return self._name

    @property
    def email(self):
        return self._email

    @property
    def organization(self):
        return self._organization

    def to_dict(self):
        """Serialize the contact to a JSON-compatible dictionary."""
        return {
            "name": self._name,
            "email": self._email,
            "organization": self._organization,
        }

    @classmethod
    def from_dict(cls, data):
        """Restore a Contact from a dictionary."""
        if not isinstance(data, dict):
            raise InvalidInputError("Contact record must be an object.")
        return cls(
            name=data.get("name", ""),
            email=data.get("email", ""),
            organization=data.get("organization", ""),
        )

    def __eq__(self, other):
        if not isinstance(other, Contact):
            return NotImplemented
        return (
            self._name == other._name
            and self._email == other._email
            and self._organization == other._organization
        )

    def __hash__(self):
        # Equal contacts must hash alike; the fields never change after creation.
        return hash((self._name, self._email, self._organization))

    def __repr__(self):
        return (
            f"Contact(name={self._name!r}, email={self._email!r}, "
            f"organization={self._organization!r})"
        )
