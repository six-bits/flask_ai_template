"""Centralized in-memory database engine holding raw collections without global locks."""

from typing import Dict

from app.adapter.entities import (
    AccountRecordEntity,
    QuoteRecordEntity,
    TransactionRecordEntity,
)


class InMemoryDatabase:
    """
    In-memory database holding all data collections.
    Does NOT use global locks; resource-level locks live directly inside AccountRecordEntity.
    """

    def __init__(self, seed: bool = True) -> None:
        self.accounts: Dict[str, AccountRecordEntity] = {}
        self.quotes: Dict[str, QuoteRecordEntity] = {}
        self.transactions: Dict[str, TransactionRecordEntity] = {}
        self.transactions_by_idempotency: Dict[str, TransactionRecordEntity] = {}
        self.rates: Dict[str, float] = {}
        self.fee_percentage: float = 0.01  # 1% standard fee

        if seed:
            self.seed_base_state()

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
        self.accounts.clear()
        self.quotes.clear()
        self.transactions.clear()
        self.transactions_by_idempotency.clear()
        self.rates.clear()
        self.seed_base_state()


# Shared singleton database instance
default_db = InMemoryDatabase()
