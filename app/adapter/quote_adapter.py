"""Quote Adapter handling quote persistence, quote lifecycle, and exchange rates."""

from typing import Dict, Optional

from app.adapter.database import InMemoryDatabase, default_db
from app.adapter.entities import QuoteRecordEntity


class QuoteAdapter:
    """
    Adapter responsible for FX quotes persistence, quote TTL/status management,
    and exchange rates querying.
    """

    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or default_db

    def save_quote(self, quote: QuoteRecordEntity) -> QuoteRecordEntity:
        """Persist an FX quote."""
        with self.db.global_lock:
            self.db.quotes[quote.quote_id] = quote
            return quote

    def get_quote(self, quote_id: str) -> Optional[QuoteRecordEntity]:
        """Retrieve an FX quote by quote_id."""
        with self.db.global_lock:
            return self.db.quotes.get(quote_id)

    def update_quote_status(self, quote_id: str, status: str) -> None:
        """Update status of a quote (ACCEPTED, EXPIRED, FAILED)."""
        with self.db.global_lock:
            if quote_id in self.db.quotes:
                self.db.quotes[quote_id].status = status

    def get_rate(self, from_curr: str, to_curr: str) -> Optional[float]:
        """Retrieve exchange rate for a currency pair."""
        if from_curr == to_curr:
            return 1.0
        with self.db.global_lock:
            return self.db.rates.get(f"{from_curr}/{to_curr}")

    def get_all_rates(self) -> Dict[str, float]:
        """Retrieve all configured exchange rates."""
        with self.db.global_lock:
            return dict(self.db.rates)

    def get_fee_percentage(self) -> float:
        """Return the standard fee percentage configured for quotes."""
        return self.db.fee_percentage


# Default singleton instance
quote_adapter = QuoteAdapter()
