"""Adapter entities defining the data contract between Manager and Adapter layers."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class GreetingRecordEntity:
    """Storage/persistence entity for greeting records in the adapter."""
    name: str
    salutation: str
    message: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert adapter entity to dictionary."""
        return asdict(self)


@dataclass
class AccountRecordEntity:
    """Storage entity for a currency account (user or settlement pool)."""
    account_id: str          # e.g. "usr_alice:USD", "pool:outbound:USD"
    owner_id: str            # e.g. "usr_alice" or "system_pool"
    currency: str            # e.g. "USD"
    balance: int             # Minor units (e.g. 100000 = $1,000.00)
    is_pool: bool = False
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuoteRecordEntity:
    """Storage entity for an FX rate quote."""
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int         # Minor units
    exchange_rate: float
    gross_to_amount: int     # Minor units
    fee_percentage: float
    fee_amount: int          # Minor units
    net_to_amount: int       # Minor units
    expires_at: str          # ISO-8601 timestamp string
    status: str = "PENDING"  # PENDING | ACCEPTED | EXPIRED
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerLegRecordEntity:
    """Storage entity for a single movement leg between two accounts."""
    leg_id: str
    transaction_id: str
    step_number: int
    from_account_id: str
    to_account_id: str
    currency: str
    amount: int              # Minor units
    is_reversal: bool = False
    status: str = "COMPLETED"  # COMPLETED | FAILED
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransactionRecordEntity:
    """Storage entity for a high-level transaction grouping multiple legs."""
    transaction_id: str
    user_id: str
    transaction_type: str    # P2P_TRANSFER | FX_CONVERSION
    status: str              # COMPLETED | FAILED | REVERSED
    legs: List[LedgerLegRecordEntity] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdempotencyRecordEntity:
    """Storage entity for tracking idempotent API requests."""
    idempotency_key: str
    status: str              # PROCESSING | COMPLETED
    response_code: int = 0
    response_data: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
