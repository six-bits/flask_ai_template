"""User Manager handling user lifecycle and existence verification."""

from datetime import datetime, timezone
from typing import Optional

from app.adapter.entities import UserRecordEntity
from app.adapter.user_adapter import UserAdapter, user_adapter as default_user_adapter
from app.manager.entities import (
    RegisterUserRequestEntity,
    RegisterUserResponseEntity,
)
from app.manager.exceptions import (
    UserAlreadyExistsError,
    UserNotFoundError,
)


class UserManager:
    """Manager handling user lifecycle and existence validations."""

    def __init__(self, user_adapter: Optional[UserAdapter] = None) -> None:
        self.user_adapter = user_adapter or default_user_adapter

    def register_user(self, request: RegisterUserRequestEntity) -> RegisterUserResponseEntity:
        """Register a new user in the user store.

        Raises:
            UserAlreadyExistsError: If user_id is already registered.
        """
        existing = self.user_adapter.get_user(request.user_id)
        if existing is not None:
            raise UserAlreadyExistsError(request.user_id)

        now = datetime.now(timezone.utc).isoformat()
        record = UserRecordEntity(user_id=request.user_id, created_at=now)
        saved = self.user_adapter.add_user(record)
        return RegisterUserResponseEntity(user_id=saved.user_id, created_at=saved.created_at)

    def ensure_user_exists(self, user_id: str) -> None:
        """Validate user existence, raising UserNotFoundError if not registered."""
        if self.user_adapter.get_user(user_id) is None:
            raise UserNotFoundError(user_id)

    def user_exists(self, user_id: str) -> bool:
        """Check whether a user is registered."""
        return self.user_adapter.get_user(user_id) is not None


# Default singleton instance
user_manager = UserManager()
