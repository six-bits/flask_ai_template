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


@dataclass
class UserRecordEntity:
    """Storage entity representing a user in the database."""
    user_id: str
    name: str
    email: str
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert user entity to dictionary."""
        return asdict(self)


@dataclass
class ItemRecordEntity:
    """Storage entity representing a catalog item in the in-memory database."""
    item_id: str
    name: str
    total_stock: int
    max_per_user: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert item entity to dictionary."""
        return asdict(self)


@dataclass
class ReservationRecordEntity:
    """Storage entity representing an inventory reservation lease."""
    reservation_id: str
    item_id: str
    user_id: str
    quantity: int
    status: str  # "PENDING" | "CONFIRMED" | "CANCELLED" | "EXPIRED"
    created_at: float
    expires_at: float
    confirmed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert reservation entity to dictionary."""
        return asdict(self)
