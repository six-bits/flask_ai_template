"""Adapter layer for Inventory Reservation persistence."""

import threading
from typing import List, Optional

from app.adapter.db import InMemoryDB, in_memory_db
from app.adapter.entities import (
    ItemRecordEntity,
    ReservationRecordEntity,
    UserRecordEntity,
)


class InventoryAdapter:
    """Consolidated adapter wrapping database persistence and locking for inventory and users."""

    def __init__(self, db: Optional[InMemoryDB] = None):
        self._db = db or in_memory_db

    def get_item_lock(self, item_id: str) -> threading.RLock:
        """Fetch lock for the specified item."""
        return self._db.get_item_lock(item_id)

    def reclaim_expired(self, item_id: str, now: float) -> int:
        """Invoke JIT lease reclamation for the specified item."""
        return self._db.reclaim_expired_leases(item_id, now)

    def get_item(self, item_id: str) -> Optional[ItemRecordEntity]:
        """Fetch catalog item record."""
        return self._db.get_item(item_id)

    def get_all_items(self) -> List[ItemRecordEntity]:
        """Fetch all catalog item records."""
        return self._db.get_all_items()

    def save_reservation(self, reservation: ReservationRecordEntity) -> None:
        """Persist a reservation lease record."""
        self._db.save_reservation(reservation)

    def get_reservation(self, reservation_id: str) -> Optional[ReservationRecordEntity]:
        """Fetch a reservation lease record by ID."""
        return self._db.get_reservation(reservation_id)

    def get_item_reservations(self, item_id: str) -> List[ReservationRecordEntity]:
        """Fetch all reservations for a given item."""
        return self._db.get_item_reservations(item_id)

    def get_user_item_reservations(
        self, item_id: str, user_id: str
    ) -> List[ReservationRecordEntity]:
        """Fetch all reservations for a given item and user."""
        return self._db.get_user_item_reservations(item_id, user_id)

    def get_user(self, user_id: str) -> Optional[UserRecordEntity]:
        """Fetch user record by ID."""
        return self._db.get_user(user_id)

    def get_all_users(self) -> List[UserRecordEntity]:
        """Fetch all user records."""
        return self._db.get_all_users()

    def seed_user(self, user: UserRecordEntity) -> None:
        """Seed or insert a user record."""
        self._db.seed_user(user)


# Module-level singleton
inventory_adapter = InventoryAdapter()
