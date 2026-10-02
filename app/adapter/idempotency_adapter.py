"""Adapter managing in-memory persistence of idempotency keys and cached responses."""

from datetime import datetime, timezone
import threading
from typing import Any, Dict, Optional, Tuple

from app.adapter.entities import IdempotencyRecordEntity


class IdempotencyAdapter:
    """Thread-safe in-memory storage adapter for idempotency records."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Clear all stored idempotency records."""
        with self._lock:
            self._records: Dict[str, IdempotencyRecordEntity] = {}

    def reserve(
        self, key: str, user_id: str, endpoint: str, request_hash: str
    ) -> Tuple[bool, Optional[IdempotencyRecordEntity]]:
        """Atomically reserve an idempotency key with IN_PROGRESS status.

        Returns (True, new_record) if reserved, or (False, existing_record) if key already exists.
        """
        with self._lock:
            if key in self._records:
                return False, self._records[key]

            now_ts = datetime.now(timezone.utc).isoformat()
            record = IdempotencyRecordEntity(
                key=key,
                user_id=user_id,
                endpoint=endpoint,
                request_hash=request_hash,
                status="IN_PROGRESS",
                created_at=now_ts,
                updated_at=now_ts,
            )
            self._records[key] = record
            return True, record

    def get(self, key: str) -> Optional[IdempotencyRecordEntity]:
        """Retrieve an idempotency record by key."""
        with self._lock:
            return self._records.get(key)

    def complete(self, key: str, status_code: int, response_body: Dict[str, Any]) -> None:
        """Mark idempotency record as COMPLETED and cache the serialized response."""
        with self._lock:
            if key in self._records:
                rec = self._records[key]
                rec.status = "COMPLETED"
                rec.status_code = status_code
                rec.response_body = response_body
                rec.updated_at = datetime.now(timezone.utc).isoformat()

    def release(self, key: str) -> None:
        """Release or remove an in-progress idempotency reservation on error."""
        with self._lock:
            self._records.pop(key, None)


# Default singleton instance
idempotency_adapter = IdempotencyAdapter()
