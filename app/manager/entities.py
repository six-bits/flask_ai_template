"""Domain entities for the application.

These entities define the data contracts between:
- Service layer <-> Manager layer
- Manager layer <-> Adapter layer
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Greeting Entities (Template / Legacy)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Flash Sale Inventory Reservation Contracts (Service <-> Manager)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateReservationRequestEntity:
    """Request payload to create an inventory reservation lease."""
    item_id: str
    user_id: str
    quantity: int


@dataclass(frozen=True)
class ConfirmReservationRequestEntity:
    """Request payload to confirm an active reservation lease."""
    reservation_id: str
    user_id: str


@dataclass(frozen=True)
class CancelReservationRequestEntity:
    """Request payload to explicitly cancel an active reservation lease."""
    reservation_id: str
    user_id: str


@dataclass(frozen=True)
class ReservationResponseEntity:
    """Response representation of a reservation lease."""
    reservation_id: str
    item_id: str
    user_id: str
    quantity: int
    status: str  # "PENDING" | "CONFIRMED" | "CANCELLED" | "EXPIRED"
    created_at: float
    expires_at: float
    confirmed_at: Optional[float] = None
    time_remaining_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to a dictionary for JSON serialization."""
        return asdict(self)


@dataclass(frozen=True)
class ItemStockResponseEntity:
    """Response representation of an item's live stock breakdown."""
    item_id: str
    name: str
    total_stock: int
    available_stock: int
    held_stock: int
    confirmed_stock: int
    max_per_user: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to a dictionary for JSON serialization."""
        return asdict(self)


@dataclass(frozen=True)
class ListItemStockResponseEntity:
    """Response representation of multiple items' stock breakdowns."""
    items: List[ItemStockResponseEntity]

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to a dictionary for JSON serialization."""
        return asdict(self)
