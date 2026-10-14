"""Adapter entities defining the data contract between Manager and Adapter layers."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class DishRecordEntity:
    """Storage entity representing a dish and its inventory portion metrics."""
    dish_id: str
    name: str
    price_per_unit: int  # in minor units (cents)
    total_portions: int
    total_available_portions: int
    total_reserved_portions: int
    total_sold_portions: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartItemRecordEntity:
    """Storage entity representing an item inside the active cart."""
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartRecordEntity:
    """Storage entity representing the single active cart."""
    items: List[CartItemRecordEntity]
    total_amount: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_amount": self.total_amount,
        }


@dataclass
class OrderLineItemRecordEntity:
    """Storage entity representing a purchased item snapshot within an order."""
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrderRecordEntity:
    """Storage entity representing an order and its current status."""
    order_id: str
    items: List[OrderLineItemRecordEntity]
    order_status: str
    total_amount: int
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdempotencyRecordEntity:
    """Storage entity mapping idempotency key and request payload hash to an order."""
    idempotency_key: str
    request_hash: str
    order_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GreetingRecordEntity:
    """Storage/persistence entity for greeting records in the adapter."""
    name: str
    salutation: str
    message: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
