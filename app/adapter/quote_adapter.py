from datetime import datetime
from typing import Dict, Optional

from app.adapter.database import InMemoryDatabase, default_db
from app.adapter.entities import QuoteRecordEntity
from app.exceptions import InvalidQuoteError, QuoteExpiredError, QuoteNotFoundError


class QuoteAdapter:
    """
    Adapter responsible for FX quotes persistence, quote TTL/status management,
    and exchange rates querying. Uses per-quote locking for atomic claims.
    """

    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or default_db

    def save_quote(self, quote: QuoteRecordEntity) -> QuoteRecordEntity:
        """Persist an FX quote."""
        self.db.quotes[quote.quote_id] = quote
        return quote

    def get_quote(self, quote_id: str) -> Optional[QuoteRecordEntity]:
        """Retrieve an FX quote by quote_id."""
        return self.db.quotes.get(quote_id)

    def claim_quote_for_execution(self, quote_id: str, user_id: str) -> QuoteRecordEntity:
        """
        Thread-safely validates and claims a quote for execution.
        Acquires quote.lock, verifies existence, ownership, TTL, and status == 'PENDING',
        then transitions status to 'PROCESSING'.
        """
        quote = self.get_quote(quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{quote_id}' does not exist")

        with quote.lock:
            if quote.user_id != user_id:
                raise InvalidQuoteError("Quote does not belong to the requesting user")

            if quote.status != "PENDING":
                raise InvalidQuoteError(f"Quote '{quote_id}' is already {quote.status}")

            clean_expiry = quote.expires_at.rstrip("Z")
            expires_dt = datetime.fromisoformat(clean_expiry)
            if datetime.utcnow() > expires_dt:
                quote.status = "EXPIRED"
                raise QuoteExpiredError(
                    f"Quote '{quote.quote_id}' has expired (validity was 30 seconds)"
                )

            # Atomically claim quote
            quote.status = "PROCESSING"
            return quote

    def update_quote_status(self, quote_id: str, status: str) -> None:
        """Update status of a quote (ACCEPTED, EXPIRED, FAILED)."""
        if quote_id in self.db.quotes:
            quote = self.db.quotes[quote_id]
            with quote.lock:
                quote.status = status

    def get_rate(self, from_curr: str, to_curr: str) -> Optional[float]:
        """Retrieve exchange rate for a currency pair."""
        if from_curr == to_curr:
            return 1.0
        return self.db.rates.get(f"{from_curr}/{to_curr}")

    def get_all_rates(self) -> Dict[str, float]:
        """Retrieve all configured exchange rates."""
        return dict(self.db.rates)

    def get_fee_percentage(self) -> float:
        """Return the standard fee percentage configured for quotes."""
        return self.db.fee_percentage


# Default singleton instance
quote_adapter = QuoteAdapter()
