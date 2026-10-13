"""Manager layer encapsulating business logic for Flash Sale Inventory Reservations and Users."""

import time
import uuid
from typing import Callable, List, Optional

from app.adapter.entities import ReservationRecordEntity
from app.adapter.inventory_adapter import InventoryAdapter, inventory_adapter
from app.manager.entities import (
    CancelReservationRequestEntity,
    ConfirmReservationRequestEntity,
    CreateReservationRequestEntity,
    ItemStockResponseEntity,
    ReservationResponseEntity,
    UserResponseEntity,
)
from app.manager.exceptions import (
    InsufficientStockError,
    ItemNotFoundError,
    PurchaseLimitExceededError,
    ReservationExpiredError,
    ReservationNotFoundError,
    ReservationStateConflictError,
    UnauthorizedReservationAccessError,
    UserNotFoundError,
)


class InventoryManager:
    """Coordinates inventory reservation lifecycle, user validation, locking, and JIT reclamation."""

    LEASE_DURATION_SECONDS: float = 30.0

    def __init__(
        self,
        adapter: Optional[InventoryAdapter] = None,
        time_provider: Callable[[], float] = time.time,
    ):
        self._adapter = adapter or inventory_adapter
        self._time_provider = time_provider

    def get_user(self, user_id: str) -> UserResponseEntity:
        """Get registered user by user_id."""
        user = self._adapter.get_user(user_id)
        if not user:
            raise UserNotFoundError(f"User '{user_id}' not found")
        return UserResponseEntity(
            user_id=user.user_id,
            name=user.name,
            email=user.email,
            created_at=user.created_at,
        )

    def list_users(self) -> List[UserResponseEntity]:
        """List all pre-seeded registered users."""
        users = self._adapter.get_all_users()
        sorted_users = sorted(users, key=lambda u: u.user_id)
        return [
            UserResponseEntity(
                user_id=u.user_id,
                name=u.name,
                email=u.email,
                created_at=u.created_at,
            )
            for u in sorted_users
        ]

    def get_item_stock(self, item_id: str) -> ItemStockResponseEntity:
        """Get live inventory stock metrics for a single item after JIT reclamation."""
        with self._adapter.get_item_lock(item_id):
            now = self._time_provider()
            self._adapter.reclaim_expired(item_id, now)

            item = self._adapter.get_item(item_id)
            if not item:
                raise ItemNotFoundError(f"Item '{item_id}' not found")

            reservations = self._adapter.get_item_reservations(item_id)
            confirmed_stock = sum(
                r.quantity for r in reservations if r.status == "CONFIRMED"
            )
            held_stock = sum(r.quantity for r in reservations if r.status == "PENDING")
            available_stock = item.total_stock - (confirmed_stock + held_stock)

            return ItemStockResponseEntity(
                item_id=item.item_id,
                name=item.name,
                total_stock=item.total_stock,
                available_stock=available_stock,
                held_stock=held_stock,
                confirmed_stock=confirmed_stock,
                max_per_user=item.max_per_user,
            )

    def list_items_stock(self) -> List[ItemStockResponseEntity]:
        """List live stock metrics for all items in catalog using sequential per-item locking."""
        items = self._adapter.get_all_items()
        sorted_items = sorted(items, key=lambda x: x.item_id)

        result: List[ItemStockResponseEntity] = []
        for item in sorted_items:
            stock_entity = self.get_item_stock(item.item_id)
            result.append(stock_entity)
        return result

    def create_reservation(
        self, request: CreateReservationRequestEntity
    ) -> ReservationResponseEntity:
        """Create a 30-second inventory reservation lease under item lock after validating user."""
        # 1. Validate user exists
        user = self._adapter.get_user(request.user_id)
        if not user:
            raise UserNotFoundError(f"User '{request.user_id}' not found")

        item_id = request.item_id
        with self._adapter.get_item_lock(item_id):
            now = self._time_provider()
            self._adapter.reclaim_expired(item_id, now)

            item = self._adapter.get_item(item_id)
            if not item:
                raise ItemNotFoundError(f"Item '{item_id}' not found")

            # Check overall available stock
            all_reservations = self._adapter.get_item_reservations(item_id)
            confirmed_stock = sum(
                r.quantity for r in all_reservations if r.status == "CONFIRMED"
            )
            held_stock = sum(
                r.quantity for r in all_reservations if r.status == "PENDING"
            )
            available_stock = item.total_stock - (confirmed_stock + held_stock)

            if request.quantity > available_stock:
                raise InsufficientStockError(
                    f"Requested {request.quantity} units, but only {available_stock} available"
                )

            # Check per-user anti-hoarding purchase quota
            user_reservations = self._adapter.get_user_item_reservations(
                item_id, request.user_id
            )
            user_held = sum(
                r.quantity for r in user_reservations if r.status == "PENDING"
            )
            user_confirmed = sum(
                r.quantity for r in user_reservations if r.status == "CONFIRMED"
            )
            user_current_total = user_held + user_confirmed

            if user_current_total + request.quantity > item.max_per_user:
                raise PurchaseLimitExceededError(
                    f"Purchase limit exceeded. Max per user is {item.max_per_user}, "
                    f"user already has {user_current_total} units committed or held"
                )

            # Create reservation record
            res_id = f"res_{uuid.uuid4().hex[:12]}"
            expires_at = now + self.LEASE_DURATION_SECONDS
            record = ReservationRecordEntity(
                reservation_id=res_id,
                item_id=item_id,
                user_id=request.user_id,
                quantity=request.quantity,
                status="PENDING",
                created_at=now,
                expires_at=expires_at,
                confirmed_at=None,
            )
            self._adapter.save_reservation(record)

            return ReservationResponseEntity(
                reservation_id=record.reservation_id,
                item_id=record.item_id,
                user_id=record.user_id,
                quantity=record.quantity,
                status=record.status,
                created_at=record.created_at,
                expires_at=record.expires_at,
                confirmed_at=None,
                time_remaining_seconds=max(0.0, expires_at - now),
            )

    def confirm_reservation(
        self, request: ConfirmReservationRequestEntity
    ) -> ReservationResponseEntity:
        """Confirm checkout for an active reservation lease under item lock after validating user."""
        # 1. Validate user exists
        user = self._adapter.get_user(request.user_id)
        if not user:
            raise UserNotFoundError(f"User '{request.user_id}' not found")

        res = self._adapter.get_reservation(request.reservation_id)
        if not res:
            raise ReservationNotFoundError(
                f"Reservation '{request.reservation_id}' not found"
            )

        with self._adapter.get_item_lock(res.item_id):
            now = self._time_provider()
            self._adapter.reclaim_expired(res.item_id, now)

            # Re-fetch latest record state under lock
            record = self._adapter.get_reservation(request.reservation_id)
            if not record:
                raise ReservationNotFoundError(
                    f"Reservation '{request.reservation_id}' not found"
                )

            if record.user_id != request.user_id:
                raise UnauthorizedReservationAccessError(
                    "User is not authorized to confirm this reservation"
                )

            if record.status == "EXPIRED" or (
                record.status == "PENDING" and now >= record.expires_at
            ):
                record.status = "EXPIRED"
                self._adapter.save_reservation(record)
                raise ReservationExpiredError(
                    f"Reservation '{request.reservation_id}' has expired"
                )

            if record.status == "CONFIRMED":
                raise ReservationStateConflictError("Reservation is already confirmed")

            if record.status == "CANCELLED":
                raise ReservationStateConflictError("Reservation has been cancelled")

            # Commit reservation
            record.status = "CONFIRMED"
            record.confirmed_at = now
            self._adapter.save_reservation(record)

            return ReservationResponseEntity(
                reservation_id=record.reservation_id,
                item_id=record.item_id,
                user_id=record.user_id,
                quantity=record.quantity,
                status=record.status,
                created_at=record.created_at,
                expires_at=record.expires_at,
                confirmed_at=record.confirmed_at,
                time_remaining_seconds=0.0,
            )

    def cancel_reservation(
        self, request: CancelReservationRequestEntity
    ) -> ReservationResponseEntity:
        """Cancel an active reservation lease and release hold immediately under item lock after validating user."""
        # 1. Validate user exists
        user = self._adapter.get_user(request.user_id)
        if not user:
            raise UserNotFoundError(f"User '{request.user_id}' not found")

        res = self._adapter.get_reservation(request.reservation_id)
        if not res:
            raise ReservationNotFoundError(
                f"Reservation '{request.reservation_id}' not found"
            )

        with self._adapter.get_item_lock(res.item_id):
            now = self._time_provider()
            self._adapter.reclaim_expired(res.item_id, now)

            # Re-fetch latest record state under lock
            record = self._adapter.get_reservation(request.reservation_id)
            if not record:
                raise ReservationNotFoundError(
                    f"Reservation '{request.reservation_id}' not found"
                )

            if record.user_id != request.user_id:
                raise UnauthorizedReservationAccessError(
                    "User is not authorized to cancel this reservation"
                )

            if record.status == "EXPIRED" or (
                record.status == "PENDING" and now >= record.expires_at
            ):
                record.status = "EXPIRED"
                self._adapter.save_reservation(record)
                raise ReservationStateConflictError(
                    "Cannot cancel an expired reservation"
                )

            if record.status == "CONFIRMED":
                raise ReservationStateConflictError(
                    "Cannot cancel an already confirmed reservation"
                )

            if record.status == "CANCELLED":
                raise ReservationStateConflictError(
                    "Reservation is already cancelled"
                )

            # Cancel reservation and release hold
            record.status = "CANCELLED"
            self._adapter.save_reservation(record)

            return ReservationResponseEntity(
                reservation_id=record.reservation_id,
                item_id=record.item_id,
                user_id=record.user_id,
                quantity=record.quantity,
                status=record.status,
                created_at=record.created_at,
                expires_at=record.expires_at,
                confirmed_at=None,
                time_remaining_seconds=0.0,
            )


# Module-level singleton
inventory_manager = InventoryManager()
