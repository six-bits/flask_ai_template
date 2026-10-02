"""Idempotency manager coordinating request hashing, conflict detection, and response caching."""

import hashlib
from typing import Any, Dict, Optional, Tuple

from app.adapter.idempotency_adapter import IdempotencyAdapter, idempotency_adapter
from app.manager.errors import (
    ConcurrentRequestConflictError,
    IdempotencyPayloadMismatchError,
)


class IdempotencyManager:
    """Manager coordinating idempotency key reservations, payload verification, and response caching."""

    def __init__(self, adpt: Optional[IdempotencyAdapter] = None) -> None:
        self.adapter = adpt or idempotency_adapter

    def compute_hash(self, endpoint: str, user_id: str, payload_json: str) -> str:
        """Compute a deterministic SHA-256 hash for an endpoint, user, and payload body."""
        raw = f"{endpoint}:{user_id}:{payload_json}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def check_or_reserve(
        self, key: str, user_id: str, endpoint: str, request_hash: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], int]:
        """Atomically check or reserve an idempotency key.

        Returns:
            (is_replayed, cached_response_body, status_code)
        Raises:
            ConcurrentRequestConflictError: If a concurrent request with the same key is in-flight.
            IdempotencyPayloadMismatchError: If the key was previously used with a different payload.
        """
        reserved, existing_record = self.adapter.reserve(
            key=key, user_id=user_id, endpoint=endpoint, request_hash=request_hash
        )

        if reserved:
            return False, None, 200

        # Key already exists
        assert existing_record is not None
        if existing_record.status == "IN_PROGRESS":
            raise ConcurrentRequestConflictError(key)

        if existing_record.status == "COMPLETED":
            if existing_record.request_hash != request_hash:
                raise IdempotencyPayloadMismatchError(key)
            return True, existing_record.response_body, existing_record.status_code

        # If previous was FAILED, release and re-reserve
        self.adapter.release(key)
        self.adapter.reserve(key, user_id, endpoint, request_hash)
        return False, None, 200

    def complete(self, key: str, status_code: int, response_body: Dict[str, Any]) -> None:
        """Mark an idempotency key as COMPLETED with its cached response."""
        self.adapter.complete(key=key, status_code=status_code, response_body=response_body)

    def release(self, key: str) -> None:
        """Release an in-progress idempotency reservation on failure."""
        self.adapter.release(key)


# Default singleton instance
idempotency_manager = IdempotencyManager()
