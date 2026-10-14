"""In-memory thread-safe adapter layer for the Food Delivery Service with per-user carts."""

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
    UserRecordEntity,
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


class UserNotFoundError(Exception):
    """Raised when an operation references a non-existent user."""
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
    """Thread-safe in-memory adapter managing restaurant catalog, per-user carts, and orders."""

    def __init__(self) -> None:
        self._global_lock = threading.RLock()
        self._inventory_lock = threading.RLock()

        self._users: Dict[str, UserRecordEntity] = {}
        self._user_locks: Dict[str, threading.RLock] = {}
        self._carts: Dict[str, CartRecordEntity] = {}

        self._dishes: Dict[str, DishRecordEntity] = {}
        self._orders: Dict[str, OrderRecordEntity] = {}
        self._idempotency_records: Dict[str, IdempotencyRecordEntity] = {}

        self._seed_default_data()

    def _seed_default_data(self) -> None:
        """Seed default pre-seeded users, per-user locks, carts, and dishes."""
        # 1. Pre-seed users
        default_users = [
            UserRecordEntity(user_id="user_1", name="Alice"),
            UserRecordEntity(user_id="user_2", name="Bob"),
            UserRecordEntity(user_id="user_3", name="Charlie"),
        ]
        for user in default_users:
            self._users[user.user_id] = user
            self._user_locks[user.user_id] = threading.RLock()
            self._carts[user.user_id] = CartRecordEntity(
                user_id=user.user_id, items=[], total_amount=0
            )

        # 2. Pre-seed restaurant dishes
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
        """Reset the adapter state to default seeded state (useful for test isolation)."""
        with self._global_lock:
            with self._inventory_lock:
                self._users.clear()
                self._user_locks.clear()
                self._carts.clear()
                self._dishes.clear()
                self._orders.clear()
                self._idempotency_records.clear()
                self._seed_default_data()

    # --- User Management ---

    def list_users(self) -> List[UserRecordEntity]:
        """Return a list of all pre-seeded users."""
        with self._global_lock:
            return [copy.deepcopy(user) for user in self._users.values()]

    def get_user(self, user_id: str) -> Optional[UserRecordEntity]:
        """Retrieve a user by ID."""
        with self._global_lock:
            user = self._users.get(user_id)
            return copy.deepcopy(user) if user else None

    def _get_user_lock(self, user_id: str) -> threading.RLock:
        """Retrieve the pre-seeded lock for a given user."""
        with self._global_lock:
            lock = self._user_locks.get(user_id)
            if not lock:
                raise UserNotFoundError(f"User '{user_id}' not found.")
            return lock

    # --- Dishes Catalog ---

    def list_dishes(self) -> List[DishRecordEntity]:
        """Return a snapshot list of all dishes with portion statistics."""
        with self._inventory_lock:
            return [copy.deepcopy(dish) for dish in self._dishes.values()]

    def get_dish(self, dish_id: str) -> Optional[DishRecordEntity]:
        """Retrieve a dish by ID."""
        with self._inventory_lock:
            dish = self._dishes.get(dish_id)
            return copy.deepcopy(dish) if dish else None

    def save_dish(self, dish: DishRecordEntity) -> None:
        """Save or update a dish in catalog."""
        with self._inventory_lock:
            self._dishes[dish.dish_id] = copy.deepcopy(dish)

    # --- Per-User Cart Management ---

    def get_cart(self, user_id: str) -> CartRecordEntity:
        """Retrieve a snapshot of the active cart for a specific user."""
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            cart = self._carts.get(user_id)
            if not cart:
                raise UserNotFoundError(f"User '{user_id}' cart not found.")
            return copy.deepcopy(cart)

    def add_to_cart(self, user_id: str, dish_id: str, units: int) -> CartRecordEntity:
        """Add or increment units of a dish in the user's active cart."""
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            cart = self._carts.get(user_id)
            if not cart:
                raise UserNotFoundError(f"User '{user_id}' cart not found.")

            with self._inventory_lock:
                dish = self._dishes.get(dish_id)
                if not dish:
                    raise DishNotFoundError(f"Dish '{dish_id}' not found")

                existing_item: Optional[CartItemRecordEntity] = None
                for item in cart.items:
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
                    cart.items.append(new_item)

                cart.total_amount = sum(item.total_price for item in cart.items)
                return copy.deepcopy(cart)

    def remove_from_cart(
        self, user_id: str, dish_id: str, units: Optional[int] = None
    ) -> CartRecordEntity:
        """Remove or decrement units of a dish in the user's active cart."""
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            cart = self._carts.get(user_id)
            if not cart:
                raise UserNotFoundError(f"User '{user_id}' cart not found.")

            existing_item: Optional[CartItemRecordEntity] = None
            for item in cart.items:
                if item.dish_id == dish_id:
                    existing_item = item
                    break

            if not existing_item:
                raise DishNotFoundError(f"Dish '{dish_id}' is not in the cart")

            if units is None or units >= existing_item.units:
                cart.items = [item for item in cart.items if item.dish_id != dish_id]
            else:
                existing_item.units -= units
                existing_item.total_price = existing_item.units * existing_item.price_per_unit

            cart.total_amount = sum(item.total_price for item in cart.items)
            return copy.deepcopy(cart)

    def clear_cart(self, user_id: str) -> CartRecordEntity:
        """Empty the user's active cart."""
        user_lock = self._get_user_lock(user_id)
        with user_lock:
            self._carts[user_id] = CartRecordEntity(user_id=user_id, items=[], total_amount=0)
            return copy.deepcopy(self._carts[user_id])

    # --- Orders & Idempotency ---

    def get_order(self, order_id: str) -> Optional[OrderRecordEntity]:
        """Retrieve an order by ID."""
        with self._global_lock:
            order = self._orders.get(order_id)
            return copy.deepcopy(order) if order else None

    def list_orders(self, user_id: Optional[str] = None) -> List[OrderRecordEntity]:
        """Retrieve a list of orders, optionally filtered by user_id."""
        with self._global_lock:
            if user_id:
                return [
                    copy.deepcopy(order)
                    for order in self._orders.values()
                    if order.user_id == user_id
                ]
            return [copy.deepcopy(order) for order in self._orders.values()]

    def get_idempotency_record(self, key: str) -> Optional[IdempotencyRecordEntity]:
        """Retrieve an idempotency record by key."""
        with self._global_lock:
            record = self._idempotency_records.get(key)
            return copy.deepcopy(record) if record else None

    def atomic_place_order(
        self, user_id: str, order_id: str, idempotency_key: str, request_hash: str
    ) -> Tuple[OrderRecordEntity, bool]:
        """Atomically place an order from the user's active cart.

        Acquires user_lock first, then inventory_lock (guaranteeing no deadlocks).
        Returns (OrderRecordEntity, is_replay: bool).
        """
        user_lock = self._get_user_lock(user_id)

        # 1. Acquire user lock
        with user_lock:
            # Check idempotency record under global lock
            with self._global_lock:
                existing_record = self._idempotency_records.get(idempotency_key)
                if existing_record:
                    if existing_record.user_id != user_id:
                        raise IdempotencyConflictError(
                            f"Idempotency key '{idempotency_key}' already used by another user."
                        )
                    if existing_record.request_hash == request_hash:
                        existing_order = self._orders.get(existing_record.order_id)
                        if existing_order:
                            return copy.deepcopy(existing_order), True
                    else:
                        raise IdempotencyConflictError(
                            f"Idempotency key '{idempotency_key}' reused with conflicting payload hash."
                        )

            cart = self._carts.get(user_id)
            if not cart or not cart.items:
                raise EmptyCartError("Cannot place an order with an empty cart.")

            # 2. Acquire inventory lock
            with self._inventory_lock:
                portions_sufficient = True
                rejection_reasons = []

                for item in cart.items:
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

                order_line_items = [
                    OrderLineItemRecordEntity(
                        dish_id=item.dish_id,
                        name=item.name,
                        units=item.units,
                        price_per_unit=item.price_per_unit,
                        total_price=item.total_price,
                    )
                    for item in cart.items
                ]

                if portions_sufficient:
                    # Deduct from available and add to reserved
                    for item in cart.items:
                        dish = self._dishes[item.dish_id]
                        dish.total_available_portions -= item.units
                        dish.total_reserved_portions += item.units

                    order = OrderRecordEntity(
                        order_id=order_id,
                        user_id=user_id,
                        items=order_line_items,
                        order_status="ORDER_ACCEPTED",
                        total_amount=cart.total_amount,
                        rejection_reason=None,
                    )
                    # Atomically empty only this user's cart
                    self._carts[user_id] = CartRecordEntity(
                        user_id=user_id, items=[], total_amount=0
                    )
                else:
                    order = OrderRecordEntity(
                        order_id=order_id,
                        user_id=user_id,
                        items=order_line_items,
                        order_status="ORDER_REJECTED",
                        total_amount=cart.total_amount,
                        rejection_reason="; ".join(rejection_reasons),
                    )
                    # User's cart remains intact on rejection

                with self._global_lock:
                    self._orders[order_id] = order
                    self._idempotency_records[idempotency_key] = IdempotencyRecordEntity(
                        idempotency_key=idempotency_key,
                        user_id=user_id,
                        request_hash=request_hash,
                        order_id=order_id,
                    )

                return copy.deepcopy(order), False

    def atomic_transition_order(self, order_id: str, target_status: str) -> OrderRecordEntity:
        """Atomically transition order status and adjust inventory portions."""
        with self._inventory_lock:
            with self._global_lock:
                order = self._orders.get(order_id)
                if not order:
                    raise OrderNotFoundError(f"Order '{order_id}' not found.")

                current_status = order.order_status

                # Terminal states cannot be transitioned
                if current_status in ("ORDER_COMPLETED", "ORDER_CANCELLED", "ORDER_REJECTED"):
                    raise InvalidTransitionError(
                        f"Order '{order_id}' is in terminal status '{current_status}' and cannot transition."
                    )

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

                # Perform portion adjustments under inventory lock
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
