"""Domain entities for the application.

These entities define the data contracts between:
- Service layer <-> Manager layer
"""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class OrderStatus(str, Enum):
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_PREPARING = "ORDER_PREPARING"
    ORDER_DELIVERING = "ORDER_DELIVERING"
    ORDER_COMPLETED = "ORDER_COMPLETED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


@dataclass
class DishEntity:
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
class CartItemEntity:
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int  # in minor units (cents)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartResponseEntity:
    items: List[CartItemEntity]
    total_amount: int  # in minor units (cents)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_amount": self.total_amount,
        }


@dataclass
class AddToCartRequestEntity:
    dish_id: str
    units: int


@dataclass
class PlaceOrderRequestEntity:
    idempotency_key: str


@dataclass
class OrderLineItemEntity:
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrderResponseEntity:
    order_id: str
    items: List[OrderLineItemEntity]
    order_status: OrderStatus
    total_amount: int
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "items": [item.to_dict() for item in self.items],
            "order_status": (
                self.order_status.value
                if isinstance(self.order_status, OrderStatus)
                else self.order_status
            ),
            "total_amount": self.total_amount,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class OrderTransitionRequestEntity:
    order_id: str
    target_status: OrderStatus


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
