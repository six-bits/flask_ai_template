"""Domain entities for the greeting application.

These entities define the data contracts between:
- Service layer <-> Manager layer
- Manager layer <-> Adapter layer
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class GreetingRequestEntity:
    """Entity representing an incoming greeting request."""
    name: str
    salutation: str = "Hello"


@dataclass
class GreetingResponseEntity:
    """Entity representing a processed greeting response."""
    message: str
    salutation: str
    name: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to a dictionary for JSON serialization."""
        return asdict(self)
