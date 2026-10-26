import time
import logging
from threading import Lock
from typing import Optional
from backend.app.extensions import redis_client

logger = logging.getLogger("fraud_agent.idempotency")

# In-memory fallback lock in case Redis is temporarily disconnected
_memory_locks = {}
_memory_lock_guard = Lock()

class IdempotencyService:
    """Provides distributed atomic locking and deduplication checking."""

    @staticmethod
    def acquire_lock(key: str, ttl_seconds: int = 30) -> bool:
        """
        Attempts to acquire a distributed lock for the idempotency key.
        Returns True if the lock was successfully acquired, False if key is already being processed.
        """
        lock_key = f"lock:idempotency:{key}"
        
        # 1. Primary: Redis atomic SETNX
        if redis_client:
            try:
                acquired = redis_client.set(lock_key, "locked", nx=True, ex=ttl_seconds)
                return bool(acquired)
            except Exception as e:
                logger.warning(f"Redis lock attempt failed: {e}. Falling back to in-memory lock.")

        # 2. Secondary Fallback: In-memory process lock
        with _memory_lock_guard:
            now = time.time()
            if lock_key in _memory_locks:
                expiry = _memory_locks[lock_key]
                if now < expiry:
                    return False  # Still locked
            _memory_locks[lock_key] = now + ttl_seconds
            return True

    @staticmethod
    def release_lock(key: str) -> None:
        """Releases the lock after processing is complete or aborted."""
        lock_key = f"lock:idempotency:{key}"
        if redis_client:
            try:
                redis_client.delete(lock_key)
            except Exception as e:
                logger.warning(f"Redis release lock failed: {e}")

        with _memory_lock_guard:
            _memory_locks.pop(lock_key, None)
