"""Adapter package exposing WalletAdapter, QuoteAdapter, and InMemoryDatabase."""

from app.adapter.database import InMemoryDatabase, default_db
from app.adapter.entities import (
    AccountRecordEntity,
    GreetingRecordEntity,
    LedgerLegRecordEntity,
    QuoteRecordEntity,
    TransactionRecordEntity,
)
from app.adapter.greeting_adapter import GreetingAdapter, greeting_adapter
from app.adapter.quote_adapter import QuoteAdapter, quote_adapter
from app.adapter.wallet_adapter import (
    WalletAdapter,
    compute_payload_hash,
    wallet_adapter,
)

__all__ = [
    "GreetingRecordEntity",
    "GreetingAdapter",
    "greeting_adapter",
    "AccountRecordEntity",
    "QuoteRecordEntity",
    "LedgerLegRecordEntity",
    "TransactionRecordEntity",
    "InMemoryDatabase",
    "default_db",
    "WalletAdapter",
    "wallet_adapter",
    "QuoteAdapter",
    "quote_adapter",
    "compute_payload_hash",
]
