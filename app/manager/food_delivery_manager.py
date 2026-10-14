"""Manager layer handling business logic and orchestration for Food Delivery Service with per-user carts."""

import hashlib
import json
import uuid
from typing import List, Optional, Tuple

from app.adapter.entities import DishRecordEntity
from app.adapter.food_delivery_adapter import (
    DishNotFoundError,
    EmptyCartError,
    FoodDeliveryAdapter,
    IdempotencyConflictError,
    InsufficientPortionsError,
    InvalidTransitionError,
    OrderNotFoundError,
    UserNotFoundError,
    food_delivery_adapter,
)
from app.manager.entities import (
    AddToCartRequestEntity,
    CartItemEntity,
    CartResponseEntity,
    DishEntity,
    OrderLineItemEntity,
    OrderResponseEntity,
    OrderStatus,
    OrderTransitionRequestEntity,
    PlaceOrderRequestEntity,
    UserEntity,
)


class FoodDeliveryManager:
    """Coordinates cart management, order placement, idempotency, and status transitions per user."""

    def __init__(self, adapter: FoodDeliveryAdapter) -> None:
        self.adapter = adapter

    def list_users(self) -> List[UserEntity]:
        """Retrieve all pre-seeded users."""
        users = self.adapter.list_users()
        return [UserEntity(user_id=u.user_id, name=u.name) for u in users]

    def get_user(self, user_id: str) -> Optional[UserEntity]:
        """Retrieve a specific user by ID."""
        user = self.adapter.get_user(user_id)
        return UserEntity(user_id=user.user_id, name=user.name) if user else None

    def list_dishes(self) -> List[DishEntity]:
        """Retrieve all dishes with portion statistics."""
        dish_records = self.adapter.list_dishes()
        return [
            DishEntity(
                dish_id=d.dish_id,
                name=d.name,
                price_per_unit=d.price_per_unit,
                total_portions=d.total_portions,
                total_available_portions=d.total_available_portions,
                total_reserved_portions=d.total_reserved_portions,
                total_sold_portions=d.total_sold_portions,
            )
            for d in dish_records
        ]

    def seed_dish(
        self, dish_id: str, name: str, price_per_unit: int, total_portions: int
    ) -> DishEntity:
        """Add or update a dish in the catalog."""
        dish_record = DishRecordEntity(
            dish_id=dish_id,
            name=name,
            price_per_unit=price_per_unit,
            total_portions=total_portions,
            total_available_portions=total_portions,
            total_reserved_portions=0,
            total_sold_portions=0,
        )
        self.adapter.save_dish(dish_record)
        return DishEntity(
            dish_id=dish_record.dish_id,
            name=dish_record.name,
            price_per_unit=dish_record.price_per_unit,
            total_portions=dish_record.total_portions,
            total_available_portions=dish_record.total_available_portions,
            total_reserved_portions=dish_record.total_reserved_portions,
            total_sold_portions=dish_record.total_sold_portions,
        )

    def get_cart(self, user_id: str) -> CartResponseEntity:
        """Retrieve the active cart for a specific user."""
        cart_record = self.adapter.get_cart(user_id)
        items = [
            CartItemEntity(
                dish_id=item.dish_id,
                name=item.name,
                units=item.units,
                price_per_unit=item.price_per_unit,
                total_price=item.total_price,
            )
            for item in cart_record.items
        ]
        return CartResponseEntity(
            user_id=cart_record.user_id, items=items, total_amount=cart_record.total_amount
        )

    def add_to_cart(self, req: AddToCartRequestEntity) -> CartResponseEntity:
        """Add or increment dish units in the user's active cart."""
        cart_record = self.adapter.add_to_cart(req.user_id, req.dish_id, req.units)
        items = [
            CartItemEntity(
                dish_id=item.dish_id,
                name=item.name,
                units=item.units,
                price_per_unit=item.price_per_unit,
                total_price=item.total_price,
            )
            for item in cart_record.items
        ]
        return CartResponseEntity(
            user_id=cart_record.user_id, items=items, total_amount=cart_record.total_amount
        )

    def remove_from_cart(
        self, user_id: str, dish_id: str, units: Optional[int] = None
    ) -> CartResponseEntity:
        """Remove or decrement dish units from the user's active cart."""
        cart_record = self.adapter.remove_from_cart(user_id, dish_id, units)
        items = [
            CartItemEntity(
                dish_id=item.dish_id,
                name=item.name,
                units=item.units,
                price_per_unit=item.price_per_unit,
                total_price=item.total_price,
            )
            for item in cart_record.items
        ]
        return CartResponseEntity(
            user_id=cart_record.user_id, items=items, total_amount=cart_record.total_amount
        )

    def clear_cart(self, user_id: str) -> CartResponseEntity:
        """Empty the user's active cart."""
        cart_record = self.adapter.clear_cart(user_id)
        return CartResponseEntity(
            user_id=cart_record.user_id, items=[], total_amount=cart_record.total_amount
        )

    def place_order(
        self, req: PlaceOrderRequestEntity
    ) -> Tuple[OrderResponseEntity, bool]:
        """Place an order from the user's active cart using an idempotency key.

        Returns (OrderResponseEntity, is_replay).
        """
        cart_record = self.adapter.get_cart(req.user_id)

        # Check existing idempotency record first
        existing_record = self.adapter.get_idempotency_record(req.idempotency_key)
        if existing_record:
            if existing_record.user_id != req.user_id:
                raise IdempotencyConflictError(
                    f"Idempotency key '{req.idempotency_key}' already used by another user."
                )
            existing_order = self.adapter.get_order(existing_record.order_id)
            if existing_order:
                if cart_record.items:
                    sorted_items = sorted(
                        [{"dish_id": i.dish_id, "units": i.units} for i in cart_record.items],
                        key=lambda x: x["dish_id"],
                    )
                    current_hash = hashlib.sha256(
                        json.dumps(sorted_items, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    if current_hash != existing_record.request_hash:
                        raise IdempotencyConflictError(
                            f"Idempotency key '{req.idempotency_key}' reused with conflicting payload hash."
                        )
                return self._to_order_response_entity(existing_order), True

        # Generate request hash from current user's cart
        sorted_items = sorted(
            [{"dish_id": i.dish_id, "units": i.units} for i in cart_record.items],
            key=lambda x: x["dish_id"],
        )
        request_hash = hashlib.sha256(
            json.dumps(sorted_items, sort_keys=True).encode("utf-8")
        ).hexdigest()

        order_id = f"ord_{uuid.uuid4().hex[:10]}"
        order_record, is_replay = self.adapter.atomic_place_order(
            user_id=req.user_id,
            order_id=order_id,
            idempotency_key=req.idempotency_key,
            request_hash=request_hash,
        )

        return self._to_order_response_entity(order_record), is_replay

    def list_orders(self, user_id: Optional[str] = None) -> List[OrderResponseEntity]:
        """List orders, optionally filtered by user_id."""
        order_records = self.adapter.list_orders(user_id=user_id)
        return [self._to_order_response_entity(o) for o in order_records]

    def get_order(self, order_id: str) -> Optional[OrderResponseEntity]:
        """Retrieve an order by ID."""
        order_record = self.adapter.get_order(order_id)
        return self._to_order_response_entity(order_record) if order_record else None

    def transition_order_status(
        self, req: OrderTransitionRequestEntity
    ) -> OrderResponseEntity:
        """Advance an order to target status."""
        target_str = (
            req.target_status.value
            if isinstance(req.target_status, OrderStatus)
            else req.target_status
        )
        order_record = self.adapter.atomic_transition_order(req.order_id, target_str)
        return self._to_order_response_entity(order_record)

    def _to_order_response_entity(self, order_record) -> OrderResponseEntity:
        """Convert OrderRecordEntity to OrderResponseEntity."""
        items = [
            OrderLineItemEntity(
                dish_id=item.dish_id,
                name=item.name,
                units=item.units,
                price_per_unit=item.price_per_unit,
                total_price=item.total_price,
            )
            for item in order_record.items
        ]
        return OrderResponseEntity(
            order_id=order_record.order_id,
            user_id=order_record.user_id,
            items=items,
            order_status=OrderStatus(order_record.order_status),
            total_amount=order_record.total_amount,
            rejection_reason=order_record.rejection_reason,
        )


# Global manager singleton
food_delivery_manager = FoodDeliveryManager(food_delivery_adapter)
