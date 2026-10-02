"""Centralized thread-safe in-memory database engine holding raw tables and locks."""

import threading
from typing import Any, Dict, Optional

from app.adapter.entities import (
    AccountRecordEntity,
    IdempotencyRecordEntity,
    QuoteRecordEntity,
    TransactionRecordEntity,
)


class InMemoryDatabase:
    """Thread-safe in-memory database holding all data collections and account locks."""

    def __init__(self, seed: bool = True) -> None:
        self.accounts: Dict[str, AccountRecordEntity] = {}
        self.quotes: Dict[str, QuoteRecordEntity] = {}
        self.transactions: Dict[str, TransactionRecordEntity] = {}
        self.idempotency: Dict[str, IdempotencyRecordEntity] = {}
        self.rates: Dict[str, float] = {}
        self.fee_percentage: float = 0.01  # 1% standard fee
        self.account_locks: Dict[str, threading.RLock] = {}
        self.global_lock = threading.RLock()

        if seed:
            self.seed_base_state()

    def get_lock(self, account_id: str) -> threading.RLock:
        """Get or lazily create an RLock for an account in a thread-safe manner."""
        with self.global_lock:
            if account_id not in self.account_locks:
                self.account_locks[account_id] = threading.RLock()
            return self.account_locks[account_id]

    def seed_base_state(self) -> None:
        """Seed the in-memory database with initial users, balances, pools, and rates."""
        # Preloaded users and balances (in minor units: cents/units)
        users_seed = {
            "usr_alice": {"USD": 100000, "EUR": 50000, "GBP": 20000},
            "usr_bob": {"USD": 50000, "EUR": 100000, "GBP": 10000},
            "usr_charlie": {"USD": 25000, "EUR": 25000, "JPY": 5000000},
        }
        for user_id, balances in users_seed.items():
            for currency, amount in balances.items():
                acc_id = f"{user_id}:{currency}"
                self.accounts[acc_id] = AccountRecordEntity(
                    account_id=acc_id,
                    owner_id=user_id,
                    currency=currency,
                    balance=amount,
                    is_pool=False,
                )

        # Preloaded system settlement pools (USD, EUR, GBP, JPY)
        supported_currencies = ["USD", "EUR", "GBP", "JPY"]
        pool_prefixes = ["pool:outbound", "pool:inbound", "pool:fee"]
        for prefix in pool_prefixes:
            for curr in supported_currencies:
                acc_id = f"{prefix}:{curr}"
                self.accounts[acc_id] = AccountRecordEntity(
                    account_id=acc_id,
                    owner_id="system_pool",
                    currency=curr,
                    balance=0,
                    is_pool=True,
                )

        # Preloaded exchange rates table
        self.rates = {
            "USD/EUR": 0.92,
            "EUR/USD": 1.087,
            "USD/GBP": 0.78,
            "GBP/USD": 1.282,
            "USD/JPY": 155.0,
            "JPY/USD": 0.00645,
            "EUR/GBP": 0.85,
            "GBP/EUR": 1.176,
        }

    def reset(self) -> None:
        """Reset and re-seed the database for test isolation."""
        with self.global_lock:
            self.accounts.clear()
            self.quotes.clear()
            self.transactions.clear()
            self.idempotency.clear()
            self.rates.clear()
            self.account_locks.clear()
            self.seed_base_state()


# Shared singleton database instance
default_db = InMemoryDatabase()
