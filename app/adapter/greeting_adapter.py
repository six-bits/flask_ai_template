"""Adapter layer handling persistence."""

from typing import List

from app.adapter.entities import GreetingRecordEntity


class GreetingAdapter:
    """In-memory persistence adapter exposing a single save function."""

    def __init__(self) -> None:
        self.storage: List[GreetingRecordEntity] = []

    def save(self, record: GreetingRecordEntity) -> GreetingRecordEntity:
        """Persist a greeting record."""
        record.id = len(self.storage) + 1
        self.storage.append(record)
        return record


# Default singleton instance
greeting_adapter = GreetingAdapter()
