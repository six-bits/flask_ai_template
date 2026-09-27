"""Manager layer coordinating business logic."""

from typing import Optional

from app.adapter.entities import GreetingRecordEntity
from app.adapter.greeting_adapter import GreetingAdapter, greeting_adapter
from app.manager.entities import GreetingRequestEntity, GreetingResponseEntity


class GreetingManager:
    """Manager exposing a single greet function."""

    def __init__(self, adapter: Optional[GreetingAdapter] = None) -> None:
        self.adapter = adapter or greeting_adapter

    def greet(self, request: GreetingRequestEntity) -> GreetingResponseEntity:
        """Process greeting request: translates between service and adapter entities."""
        salutation = request.salutation.strip() or "Hello"
        name = request.name.strip()
        message = f"{salutation}, {name}!"

        # Translate to Adapter entity (Manager <-> Adapter contract)
        record = GreetingRecordEntity(
            name=name,
            salutation=salutation,
            message=message,
        )
        saved = self.adapter.save(record)

        # Translate to Manager response entity (Service <-> Manager contract)
        return GreetingResponseEntity(
            id=saved.id,
            name=saved.name,
            salutation=saved.salutation,
            message=saved.message,
        )


# Default singleton instance
greeting_manager = GreetingManager()
