"""Adapter entities defining the data contract between Manager and Adapter layers."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class GreetingRecordEntity:
    """Storage/persistence entity for greeting records in the adapter."""
    name: str
    salutation: str
    message: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert adapter entity to dictionary."""
        return asdict(self)
