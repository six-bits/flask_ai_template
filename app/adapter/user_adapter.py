"""In-memory persistence adapter for available users."""

from typing import Dict, Optional

from app.adapter.entities import UserRecordEntity


class UserAdapter:
    """In-memory adapter storing available users."""

    def __init__(self) -> None:
        self._users: Dict[str, UserRecordEntity] = {}

    def add_user(self, record: UserRecordEntity) -> UserRecordEntity:
        """Register an available user (idempotent).

        If user already exists, returns the existing record.
        """
        if record.user_id not in self._users:
            self._users[record.user_id] = record
        return self._users[record.user_id]

    def get_user(self, user_id: str) -> Optional[UserRecordEntity]:
        """Retrieve user by user_id, or None if not found (used for existence checks)."""
        return self._users.get(user_id)

    def clear(self) -> None:
        """Clear all stored users (useful for test resets)."""
        self._users.clear()


# Default singleton instance
user_adapter = UserAdapter()
