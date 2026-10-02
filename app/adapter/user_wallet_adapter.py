import threading
from typing import Dict, List, Optional
import uuid

from app.adapter.entities import OutboxEventRecordEntity, PoolRecordEntity, UserRecordEntity


class UserWalletAdapter:
    """In-memory persistence adapter managing user wallets, clearing pools, and domain events."""

    def __init__(self) -> None:
        self._pool_lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Reset wallets, clearing pools, and attached outbox events to initial seed state."""
        self._users: Dict[str, UserRecordEntity] = {
            "user_1": UserRecordEntity(
                user_id="user_1",
                name="Alice",
                balances={"USD": 100000, "EUR": 50000, "GBP": 10000},
                outbox_events=[],
            ),
            "user_2": UserRecordEntity(
                user_id="user_2",
                name="Bob",
                balances={"USD": 25000, "EUR": 0, "GBP": 30000},
                outbox_events=[],
            ),
            "user_3": UserRecordEntity(
                user_id="user_3",
                name="Charlie",
                balances={"USD": 5000, "EUR": 120000, "GBP": 5000},
                outbox_events=[],
            ),
        }

        self._pools: Dict[str, PoolRecordEntity] = {
            "SYSTEM_OUTBOUND": PoolRecordEntity(
                pool_id="SYSTEM_OUTBOUND",
                balances={"USD": 0, "EUR": 0, "GBP": 0},
                outbox_events=[],
            ),
            "SYSTEM_INBOUND": PoolRecordEntity(
                pool_id="SYSTEM_INBOUND",
                balances={"USD": 0, "EUR": 0, "GBP": 0},
                outbox_events=[],
            ),
            "SYSTEM_FEES": PoolRecordEntity(
                pool_id="SYSTEM_FEES",
                balances={"USD": 0, "EUR": 0, "GBP": 0},
                outbox_events=[],
            ),
        }

    # ---------------------------------------------------------------------
    # Read Methods
    # ---------------------------------------------------------------------

    def get_user(self, user_id: str) -> Optional[UserRecordEntity]:
        """Retrieve user record entity."""
        user = self._users.get(user_id)
        if user is None:
            return None
        return UserRecordEntity(
            user_id=user.user_id,
            name=user.name,
            balances=user.balances.copy(),
            outbox_events=list(user.outbox_events),
        )

    def user_exists(self, user_id: str) -> bool:
        """Check if user exists."""
        return user_id in self._users

    def get_balance(self, user_id: str, currency: str) -> int:
        """Get user balance in minor units."""
        user = self._users.get(user_id)
        if not user:
            return 0
        return user.balances.get(currency, 0)

    def get_transit_pool_balances(self) -> Dict[str, Dict[str, int]]:
        """Return snapshot of system transit and fee pools for audit reconciliation."""
        with self._pool_lock:
            return {
                "outbound": self._pools["SYSTEM_OUTBOUND"].balances.copy(),
                "inbound": self._pools["SYSTEM_INBOUND"].balances.copy(),
                "fees": self._pools["SYSTEM_FEES"].balances.copy(),
            }

    # ---------------------------------------------------------------------
    # P2P Transfer Multi-Stage State Machine Methods
    # ---------------------------------------------------------------------

    def debit_sender_to_outbound(
        self, sender_id: str, currency: str, amount: int, transfer_id: str, timestamp: str
    ) -> int:
        """Stage 1: Debit sender account and credit SYSTEM_OUTBOUND pool.

        Attaches TRANSFER_OUTBOUND_COMMITTED to the sender entity.
        """
        sender = self._users[sender_id]
        current_balance = sender.balances.get(currency, 0)
        if current_balance < amount:
            raise ValueError(f"Insufficient funds: have {current_balance}, need {amount}")

        sender.balances[currency] = current_balance - amount
        with self._pool_lock:
            self._pools["SYSTEM_OUTBOUND"].balances[currency] = (
                self._pools["SYSTEM_OUTBOUND"].balances.get(currency, 0) + amount
            )

        event = OutboxEventRecordEntity(
            event_id=f"evt_tx_out_{uuid.uuid4().hex[:8]}",
            entity_type="USER_WALLET",
            entity_id=sender_id,
            event_type="TRANSFER_OUTBOUND_COMMITTED",
            payload={
                "transfer_id": transfer_id,
                "currency": currency,
                "amount": amount,
                "remaining_balance": sender.balances[currency],
            },
            timestamp=timestamp,
            status="PENDING",
        )
        sender.outbox_events.append(event)
        return sender.balances[currency]

    def route_outbound_to_inbound(
        self, currency: str, amount: int, transfer_id: str, timestamp: str
    ) -> None:
        """Stage 2: Debit SYSTEM_OUTBOUND and credit SYSTEM_INBOUND pool.

        Attaches TRANSIT_POOL_CLEARED to the Outbound Pool entity.
        """
        with self._pool_lock:
            outbound = self._pools["SYSTEM_OUTBOUND"].balances.get(currency, 0)
            if outbound < amount:
                raise ValueError(f"Outbound transit underflow: have {outbound}, need {amount}")

            self._pools["SYSTEM_OUTBOUND"].balances[currency] = outbound - amount
            self._pools["SYSTEM_INBOUND"].balances[currency] = (
                self._pools["SYSTEM_INBOUND"].balances.get(currency, 0) + amount
            )

            event = OutboxEventRecordEntity(
                event_id=f"evt_pool_hop_{uuid.uuid4().hex[:8]}",
                entity_type="CLEARING_POOL",
                entity_id="SYSTEM_OUTBOUND",
                event_type="TRANSIT_POOL_CLEARED",
                payload={
                    "transfer_id": transfer_id,
                    "from_pool": "SYSTEM_OUTBOUND",
                    "to_pool": "SYSTEM_INBOUND",
                    "currency": currency,
                    "amount": amount,
                },
                timestamp=timestamp,
                status="PENDING",
            )
            self._pools["SYSTEM_OUTBOUND"].outbox_events.append(event)

    def settle_inbound_to_recipient(
        self, recipient_id: str, currency: str, amount: int, transfer_id: str, timestamp: str
    ) -> int:
        """Stage 3: Debit SYSTEM_INBOUND and credit recipient account.

        Attaches TRANSFER_INBOUND_SETTLED to the recipient entity.
        """
        with self._pool_lock:
            inbound = self._pools["SYSTEM_INBOUND"].balances.get(currency, 0)
            if inbound < amount:
                raise ValueError(f"Inbound transit underflow: have {inbound}, need {amount}")

            self._pools["SYSTEM_INBOUND"].balances[currency] = inbound - amount

        recipient = self._users[recipient_id]
        recipient.balances[currency] = recipient.balances.get(currency, 0) + amount

        event = OutboxEventRecordEntity(
            event_id=f"evt_tx_in_{uuid.uuid4().hex[:8]}",
            entity_type="USER_WALLET",
            entity_id=recipient_id,
            event_type="TRANSFER_INBOUND_SETTLED",
            payload={
                "transfer_id": transfer_id,
                "currency": currency,
                "amount": amount,
                "updated_balance": recipient.balances[currency],
            },
            timestamp=timestamp,
            status="PENDING",
        )
        recipient.outbox_events.append(event)
        return recipient.balances[currency]

    # ---------------------------------------------------------------------
    # Currency Conversion Multi-Stage State Machine Methods
    # ---------------------------------------------------------------------

    def debit_user_for_conversion(
        self, user_id: str, currency: str, amount: int, quote_id: str, timestamp: str
    ) -> int:
        """Stage 1: Debit user source currency and credit SYSTEM_OUTBOUND.

        Attaches CONVERSION_OUTBOUND_COMMITTED to user's wallet entity.
        """
        user = self._users[user_id]
        current_balance = user.balances.get(currency, 0)
        if current_balance < amount:
            raise ValueError(f"Insufficient funds: have {current_balance}, need {amount}")

        user.balances[currency] = current_balance - amount
        with self._pool_lock:
            self._pools["SYSTEM_OUTBOUND"].balances[currency] = (
                self._pools["SYSTEM_OUTBOUND"].balances.get(currency, 0) + amount
            )

        event = OutboxEventRecordEntity(
            event_id=f"evt_conv_out_{uuid.uuid4().hex[:8]}",
            entity_type="USER_WALLET",
            entity_id=user_id,
            event_type="CONVERSION_OUTBOUND_COMMITTED",
            payload={
                "quote_id": quote_id,
                "currency": currency,
                "amount": amount,
                "remaining_balance": user.balances[currency],
            },
            timestamp=timestamp,
            status="PENDING",
        )
        user.outbox_events.append(event)
        return user.balances[currency]

    def clear_fx_pools(
        self,
        from_curr: str,
        to_curr: str,
        from_amount: int,
        to_amount: int,
        fee_amount: int,
        quote_id: str,
        timestamp: str,
    ) -> None:
        """Stage 2: Absorb source currency from outbound pool, allocate fee to fee collector,

        and credit net target currency to inbound pool.
        Attaches CONVERSION_FX_CLEARED to Outbound Pool entity.
        """
        with self._pool_lock:
            outbound = self._pools["SYSTEM_OUTBOUND"].balances.get(from_curr, 0)
            if outbound < from_amount:
                raise ValueError(f"Outbound source underflow: have {outbound}, need {from_amount}")

            self._pools["SYSTEM_OUTBOUND"].balances[from_curr] = outbound - from_amount
            self._pools["SYSTEM_FEES"].balances[to_curr] = (
                self._pools["SYSTEM_FEES"].balances.get(to_curr, 0) + fee_amount
            )
            self._pools["SYSTEM_INBOUND"].balances[to_curr] = (
                self._pools["SYSTEM_INBOUND"].balances.get(to_curr, 0) + to_amount
            )

            event = OutboxEventRecordEntity(
                event_id=f"evt_conv_fx_{uuid.uuid4().hex[:8]}",
                entity_type="CLEARING_POOL",
                entity_id="SYSTEM_OUTBOUND",
                event_type="CONVERSION_FX_CLEARED",
                payload={
                    "quote_id": quote_id,
                    "from_currency": from_curr,
                    "from_amount": from_amount,
                    "to_currency": to_curr,
                    "to_amount": to_amount,
                    "fee_amount": fee_amount,
                },
                timestamp=timestamp,
                status="PENDING",
            )
            self._pools["SYSTEM_OUTBOUND"].outbox_events.append(event)

    def credit_user_from_inbound(
        self, user_id: str, currency: str, amount: int, quote_id: str, timestamp: str
    ) -> int:
        """Stage 3: Debit SYSTEM_INBOUND and credit user's target currency.

        Attaches CONVERSION_INBOUND_SETTLED to user's wallet entity.
        """
        with self._pool_lock:
            inbound = self._pools["SYSTEM_INBOUND"].balances.get(currency, 0)
            if inbound < amount:
                raise ValueError(f"Inbound transit underflow: have {inbound}, need {amount}")

            self._pools["SYSTEM_INBOUND"].balances[currency] = inbound - amount

        user = self._users[user_id]
        user.balances[currency] = user.balances.get(currency, 0) + amount

        event = OutboxEventRecordEntity(
            event_id=f"evt_conv_in_{uuid.uuid4().hex[:8]}",
            entity_type="USER_WALLET",
            entity_id=user_id,
            event_type="CONVERSION_INBOUND_SETTLED",
            payload={
                "quote_id": quote_id,
                "currency": currency,
                "amount": amount,
                "updated_balance": user.balances[currency],
            },
            timestamp=timestamp,
            status="PENDING",
        )
        user.outbox_events.append(event)
        return user.balances[currency]

    # ---------------------------------------------------------------------
    # Outbox Scraper & Acknowledgment Methods
    # ---------------------------------------------------------------------

    def get_all_user_events(self) -> List[OutboxEventRecordEntity]:
        """Collect all outbox events attached across all user entities."""
        events: List[OutboxEventRecordEntity] = []
        for user in self._users.values():
            events.extend(user.outbox_events)
        return events

    def get_all_pool_events(self) -> List[OutboxEventRecordEntity]:
        """Collect all outbox events attached to clearing pools."""
        with self._pool_lock:
            events: List[OutboxEventRecordEntity] = []
            for pool in self._pools.values():
                events.extend(pool.outbox_events)
            return events

    def mark_outbox_events_published(self, event_ids: List[str]) -> List[str]:
        """Mark matching events across users and pools as PUBLISHED."""
        target_ids = set(event_ids)
        acknowledged: List[str] = []

        for user in self._users.values():
            for evt in user.outbox_events:
                if evt.event_id in target_ids:
                    evt.status = "PUBLISHED"
                    acknowledged.append(evt.event_id)

        for pool in self._pools.values():
            for evt in pool.outbox_events:
                if evt.event_id in target_ids:
                    evt.status = "PUBLISHED"
                    acknowledged.append(evt.event_id)

        return acknowledged


# Default singleton instance
user_wallet_adapter = UserWalletAdapter()
