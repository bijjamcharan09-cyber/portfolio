"""Lightweight, thread-safe, user-isolated TTL cache for derived non-sensitive data.

Used for:
- Short-TTL dashboard summary aggregates (invalidated immediately on transaction writes)
- Short-TTL active user lookup (invalidated immediately on user profile/status changes)

Never caches authentication credentials, tokens, or cross-user data.
"""
import threading
import time
from typing import Any, Optional


class TTLCache:
    """Thread-safe bounded in-memory TTL cache."""

    def __init__(self, max_entries: int = 512):
        self._lock = threading.RLock()
        self._store: dict[str, tuple[float, Any]] = {}
        self._max_entries = max_entries

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float):
        if ttl_seconds <= 0:
            return
        expires_at = time.monotonic() + ttl_seconds
        with self._lock:
            if len(self._store) >= self._max_entries and key not in self._store:
                # Evict oldest/expired entries first
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._store.items() if now >= exp]
                for k in expired:
                    del self._store[k]
                if len(self._store) >= self._max_entries:
                    oldest_key = next(iter(self._store))
                    del self._store[oldest_key]
            self._store[key] = (expires_at, value)

    def delete_prefix(self, prefix: str):
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()


_summary_cache = TTLCache(max_entries=512)
_user_cache = TTLCache(max_entries=256)

SUMMARY_TTL_SECONDS = 30.0
USER_TTL_SECONDS = 15.0


def get_cached_summary(user_id: Optional[int], start_iso: str, end_iso: str) -> Optional[dict]:
    if user_id is None:
        return None
    return _summary_cache.get(f"summary:{user_id}:{start_iso}:{end_iso}")


def set_cached_summary(user_id: Optional[int], start_iso: str, end_iso: str, data: dict):
    if user_id is None:
        return
    _summary_cache.set(f"summary:{user_id}:{start_iso}:{end_iso}", data, SUMMARY_TTL_SECONDS)


def invalidate_user_summary(user_id: Optional[int]):
    if user_id is None:
        _summary_cache.clear()
    else:
        _summary_cache.delete_prefix(f"summary:{user_id}:")


def get_cached_user(user_id: int) -> Optional[dict]:
    return _user_cache.get(f"user:{user_id}")


def set_cached_user(user_id: int, user_dict: dict):
    _user_cache.set(f"user:{user_id}", user_dict, USER_TTL_SECONDS)


def invalidate_user(user_id: int):
    _user_cache.delete(f"user:{user_id}")


def clear_all_caches():
    _summary_cache.clear()
    _user_cache.clear()
