"""In-memory database and concurrency control for card issuing service."""

import threading
from typing import Dict, List, Optional, Set

from app.adapter.entities import (
    AuthorizationRecordEntity,
    CardRecordEntity,
    ClearingRecordEntity,
    IdempotencyRecordEntity,
    LedgerTransactionRecordEntity,
    ReversalRecordEntity,
)

SEED_CARDS: Dict[str, float] = {
    "card_seed_1": 1000.00,
    "card_seed_2": 500.00,
    "card_seed_3": 2000.00,
}

SEED_MERCHANTS: Set[str] = {
    "Amazon",
    "Restaurant",
    "Target",
    "Starbucks",
    "Airline Offline",
}


class InMemoryDB:
    """Thread-safe in-memory database with granular lock registries."""

    def __init__(self):
        self._registry_lock = threading.Lock()
        self._idempotency_lock = threading.Lock()
        self._auths_lock = threading.Lock()
        self._clearings_lock = threading.Lock()
        self._reversals_lock = threading.Lock()

        self._card_locks: Dict[str, threading.RLock] = {}
        self._auth_locks: Dict[str, threading.RLock] = {}

        self.cards: Dict[str, CardRecordEntity] = {}
        self.merchants: Set[str] = set()
        self.authorizations: Dict[str, AuthorizationRecordEntity] = {}
        self.clearings: Dict[str, ClearingRecordEntity] = {}
        self.reversals: Dict[str, ReversalRecordEntity] = {}
        self.transactions: Dict[str, List[LedgerTransactionRecordEntity]] = {}
        self.idempotency: Dict[str, IdempotencyRecordEntity] = {}

        self.reset()

    def reset(self) -> None:
        """Reset database to initial seed state."""
        with self._registry_lock:
            self.cards = {
                card_id: CardRecordEntity(card_id=card_id, credit_limit=limit, settled_balance=0.0)
                for card_id, limit in SEED_CARDS.items()
            }
            self.merchants = set(SEED_MERCHANTS)
            self.authorizations.clear()
            self.clearings.clear()
            self.reversals.clear()
            self.transactions = {card_id: [] for card_id in SEED_CARDS}
            self.idempotency.clear()

            # Pre-seed card locks
            self._card_locks = {card_id: threading.RLock() for card_id in SEED_CARDS}
            self._auth_locks.clear()

    def get_card_lock(self, card_id: str) -> threading.RLock:
        """Get or initialize the object-level lock for a card."""
        with self._registry_lock:
            if card_id not in self._card_locks:
                self._card_locks[card_id] = threading.RLock()
            return self._card_locks[card_id]

    def get_auth_lock(self, auth_id: str) -> threading.RLock:
        """Get or initialize the object-level lock for an authorization."""
        with self._registry_lock:
            if auth_id not in self._auth_locks:
                self._auth_locks[auth_id] = threading.RLock()
            return self._auth_locks[auth_id]

    def is_valid_merchant(self, merchant: str) -> bool:
        """Check if merchant is in the seeded set."""
        return merchant in self.merchants

    def get_card(self, card_id: str) -> Optional[CardRecordEntity]:
        """Lookup card entity."""
        return self.cards.get(card_id)

    def get_authorization(self, auth_id: str) -> Optional[AuthorizationRecordEntity]:
        """Lookup authorization entity under registry lock."""
        with self._auths_lock:
            return self.authorizations.get(auth_id)

    def save_authorization(self, auth: AuthorizationRecordEntity) -> None:
        """Save authorization entity in registry."""
        with self._auths_lock:
            self.authorizations[auth.authorization_id] = auth
        # Ensure auth lock is seeded
        self.get_auth_lock(auth.authorization_id)

    def save_clearing(self, clearing: ClearingRecordEntity) -> None:
        """Save clearing entity in registry."""
        with self._clearings_lock:
            self.clearings[clearing.clearing_id] = clearing

    def save_reversal(self, reversal: ReversalRecordEntity) -> None:
        """Save reversal entity in registry."""
        with self._reversals_lock:
            self.reversals[reversal.reversal_id] = reversal

    def add_transaction(self, tx: LedgerTransactionRecordEntity) -> None:
        """Add transaction to card's ledger history."""
        if tx.card_id not in self.transactions:
            self.transactions[tx.card_id] = []
        self.transactions[tx.card_id].append(tx)

    def get_transactions(self, card_id: str) -> List[LedgerTransactionRecordEntity]:
        """Get copy of transaction history for card."""
        return list(self.transactions.get(card_id, []))

    def get_idempotency_record(self, key: str) -> Optional[IdempotencyRecordEntity]:
        """Lookup idempotency record under idempotency lock."""
        with self._idempotency_lock:
            return self.idempotency.get(key)

    def save_idempotency_record(self, record: IdempotencyRecordEntity) -> None:
        """Save idempotency record under idempotency lock."""
        with self._idempotency_lock:
            self.idempotency[record.idempotency_key] = record


# Global singleton instance
db = InMemoryDB()
