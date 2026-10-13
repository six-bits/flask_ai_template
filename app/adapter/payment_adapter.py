"""Adapter layer for card payment service interacting with the in-memory database."""

import threading
from typing import List, Optional

from app.adapter.db import InMemoryDB, db
from app.adapter.entities import (
    AuthorizationRecordEntity,
    CardRecordEntity,
    ClearingRecordEntity,
    IdempotencyRecordEntity,
    LedgerTransactionRecordEntity,
    ReversalRecordEntity,
)


class PaymentAdapter:
    """Adapter bridging Manager layer to in-memory persistence."""

    def __init__(self, database: Optional[InMemoryDB] = None):
        self.db = database or db

    def get_card_lock(self, card_id: str) -> threading.RLock:
        return self.db.get_card_lock(card_id)

    def get_auth_lock(self, auth_id: str) -> threading.RLock:
        return self.db.get_auth_lock(auth_id)

    def is_valid_merchant(self, merchant: str) -> bool:
        return self.db.is_valid_merchant(merchant)

    def get_card(self, card_id: str) -> Optional[CardRecordEntity]:
        return self.db.get_card(card_id)

    def get_authorization(self, auth_id: str) -> Optional[AuthorizationRecordEntity]:
        return self.db.get_authorization(auth_id)

    def save_authorization(self, auth: AuthorizationRecordEntity) -> None:
        self.db.save_authorization(auth)

    def save_clearing(self, clearing: ClearingRecordEntity) -> None:
        self.db.save_clearing(clearing)

    def save_reversal(self, reversal: ReversalRecordEntity) -> None:
        self.db.save_reversal(reversal)

    def add_transaction(self, tx: LedgerTransactionRecordEntity) -> None:
        self.db.add_transaction(tx)

    def get_card_transactions(self, card_id: str) -> List[LedgerTransactionRecordEntity]:
        return self.db.get_transactions(card_id)

    def get_idempotency_record(self, key: str) -> Optional[IdempotencyRecordEntity]:
        return self.db.get_idempotency_record(key)

    def save_idempotency_record(self, record: IdempotencyRecordEntity) -> None:
        self.db.save_idempotency_record(record)

    def get_active_held_balance(self, card_id: str, now: float) -> float:
        """Calculate sum of active, unexpired, and unreversed holds for card."""
        held_total = 0.0
        with self.db._auths_lock:
            for auth in self.db.authorizations.values():
                if auth.card_id == card_id and auth.status == "APPROVED":
                    if now >= auth.expires_at:
                        auth.status = "EXPIRED"
                        auth.remaining_held_amount = 0.0
                    else:
                        held_total += auth.remaining_held_amount
        return held_total


payment_adapter = PaymentAdapter()
