"""Fine-grained account locking manager with deadlock-free canonical ordering."""

from contextlib import contextmanager
import threading
from typing import Dict, Iterable, List


class AccountLockManager:
    """Thread-safe fine-grained lock manager.
    
    Locks are assigned per account_id and acquired in deterministic canonical
    (lexicographical) order. This guarantees zero deadlocks across concurrent threads.
    """

    def __init__(self):
        self._locks: Dict[str, threading.RLock] = {}
        self._registry_lock = threading.Lock()

    def get_lock(self, account_id: str) -> threading.RLock:
        """Get or create an RLock for the given account_id."""
        with self._registry_lock:
            if account_id not in self._locks:
                self._locks[account_id] = threading.RLock()
            return self._locks[account_id]

    @contextmanager
    def acquire_account_locks(self, account_ids: Iterable[str]):
        """Acquire locks on all specified account IDs in strict lexicographical order.
        
        Only the accounts participating in the operation are locked.
        Releases locks in reverse order when the context block exits.
        """
        unique_sorted_ids: List[str] = sorted(list(set(account_ids)))
        acquired_locks: List[threading.RLock] = []
        try:
            for acc_id in unique_sorted_ids:
                lock = self.get_lock(acc_id)
                lock.acquire()
                acquired_locks.append(lock)
            yield
        finally:
            for lock in reversed(acquired_locks):
                lock.release()


# Global singleton instance
lock_manager = AccountLockManager()
