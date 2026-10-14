"""In-memory thread-safe adapter layer for the Food Delivery Service."""

import copy
import threading
from typing import Dict, List, Optional, Tuple

from app.adapter.entities import (
    CartItemRecordEntity,
    CartRecordEntity,
    DishRecordEntity,
    IdempotencyRecordEntity,
    OrderLineItemRecordEntity,
    OrderRecordEntity,
)


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different request payload hash."""
    pass


class EmptyCartError(Exception):
    """Raised when an order placement is attempted on an empty cart."""
    pass


class DishNotFoundError(Exception):
    """Raised when an operation references a non-existent dish."""
    pass


class InvalidTransitionError(Exception):
    """Raised when an invalid status transition is attempted on an order."""
    pass


class OrderNotFoundError(Exception):
    """Raised when an operation references a non-existent order."""
    pass


class InsufficientPortionsError(Exception):
    """Raised when requested dish units exceed available portions."""
    pass


class FoodDeliveryAdapter:
    """Thread-safe in-memory adapter managing restaurant catalog, cart, and orders."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dishes: Dict[str, DishRecordEntity] = {}
        self._cart: CartRecordEntity = CartRecordEntity(items=[], total_amount=0)
        self._orders: Dict[str, OrderRecordEntity] = {}
        self._idempotency_records: Dict[str, IdempotencyRecordEntity] = {}
        self._seed_default_dishes()

    def _seed_default_dishes(self) -> None:
        """Seed the restaurant's default dishes with portion counts."""
        default_dishes = [
            DishRecordEntity(
                dish_id="dish_1",
                name="Margherita Pizza",
                price_per_unit=1250,  # $12.50
                total_portions=10,
                total_available_portions=10,
                total_reserved_portions=0,
                total_sold_portions=0,
            ),
            DishRecordEntity(
                dish_id="dish_2",
                name="Pasta Carbonara",
                price_per_unit=1500,  # $15.00
                total_portions=8,
                total_available_portions=8,
                total_reserved_portions=0,
                total_sold_portions=0,
            ),
            DishRecordEntity(
                dish_id="dish_3",
                name="Tiramisu",
                price_per_unit=600,  # $6.00
                total_portions=15,
                total_available_portions=15,
                total_reserved_portions=0,
                total_sold_portions=0,
            ),
        ]
        for dish in default_dishes:
            self._dishes[dish.dish_id] = dish

    def reset(self) -> None:
        """Reset the adapter state to default seeded state (useful for tests)."""
        with self._lock:
            self._dishes.clear()
            self._cart = CartRecordEntity(items=[], total_amount=0)
            self._orders.clear()
            self._idempotency_records.clear()
            self._seed_default_dishes()

    def list_dishes(self) -> List[DishRecordEntity]:
        """Return a snapshot list of all dishes."""
        with self._lock:
            return [copy.deepcopy(dish) for dish in self._dishes.values()]

    def get_dish(self, dish_id: str) -> Optional[DishRecordEntity]:
        """Retrieve a dish by ID."""
        with self._lock:
            dish = self._dishes.get(dish_id)
            return copy.deepcopy(dish) if dish else None

    def save_dish(self, dish: DishRecordEntity) -> None:
        """Save or update a dish in catalog."""
        with self._lock:
            self._dishes[dish.dish_id] = copy.deepcopy(dish)

    def get_cart(self) -> CartRecordEntity:
        """Retrieve a snapshot of the current active cart."""
        with self._lock:
            return copy.deepcopy(self._cart)

    def add_to_cart(self, dish_id: str, units: int) -> CartRecordEntity:
        """Add or increment units of a dish in the active cart."""
        with self._lock:
            dish = self._dishes.get(dish_id)
            if not dish:
                raise DishNotFoundError(f"Dish '{dish_id}' not found")

            existing_item: Optional[CartItemRecordEntity] = None
            for item in self._cart.items:
                if item.dish_id == dish_id:
                    existing_item = item
                    break

            current_units = existing_item.units if existing_item else 0
            if current_units + units > dish.total_available_portions:
                raise InsufficientPortionsError(
                    f"Cannot add {units} portion(s) of '{dish.name}'. "
                    f"Cart already has {current_units}, but only {dish.total_available_portions} portion(s) are available."
                )

            if existing_item:
                existing_item.units += units
                existing_item.total_price = existing_item.units * existing_item.price_per_unit
            else:
                new_item = CartItemRecordEntity(
                    dish_id=dish.dish_id,
                    name=dish.name,
                    units=units,
                    price_per_unit=dish.price_per_unit,
                    total_price=units * dish.price_per_unit,
                )
                self._cart.items.append(new_item)

            self._cart.total_amount = sum(item.total_price for item in self._cart.items)
            return copy.deepcopy(self._cart)

    def remove_from_cart(self, dish_id: str, units: Optional[int] = None) -> CartRecordEntity:
        """Remove or decrement units of a dish in the active cart."""
        with self._lock:
            existing_item: Optional[CartItemRecordEntity] = None
            for item in self._cart.items:
                if item.dish_id == dish_id:
                    existing_item = item
                    break

            if not existing_item:
                raise DishNotFoundError(f"Dish '{dish_id}' is not in the cart")

            if units is None or units >= existing_item.units:
                self._cart.items = [item for item in self._cart.items if item.dish_id != dish_id]
            else:
                existing_item.units -= units
                existing_item.total_price = existing_item.units * existing_item.price_per_unit

            self._cart.total_amount = sum(item.total_price for item in self._cart.items)
            return copy.deepcopy(self._cart)

    def clear_cart(self) -> CartRecordEntity:
        """Empty the active cart."""
        with self._lock:
            self._cart = CartRecordEntity(items=[], total_amount=0)
            return copy.deepcopy(self._cart)

    def get_order(self, order_id: str) -> Optional[OrderRecordEntity]:
        """Retrieve an order by ID."""
        with self._lock:
            order = self._orders.get(order_id)
            return copy.deepcopy(order) if order else None

    def list_orders(self) -> List[OrderRecordEntity]:
        """Retrieve a list of all orders."""
        with self._lock:
            return [copy.deepcopy(order) for order in self._orders.values()]

    def get_idempotency_record(self, key: str) -> Optional[IdempotencyRecordEntity]:
        """Retrieve an idempotency record by key."""
        with self._lock:
            record = self._idempotency_records.get(key)
            return copy.deepcopy(record) if record else None

    def atomic_place_order(
        self, order_id: str, idempotency_key: str, request_hash: str
    ) -> Tuple[OrderRecordEntity, bool]:
        """Atomically place an order from the active cart.

        Returns (OrderRecordEntity, is_replay: bool).
        """
        with self._lock:
            # 1. Idempotency check
            existing_record = self._idempotency_records.get(idempotency_key)
            if existing_record:
                if existing_record.request_hash == request_hash:
                    existing_order = self._orders.get(existing_record.order_id)
                    if existing_order:
                        return copy.deepcopy(existing_order), True
                else:
                    raise IdempotencyConflictError(
                        f"Idempotency key '{idempotency_key}' reused with conflicting payload hash."
                    )

            # 2. Cart validation
            if not self._cart.items:
                raise EmptyCartError("Cannot place an order with an empty cart.")

            # 3. Check portion availability across all cart items
            portions_sufficient = True
            rejection_reasons = []

            for item in self._cart.items:
                dish = self._dishes.get(item.dish_id)
                if not dish:
                    portions_sufficient = False
                    rejection_reasons.append(f"Dish '{item.dish_id}' not found in catalog.")
                elif dish.total_available_portions < item.units:
                    portions_sufficient = False
                    rejection_reasons.append(
                        f"Dish '{dish.name}' only has {dish.total_available_portions} portions available, "
                        f"requested {item.units}."
                    )

            # Build line items
            order_line_items = [
                OrderLineItemRecordEntity(
                    dish_id=item.dish_id,
                    name=item.name,
                    units=item.units,
                    price_per_unit=item.price_per_unit,
                    total_price=item.total_price,
                )
                for item in self._cart.items
            ]

            if portions_sufficient:
                # Deduct from available and add to reserved
                for item in self._cart.items:
                    dish = self._dishes[item.dish_id]
                    dish.total_available_portions -= item.units
                    dish.total_reserved_portions += item.units

                order = OrderRecordEntity(
                    order_id=order_id,
                    items=order_line_items,
                    order_status="ORDER_ACCEPTED",
                    total_amount=self._cart.total_amount,
                    rejection_reason=None,
                )
                # Atomically empty the active cart upon acceptance
                self._cart = CartRecordEntity(items=[], total_amount=0)
            else:
                order = OrderRecordEntity(
                    order_id=order_id,
                    items=order_line_items,
                    order_status="ORDER_REJECTED",
                    total_amount=self._cart.total_amount,
                    rejection_reason="; ".join(rejection_reasons),
                )
                # Keep active cart intact on rejection

            self._orders[order_id] = order
            self._idempotency_records[idempotency_key] = IdempotencyRecordEntity(
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                order_id=order_id,
            )

            return copy.deepcopy(order), False

    def atomic_transition_order(self, order_id: str, target_status: str) -> OrderRecordEntity:
        """Atomically transition order status and adjust inventory portions."""
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                raise OrderNotFoundError(f"Order '{order_id}' not found.")

            current_status = order.order_status

            # Terminal states cannot be transitioned
            if current_status in ("ORDER_COMPLETED", "ORDER_CANCELLED", "ORDER_REJECTED"):
                raise InvalidTransitionError(
                    f"Order '{order_id}' is in terminal status '{current_status}' and cannot transition."
                )

            # Transition rules:
            # ORDER_ACCEPTED -> ORDER_PREPARING, ORDER_CANCELLED
            # ORDER_PREPARING -> ORDER_DELIVERING, ORDER_CANCELLED
            # ORDER_DELIVERING -> ORDER_COMPLETED
            valid_targets = {
                "ORDER_ACCEPTED": ["ORDER_PREPARING", "ORDER_CANCELLED"],
                "ORDER_PREPARING": ["ORDER_DELIVERING", "ORDER_CANCELLED"],
                "ORDER_DELIVERING": ["ORDER_COMPLETED"],
            }.get(current_status, [])

            if target_status not in valid_targets:
                raise InvalidTransitionError(
                    f"Cannot transition order '{order_id}' from '{current_status}' to '{target_status}'. "
                    f"Allowed targets: {valid_targets}"
                )

            # Perform portion adjustments
            if target_status == "ORDER_CANCELLED":
                for item in order.items:
                    dish = self._dishes.get(item.dish_id)
                    if dish:
                        dish.total_reserved_portions -= item.units
                        dish.total_available_portions += item.units
            elif target_status == "ORDER_COMPLETED":
                for item in order.items:
                    dish = self._dishes.get(item.dish_id)
                    if dish:
                        dish.total_reserved_portions -= item.units
                        dish.total_sold_portions += item.units

            order.order_status = target_status
            return copy.deepcopy(order)


# Global adapter singleton
food_delivery_adapter = FoodDeliveryAdapter()
