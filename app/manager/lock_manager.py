"""Lock manager coordinating fine-grained, deadlock-free resource synchronization."""

from contextlib import contextmanager
import threading
from typing import Dict, Generator, List


class LockManager:
    """Fine-grained resource lock striping and deadlock-free ordered lock coordinator."""

    def __init__(self) -> None:
        self._meta_lock = threading.Lock()
        self._locks: Dict[str, threading.RLock] = {}

    def get_lock(self, resource_id: str) -> threading.RLock:
        """Get or create a re-entrant lock for a specific resource ID."""
        with self._meta_lock:
            if resource_id not in self._locks:
                self._locks[resource_id] = threading.RLock()
            return self._locks[resource_id]

    @contextmanager
    def acquire_ordered_locks(self, *resource_ids: str) -> Generator[None, None, None]:
        """Acquire locks for multiple resources in strict lexicographical order to eliminate deadlocks.

        Locks are acquired sequentially in ascending order and released in reverse order.
        """
        # Deduplicate and sort IDs lexicographically to guarantee cycle-free acquisition
        valid_ids: List[str] = sorted(dict.fromkeys([rid for rid in resource_ids if rid]))
        locks = [self.get_lock(rid) for rid in valid_ids]
        acquired: List[threading.RLock] = []

        try:
            for lock in locks:
                lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    def reset(self) -> None:
        """Clear all created resource locks."""
        with self._meta_lock:
            self._locks.clear()


# Default singleton instance
lock_manager = LockManager()
