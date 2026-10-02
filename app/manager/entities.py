"""Domain entities defining data contracts between Service and Manager layers."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GetBalancesRequestEntity:
    """Request entity to query balances for a user."""
    user_id: str


@dataclass
class GetBalancesResponseEntity:
    """Response entity containing minor unit balances for a user."""
    user_id: str
    balances: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CreateQuoteRequestEntity:
    """Request entity to create a 30s locked exchange rate quote."""
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int


@dataclass
class QuoteResponseEntity:
    """Response entity with locked rate, fee, and net amount."""
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
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptQuoteRequestEntity:
    """Request entity to accept an active quote."""
    quote_id: str
    user_id: str
    idempotency_key: Optional[str] = None
    request_payload_json: str = ""


@dataclass
class AcceptQuoteResponseEntity:
    """Response entity after conversion execution."""
    quote_id: str
    status: str
    from_currency: str
    to_currency: str
    from_amount: int
    to_amount: int
    fee_amount: int
    executed_at: str
    balances: Dict[str, int]
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("is_replayed", None)
        return d


@dataclass
class TransferRequestEntity:
    """Request entity for peer-to-peer transfer."""
    from_user_id: str
    to_user_id: str
    currency: str
    amount: int
    idempotency_key: Optional[str] = None
    request_payload_json: str = ""


@dataclass
class TransferResponseEntity:
    """Response entity after transfer execution."""
    transfer_id: str
    from_user_id: str
    to_user_id: str
    currency: str
    amount: int
    timestamp: str
    from_user_balance: int
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("is_replayed", None)
        return d


@dataclass
class TransactionItemEntity:
    """Domain entity representing a single transaction in user history."""
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
class GetTransactionsRequestEntity:
    """Request entity to query transaction ledger for a user."""
    user_id: str


@dataclass
class GetTransactionsResponseEntity:
    """Response entity containing a user's chronological transaction history."""
    user_id: str
    transactions: List[TransactionItemEntity]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "transactions": [tx.to_dict() for tx in self.transactions],
        }


@dataclass
class GreetingRequestEntity:
    """Entity representing an incoming greeting request."""
    name: str
    salutation: str = "Hello"


@dataclass
class GreetingResponseEntity:
    """Entity representing a processed greeting response."""
    message: str
    salutation: str
    name: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GetOutboxEventsRequestEntity:
    """Request entity to query outbox domain events."""
    status: str = "PENDING"
    limit: int = 50


@dataclass
class OutboxEventItemEntity:
    """Domain entity representing a single outbox event item."""
    event_id: str
    entity_type: str  # USER_WALLET, CLEARING_POOL, QUOTE
    entity_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: str
    status: str  # PENDING, PUBLISHED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GetOutboxEventsResponseEntity:
    """Response entity containing scraped outbox events and total count."""
    events: List[OutboxEventItemEntity]
    total: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "total": self.total,
        }


@dataclass
class AckOutboxEventsRequestEntity:
    """Request entity to acknowledge delivery of outbox events."""
    event_ids: List[str]


@dataclass
class AckOutboxEventsResponseEntity:
    """Response entity after acknowledging outbox events."""
    acknowledged_ids: List[str]
    count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


