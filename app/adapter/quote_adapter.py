"""Adapter managing persistence of exchange rate quotes and quote outbox events."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from app.adapter.entities import OutboxEventRecordEntity, QuoteRecordEntity


class QuoteAdapter:
    """In-memory persistence adapter managing quotes and attached outbox events."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Clear all stored quotes."""
        self._quotes: Dict[str, QuoteRecordEntity] = {}

    def save_quote(self, quote: QuoteRecordEntity) -> QuoteRecordEntity:
        """Persist a quote and attach QUOTE_CREATED domain event directly to the quote entity."""
        event = OutboxEventRecordEntity(
            event_id=f"evt_quote_create_{uuid.uuid4().hex[:8]}",
            entity_type="QUOTE",
            entity_id=quote.quote_id,
            event_type="QUOTE_CREATED",
            payload={
                "from_currency": quote.from_currency,
                "to_currency": quote.to_currency,
                "from_amount": quote.from_amount,
                "to_amount": quote.to_amount,
                "exchange_rate": quote.exchange_rate,
                "fee_amount": quote.fee_amount,
                "expires_at": quote.expires_at,
            },
            timestamp=quote.created_at,
            status="PENDING",
        )
        quote.outbox_events.append(event)
        self._quotes[quote.quote_id] = quote
        return quote

    def get_quote(self, quote_id: str) -> Optional[QuoteRecordEntity]:
        """Retrieve quote by its unique identifier."""
        return self._quotes.get(quote_id)

    def update_status(self, quote_id: str, status: str) -> Optional[QuoteRecordEntity]:
        """Update quote status and attach lifecycle event directly to the quote entity."""
        quote = self._quotes.get(quote_id)
        if quote is None:
            return None

        quote.status = status
        now_ts = datetime.now(timezone.utc).isoformat()

        if status == "ACCEPTED":
            event = OutboxEventRecordEntity(
                event_id=f"evt_quote_accept_{uuid.uuid4().hex[:8]}",
                entity_type="QUOTE",
                entity_id=quote.quote_id,
                event_type="QUOTE_ACCEPTED",
                payload={"status": "ACCEPTED", "executed_at": now_ts},
                timestamp=now_ts,
                status="PENDING",
            )
            quote.outbox_events.append(event)

        return quote

    def get_all_quote_events(self) -> List[OutboxEventRecordEntity]:
        """Scrape all outbox events across all stored quotes."""
        events: List[OutboxEventRecordEntity] = []
        for quote in self._quotes.values():
            events.extend(quote.outbox_events)
        return events

    def mark_outbox_events_published(self, event_ids: List[str]) -> List[str]:
        """Mark matching quote outbox events as PUBLISHED."""
        target_ids = set(event_ids)
        acknowledged: List[str] = []

        for quote in self._quotes.values():
            for evt in quote.outbox_events:
                if evt.event_id in target_ids:
                    evt.status = "PUBLISHED"
                    acknowledged.append(evt.event_id)

        return acknowledged


# Default singleton instance
quote_adapter = QuoteAdapter()
