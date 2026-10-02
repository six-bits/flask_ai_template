"""Outbox manager providing scraping and acknowledgment for polling workers."""

from typing import List, Optional

from app.adapter.quote_adapter import QuoteAdapter, quote_adapter
from app.adapter.user_wallet_adapter import UserWalletAdapter, user_wallet_adapter
from app.manager.entities import (
    AckOutboxEventsRequestEntity,
    AckOutboxEventsResponseEntity,
    GetOutboxEventsRequestEntity,
    GetOutboxEventsResponseEntity,
    OutboxEventItemEntity,
)


class OutboxManager:
    """Manager coordinating outbox domain events scraping and delivery acknowledgment."""

    def __init__(
        self,
        wallet_adpt: Optional[UserWalletAdapter] = None,
        quote_adpt: Optional[QuoteAdapter] = None,
    ) -> None:
        self.wallet_adapter = wallet_adpt or user_wallet_adapter
        self.quote_adapter = quote_adpt or quote_adapter

    def get_events(self, request: GetOutboxEventsRequestEntity) -> GetOutboxEventsResponseEntity:
        """Scrape outbox events attached across all user entities, clearing pools, and quotes."""
        user_events = self.wallet_adapter.get_all_user_events()
        pool_events = self.wallet_adapter.get_all_pool_events()
        quote_events = self.quote_adapter.get_all_quote_events()

        all_events = user_events + pool_events + quote_events
        # Sort chronologically by timestamp
        all_events.sort(key=lambda e: e.timestamp)

        # Filter by status
        if request.status and request.status != "ALL":
            filtered = [e for e in all_events if e.status == request.status]
        else:
            filtered = all_events

        # Enforce limit
        limit = request.limit if request.limit and request.limit > 0 else 50
        sliced = filtered[:limit]

        items = [
            OutboxEventItemEntity(
                event_id=e.event_id,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                event_type=e.event_type,
                payload=e.payload,
                timestamp=e.timestamp,
                status=e.status,
            )
            for e in sliced
        ]

        return GetOutboxEventsResponseEntity(
            events=items,
            total=len(filtered),
        )

    def ack_events(self, request: AckOutboxEventsRequestEntity) -> AckOutboxEventsResponseEntity:
        """Acknowledge delivered events, updating their status on host entities from PENDING to PUBLISHED."""
        wallet_acked = self.wallet_adapter.mark_outbox_events_published(request.event_ids)
        quote_acked = self.quote_adapter.mark_outbox_events_published(request.event_ids)

        # Combine acknowledged IDs preserving uniqueness
        acknowledged = list(dict.fromkeys(wallet_acked + quote_acked))
        return AckOutboxEventsResponseEntity(
            acknowledged_ids=acknowledged,
            count=len(acknowledged),
        )


# Default singleton instance
outbox_manager = OutboxManager()
