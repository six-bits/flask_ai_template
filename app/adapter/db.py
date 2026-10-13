"""In-memory database engine for Flash Sale Inventory Reservation."""

import threading
import time
from typing import Dict, List, Optional

from app.adapter.entities import (
    ItemRecordEntity,
    ReservationRecordEntity,
    UserRecordEntity,
)


class InMemoryDB:
    """Thread-safe in-memory database engine with granular per-item locking."""

    def __init__(self):
        self._items: Dict[str, ItemRecordEntity] = {}
        self._reservations: Dict[str, ReservationRecordEntity] = {}
        self._users: Dict[str, UserRecordEntity] = {}
        self._item_locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()
        self.seed_data()

    def seed_data(self) -> None:
        """Initialize in-memory database with default seed items and users."""
        default_items = [
            ItemRecordEntity(
                item_id="item_vip_ticket",
                name="VIP Concert Pass",
                total_stock=10,
                max_per_user=2,
            ),
            ItemRecordEntity(
                item_id="item_ga_ticket",
                name="General Admission Ticket",
                total_stock=50,
                max_per_user=4,
            ),
            ItemRecordEntity(
                item_id="item_merch_hoodie",
                name="Limited Edition Tour Hoodie",
                total_stock=5,
                max_per_user=1,
            ),
        ]

        now = time.time()
        default_users = [
            UserRecordEntity("user_101", "Demo User 101", "user101@example.com", now),
            UserRecordEntity("user_alice", "Alice Chen", "alice@example.com", now),
            UserRecordEntity("user_bob", "Bob Smith", "bob@example.com", now),
            UserRecordEntity("user_charlie", "Charlie Davis", "charlie@example.com", now),
            UserRecordEntity("user_dan", "Dan Evans", "dan@example.com", now),
            UserRecordEntity("user_eve", "Eve Taylor", "eve@example.com", now),
            UserRecordEntity("user_owner", "Owner User", "owner@example.com", now),
            UserRecordEntity("user_intruder", "Intruder User", "intruder@example.com", now),
        ]
        # Seed test buyers (buyer_0 to buyer_49, buyer_overflow)
        for i in range(50):
            default_users.append(
                UserRecordEntity(f"buyer_{i}", f"Buyer {i}", f"buyer_{i}@example.com", now)
            )
        default_users.append(
            UserRecordEntity("buyer_overflow", "Buyer Overflow", "overflow@example.com", now)
        )
        # Seed concurrency test racers (racer_0 to racer_19)
        for i in range(20):
            default_users.append(
                UserRecordEntity(f"racer_{i}", f"Racer {i}", f"racer_{i}@example.com", now)
            )

        with self._global_lock:
            for item in default_items:
                self._items[item.item_id] = item
                if item.item_id not in self._item_locks:
                    self._item_locks[item.item_id] = threading.RLock()

            for user in default_users:
                self._users[user.user_id] = user

    def reset(self) -> None:
        """Reset all in-memory database state and re-seed (used in testing)."""
        with self._global_lock:
            self._items.clear()
            self._reservations.clear()
            self._users.clear()
            self._item_locks.clear()
            self.seed_data()

    def get_item_lock(self, item_id: str) -> threading.RLock:
        """Fetch or dynamically create re-entrant lock for a specific item thread-safely."""
        with self._global_lock:
            if item_id not in self._item_locks:
                self._item_locks[item_id] = threading.RLock()
            return self._item_locks[item_id]

    def reclaim_expired_leases(self, item_id: str, now: float) -> int:
        """Transition overdue PENDING reservations to EXPIRED for an item (called under item lock)."""
        reclaimed_count = 0
        for res in self._reservations.values():
            if res.item_id == item_id and res.status == "PENDING" and now >= res.expires_at:
                res.status = "EXPIRED"
                reclaimed_count += 1
        return reclaimed_count

    def get_item(self, item_id: str) -> Optional[ItemRecordEntity]:
        """Retrieve a catalog item record by item_id."""
        return self._items.get(item_id)

    def get_all_items(self) -> List[ItemRecordEntity]:
        """Retrieve all catalog item records."""
        return list(self._items.values())

    def save_reservation(self, reservation: ReservationRecordEntity) -> None:
        """Save or update a reservation lease record."""
        self._reservations[reservation.reservation_id] = reservation

    def get_reservation(self, reservation_id: str) -> Optional[ReservationRecordEntity]:
        """Retrieve a reservation lease record by reservation_id."""
        return self._reservations.get(reservation_id)

    def get_item_reservations(self, item_id: str) -> List[ReservationRecordEntity]:
        """Retrieve all reservation records associated with an item."""
        return [res for res in self._reservations.values() if res.item_id == item_id]

    def get_user_item_reservations(
        self, item_id: str, user_id: str
    ) -> List[ReservationRecordEntity]:
        """Retrieve all reservation records for a specific user and item."""
        return [
            res
            for res in self._reservations.values()
            if res.item_id == item_id and res.user_id == user_id
        ]

    def get_user(self, user_id: str) -> Optional[UserRecordEntity]:
        """Retrieve a user record by user_id."""
        return self._users.get(user_id)

    def get_all_users(self) -> List[UserRecordEntity]:
        """Retrieve all registered users."""
        return list(self._users.values())

    def seed_user(self, user: UserRecordEntity) -> None:
        """Seed or insert a user record."""
        with self._global_lock:
            self._users[user.user_id] = user


# Singleton instance
in_memory_db = InMemoryDB()
