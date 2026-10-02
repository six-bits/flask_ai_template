"""Adapter entities defining the data contracts between Manager and Adapter layers."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OutboxEventRecordEntity:
    """Storage entity representing a domain event attached directly to an aggregate entity."""
    event_id: str
    entity_type: str  # USER_WALLET, CLEARING_POOL, QUOTE
    entity_id: str  # e.g. "user_1", "SYSTEM_OUTBOUND", "quote_abc123"
    event_type: str  # e.g. "TRANSFER_OUTBOUND_COMMITTED"
    payload: Dict[str, Any]
    timestamp: str
    status: str = "PENDING"  # PENDING, PUBLISHED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UserRecordEntity:
    """Storage entity representing a user, multi-currency balances, and attached outbox events."""
    user_id: str
    name: str
    balances: Dict[str, int]
    outbox_events: List[OutboxEventRecordEntity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "balances": self.balances,
            "outbox_events": [e.to_dict() for e in self.outbox_events],
        }


@dataclass
class PoolRecordEntity:
    """Storage entity representing a system clearing pool and its attached outbox events."""
    pool_id: str  # "SYSTEM_OUTBOUND", "SYSTEM_INBOUND", "SYSTEM_FEES"
    balances: Dict[str, int]
    outbox_events: List[OutboxEventRecordEntity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "balances": self.balances,
            "outbox_events": [e.to_dict() for e in self.outbox_events],
        }


@dataclass
class ExchangeRateRecordEntity:
    """Storage entity representing an exchange rate between two currencies."""
    from_currency: str
    to_currency: str
    rate: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuoteRecordEntity:
    """Storage entity representing a 30-second locked exchange quote with attached outbox events."""
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int
    to_amount: int
    exchange_rate: str
    fee_amount: int
    fee_percentage: str
    created_at: str
    expires_at: str
    status: str  # PENDING, ACCEPTED, EXPIRED
    outbox_events: List[OutboxEventRecordEntity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quote_id": self.quote_id,
            "user_id": self.user_id,
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "from_amount": self.from_amount,
            "to_amount": self.to_amount,
            "exchange_rate": self.exchange_rate,
            "fee_amount": self.fee_amount,
            "fee_percentage": self.fee_percentage,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "outbox_events": [e.to_dict() for e in self.outbox_events],
        }


@dataclass
class TransactionRecordEntity:
    """Storage entity representing a transaction ledger event."""
    transaction_id: str
    user_id: str
    type: str  # CONVERSION, TRANSFER_SENT, TRANSFER_RECEIVED
    currency: Optional[str] = None
    from_currency: Optional[str] = None
    to_currency: Optional[str] = None
    from_amount: Optional[int] = None
    to_amount: Optional[int] = None
    amount: Optional[int] = None
    fee_amount: Optional[int] = None
    related_user_id: Optional[str] = None
    quote_id: Optional[str] = None
    timestamp: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GreetingRecordEntity:
    """Storage/persistence entity for greeting records in the adapter."""
    name: str
    salutation: str
    message: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdempotencyRecordEntity:
    """Storage entity representing an idempotency key and cached response."""
    key: str
    user_id: str
    endpoint: str
    request_hash: str
    status: str  # "IN_PROGRESS", "COMPLETED", "FAILED"
    status_code: int = 200
    response_body: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

