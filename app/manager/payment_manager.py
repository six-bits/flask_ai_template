"""Payment manager implementing business logic, multi-clearing math, and granular concurrency control."""

import datetime
import hashlib
import json
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from app.adapter.entities import (
    AuthorizationRecordEntity,
    ClearingRecordEntity,
    IdempotencyRecordEntity,
    LedgerTransactionRecordEntity,
    ReversalRecordEntity,
)
from app.adapter.payment_adapter import PaymentAdapter, payment_adapter
from app.manager.entities import (
    AuthorizationRequestEntity,
    ClearingRequestEntity,
    ReversalRequestEntity,
)


def compute_request_hash(method: str, path: str, body: Optional[Dict[str, Any]]) -> str:
    """Compute deterministic SHA-256 hash of canonical HTTP request components."""
    serialized_body = json.dumps(body or {}, sort_keys=True, separators=(",", ":"))
    raw = f"{method.upper()}:{path}:{serialized_body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PaymentManager:
    """Coordinates card authorization, clearing, reversal, and balance logic."""

    def __init__(self, adapter: Optional[PaymentAdapter] = None):
        self.adapter = adapter or payment_adapter

    def _format_iso(self, ts: float) -> str:
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()

    def _save_idempotency(
        self,
        key: str,
        card_id: str,
        request_hash: str,
        status_code: int,
        body: Dict[str, Any],
        now: float,
    ) -> None:
        record = IdempotencyRecordEntity(
            idempotency_key=key,
            card_id=card_id,
            request_hash=request_hash,
            status_code=status_code,
            response_body=body,
            created_at=now,
        )
        self.adapter.save_idempotency_record(record)

    def create_authorization(
        self, req: AuthorizationRequestEntity, request_hash: str
    ) -> Tuple[int, Dict[str, Any], bool]:
        """Place a temporary hold for 60 seconds against available credit limit."""
        # 1. Check idempotency
        record = self.adapter.get_idempotency_record(req.idempotency_key)
        if record:
            if record.request_hash == request_hash:
                return record.status_code, record.response_body, True
            return 409, {"error": "Conflict", "message": "Idempotency key reused with different request payload"}, False

        # 2. Seed validations
        card = self.adapter.get_card(req.card_id)
        if not card:
            return 404, {"error": "Not Found", "message": f"Card '{req.card_id}' not found"}, False

        if not self.adapter.is_valid_merchant(req.merchant):
            return 400, {"error": "Validation error", "message": f"Merchant '{req.merchant}' is not recognized"}, False

        # 3. Acquire granular card lock
        card_lock = self.adapter.get_card_lock(req.card_id)
        with card_lock:
            # Re-check idempotency under lock
            record = self.adapter.get_idempotency_record(req.idempotency_key)
            if record:
                if record.request_hash == request_hash:
                    return record.status_code, record.response_body, True
                return 409, {"error": "Conflict", "message": "Idempotency key reused with different request payload"}, False

            now = time.time()
            active_held = self.adapter.get_active_held_balance(req.card_id, now)
            available_limit = card.credit_limit - card.settled_balance - active_held

            if req.amount > available_limit:
                body = {
                    "error": "INSUFFICIENT_FUNDS",
                    "message": "Hold amount exceeds available limit",
                    "card_id": req.card_id,
                    "amount": req.amount,
                    "available_limit": round(available_limit, 2),
                    "status": "DECLINED",
                }
                self._save_idempotency(req.idempotency_key, req.card_id, request_hash, 422, body, now)
                return 422, body, False

            # Hold approved
            auth_id = f"auth_{uuid.uuid4().hex[:8]}"
            expires_at = now + 60.0
            auth_record = AuthorizationRecordEntity(
                authorization_id=auth_id,
                card_id=req.card_id,
                merchant=req.merchant,
                original_amount=req.amount,
                remaining_held_amount=req.amount,
                status="APPROVED",
                created_at=now,
                expires_at=expires_at,
            )
            self.adapter.save_authorization(auth_record)

            tx_record = LedgerTransactionRecordEntity(
                transaction_id=auth_id,
                card_id=req.card_id,
                type="AUTHORIZATION",
                amount=req.amount,
                merchant=req.merchant,
                status="APPROVED",
                timestamp=now,
                authorization_id=auth_id,
            )
            self.adapter.add_transaction(tx_record)

            body = {
                "authorization_id": auth_id,
                "card_id": req.card_id,
                "amount": req.amount,
                "merchant": req.merchant,
                "status": "APPROVED",
                "expires_at": self._format_iso(expires_at),
                "created_at": self._format_iso(now),
            }
            self._save_idempotency(req.idempotency_key, req.card_id, request_hash, 201, body, now)
            return 201, body, False

    def create_clearing(
        self, req: ClearingRequestEntity, request_hash: str
    ) -> Tuple[int, Dict[str, Any], bool]:
        """Settle transaction. Supports multi-clearing, over-capture, and force-posts."""
        # 1. Check idempotency
        record = self.adapter.get_idempotency_record(req.idempotency_key)
        if record:
            if record.request_hash == request_hash:
                return record.status_code, record.response_body, True
            return 409, {"error": "Conflict", "message": "Idempotency key reused with different request payload"}, False

        # 2. Seed validations
        card = self.adapter.get_card(req.card_id)
        if not card:
            return 404, {"error": "Not Found", "message": f"Card '{req.card_id}' not found"}, False

        if not self.adapter.is_valid_merchant(req.merchant):
            return 400, {"error": "Validation error", "message": f"Merchant '{req.merchant}' is not recognized"}, False

        # 3. Check authorization existence if referenced
        auth = None
        if req.authorization_id:
            auth = self.adapter.get_authorization(req.authorization_id)
            if not auth:
                return 404, {"error": "Not Found", "message": f"Authorization '{req.authorization_id}' not found"}, False
            if auth.card_id != req.card_id:
                return 400, {"error": "Validation error", "message": "Authorization does not belong to this card"}, False

        # 4. Acquire locks in canonical hierarchy: Card Lock -> Auth Lock
        card_lock = self.adapter.get_card_lock(req.card_id)
        with card_lock:
            if auth:
                auth_lock = self.adapter.get_auth_lock(auth.authorization_id)
                with auth_lock:
                    return self._execute_clearing(card, req, auth, request_hash)
            else:
                # Force-post (no prior auth)
                return self._execute_clearing(card, req, None, request_hash)

    def _execute_clearing(
        self,
        card: Any,
        req: ClearingRequestEntity,
        auth: Optional[AuthorizationRecordEntity],
        request_hash: str,
    ) -> Tuple[int, Dict[str, Any], bool]:
        # Re-check idempotency under lock
        record = self.adapter.get_idempotency_record(req.idempotency_key)
        if record:
            if record.request_hash == request_hash:
                return record.status_code, record.response_body, True
            return 409, {"error": "Conflict", "message": "Idempotency key reused with different request payload"}, False

        now = time.time()
        clearing_id = f"clr_{uuid.uuid4().hex[:8]}"
        is_force_post = auth is None

        if is_force_post:
            # Force-post increases settled balance directly; allowed to push available limit negative
            card.settled_balance += req.amount
            tx_type = "FORCE_POST"
            auth_id_ref = None
        else:
            # Multi-clearing / Over-capture logic
            tx_type = "CLEARING"
            auth_id_ref = auth.authorization_id

            if now >= auth.expires_at or auth.status == "EXPIRED":
                # Expired hold: hold is 0, settle full amount
                auth.status = "EXPIRED"
                auth.remaining_held_amount = 0.0
            else:
                # Active hold: consume up to remaining held amount
                held_to_release = min(auth.remaining_held_amount, req.amount)
                auth.remaining_held_amount -= held_to_release
                if auth.remaining_held_amount <= 0.0:
                    auth.remaining_held_amount = 0.0
                    auth.status = "CLEARED"

            card.settled_balance += req.amount

        # Record clearing & ledger entry
        clearing_record = ClearingRecordEntity(
            clearing_id=clearing_id,
            card_id=req.card_id,
            amount=req.amount,
            merchant=req.merchant,
            is_force_post=is_force_post,
            created_at=now,
            authorization_id=auth_id_ref,
        )
        self.adapter.save_clearing(clearing_record)

        tx_record = LedgerTransactionRecordEntity(
            transaction_id=clearing_id,
            card_id=req.card_id,
            type=tx_type,
            amount=req.amount,
            merchant=req.merchant,
            status="SETTLED",
            timestamp=now,
            authorization_id=auth_id_ref,
        )
        self.adapter.add_transaction(tx_record)

        body = {
            "clearing_id": clearing_id,
            "card_id": req.card_id,
            "amount": req.amount,
            "merchant": req.merchant,
            "authorization_id": auth_id_ref,
            "is_force_post": is_force_post,
            "status": "SETTLED",
            "created_at": self._format_iso(now),
        }
        self._save_idempotency(req.idempotency_key, req.card_id, request_hash, 201, body, now)
        return 201, body, False

    def reverse_authorization(
        self, req: ReversalRequestEntity, request_hash: str
    ) -> Tuple[int, Dict[str, Any], bool]:
        """Cancel active remaining held amount on an authorization early."""
        # 1. Check idempotency
        record = self.adapter.get_idempotency_record(req.idempotency_key)
        if record:
            if record.request_hash == request_hash:
                return record.status_code, record.response_body, True
            return 409, {"error": "Conflict", "message": "Idempotency key reused with different request payload"}, False

        # 2. Check card & authorization
        card = self.adapter.get_card(req.card_id)
        if not card:
            return 404, {"error": "Not Found", "message": f"Card '{req.card_id}' not found"}, False

        auth = self.adapter.get_authorization(req.authorization_id)
        if not auth:
            return 404, {"error": "Not Found", "message": f"Authorization '{req.authorization_id}' not found"}, False
        if auth.card_id != req.card_id:
            return 400, {"error": "Validation error", "message": "Authorization does not belong to this card"}, False

        # 3. Acquire locks in canonical hierarchy: Card Lock -> Auth Lock
        card_lock = self.adapter.get_card_lock(req.card_id)
        auth_lock = self.adapter.get_auth_lock(req.authorization_id)

        with card_lock:
            with auth_lock:
                # Re-check idempotency under lock
                record = self.adapter.get_idempotency_record(req.idempotency_key)
                if record:
                    if record.request_hash == request_hash:
                        return record.status_code, record.response_body, True
                    return 409, {"error": "Conflict", "message": "Idempotency key reused with different request payload"}, False

                now = time.time()
                if now >= auth.expires_at or auth.status == "EXPIRED":
                    auth.status = "EXPIRED"
                    auth.remaining_held_amount = 0.0
                    return 422, {"error": "Unprocessable Entity", "message": "Authorization hold has expired"}, False

                if auth.remaining_held_amount <= 0.0 or auth.status in ("CLEARED", "REVERSED"):
                    return 422, {"error": "Unprocessable Entity", "message": "Authorization has no active held balance to reverse"}, False

                # Determine amount to reverse
                if req.amount is None:
                    amount_to_reverse = auth.remaining_held_amount
                else:
                    if req.amount > auth.remaining_held_amount:
                        return 422, {
                            "error": "Unprocessable Entity",
                            "message": f"Requested reversal amount ({req.amount}) exceeds active held amount ({auth.remaining_held_amount})",
                        }, False
                    amount_to_reverse = req.amount

                # Deduct from remaining hold
                auth.remaining_held_amount -= amount_to_reverse
                if auth.remaining_held_amount <= 0.0:
                    auth.remaining_held_amount = 0.0
                    auth.status = "REVERSED"

                reversal_id = f"rev_{uuid.uuid4().hex[:8]}"
                reversal_record = ReversalRecordEntity(
                    reversal_id=reversal_id,
                    authorization_id=auth.authorization_id,
                    card_id=req.card_id,
                    amount=amount_to_reverse,
                    created_at=now,
                )
                self.adapter.save_reversal(reversal_record)

                tx_record = LedgerTransactionRecordEntity(
                    transaction_id=reversal_id,
                    card_id=req.card_id,
                    type="REVERSAL",
                    amount=amount_to_reverse,
                    merchant=auth.merchant,
                    status="REVERSED",
                    timestamp=now,
                    authorization_id=auth.authorization_id,
                )
                self.adapter.add_transaction(tx_record)

                body = {
                    "reversal_id": reversal_id,
                    "authorization_id": auth.authorization_id,
                    "card_id": req.card_id,
                    "reversed_amount": amount_to_reverse,
                    "remaining_held_amount": round(auth.remaining_held_amount, 2),
                    "status": "REVERSED",
                    "created_at": self._format_iso(now),
                }
                self._save_idempotency(req.idempotency_key, req.card_id, request_hash, 200, body, now)
                return 200, body, False

    def get_card_balance(self, card_id: str) -> Tuple[int, Dict[str, Any]]:
        """Retrieve credit limit, settled balance, active held balance, and available remaining limit."""
        card = self.adapter.get_card(card_id)
        if not card:
            return 404, {"error": "Not Found", "message": f"Card '{card_id}' not found"}

        card_lock = self.adapter.get_card_lock(card_id)
        with card_lock:
            now = time.time()
            active_held = self.adapter.get_active_held_balance(card_id, now)
            available_limit = card.credit_limit - card.settled_balance - active_held

            body = {
                "card_id": card_id,
                "credit_limit": round(card.credit_limit, 2),
                "settled_balance": round(card.settled_balance, 2),
                "held_balance": round(active_held, 2),
                "available_limit": round(available_limit, 2),
            }
            return 200, body

    def get_card_transactions(self, card_id: str) -> Tuple[int, Dict[str, Any]]:
        """Retrieve full card transaction ledger history."""
        card = self.adapter.get_card(card_id)
        if not card:
            return 404, {"error": "Not Found", "message": f"Card '{card_id}' not found"}

        card_lock = self.adapter.get_card_lock(card_id)
        with card_lock:
            transactions = self.adapter.get_card_transactions(card_id)
            body = {
                "card_id": card_id,
                "transactions": [
                    {
                        "transaction_id": t.transaction_id,
                        "card_id": t.card_id,
                        "type": t.type,
                        "amount": round(t.amount, 2),
                        "merchant": t.merchant,
                        "status": t.status,
                        "timestamp": self._format_iso(t.timestamp),
                        "authorization_id": t.authorization_id,
                    }
                    for t in transactions
                ],
            }
            return 200, body


payment_manager = PaymentManager()
