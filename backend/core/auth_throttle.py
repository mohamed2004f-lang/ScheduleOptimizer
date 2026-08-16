"""
عداد محاولات الدخول وقفل الحساب — Redis إن وُجد، وإلا ذاكرة العملية.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_PREFIX = "so:auth:"
_memory_store: Optional["MemoryAuthStore"] = None
_redis_store: Optional["RedisAuthStore"] = None
_redis_failed = False


def redis_url() -> str:
    return (os.environ.get("CACHE_REDIS_URL") or os.environ.get("REDIS_URL") or "").strip()


def lockout_max_failures() -> int:
    try:
        n = int(os.environ.get("LOGIN_LOCKOUT_MAX", "5"))
    except ValueError:
        n = 5
    return max(3, min(n, 50))


def lockout_seconds() -> int:
    try:
        n = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900"))
    except ValueError:
        n = 900
    return max(60, min(n, 86400))


def lockout_enabled() -> bool:
    v = (os.environ.get("LOGIN_LOCKOUT_ENABLED") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    try:
        from flask import current_app, has_app_context

        if has_app_context() and current_app.config.get("TESTING"):
            return False
    except Exception:
        pass
    return True


def _norm_user(username: str) -> str:
    return (username or "").strip().casefold()


class MemoryAuthStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._data.items() if exp <= now]
        for k in expired:
            self._data.pop(k, None)

    def incr(self, key: str, ttl: int) -> int:
        now = time.time()
        with self._lock:
            self._purge(now)
            val, exp = self._data.get(key, ("0", 0.0))
            if exp <= now:
                self._data[key] = ("1", now + ttl)
                return 1
            n = int(val or "0") + 1
            self._data[key] = (str(n), exp)
            return n

    def get(self, key: str) -> Optional[str]:
        now = time.time()
        with self._lock:
            val, exp = self._data.get(key, (None, 0.0))
            if val is None or exp <= now:
                self._data.pop(key, None)
                return None
            return val

    def set(self, key: str, value: str, ttl: int) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def ttl(self, key: str) -> int:
        now = time.time()
        with self._lock:
            _, exp = self._data.get(key, (None, 0.0))
            if exp <= now:
                self._data.pop(key, None)
                return 0
            return max(0, int(exp - now))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class RedisAuthStore:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._client.ping()

    def incr(self, key: str, ttl: int) -> int:
        n = int(self._client.incr(key))
        if n == 1:
            self._client.expire(key, ttl)
        return n

    def get(self, key: str) -> Optional[str]:
        val = self._client.get(key)
        return str(val) if val is not None else None

    def set(self, key: str, value: str, ttl: int) -> None:
        self._client.setex(key, ttl, value)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def ttl(self, key: str) -> int:
        n = int(self._client.ttl(key) or 0)
        return n if n > 0 else 0


def _memory() -> MemoryAuthStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryAuthStore()
    return _memory_store


def _store():
    global _redis_store, _redis_failed
    url = redis_url()
    if url and not _redis_failed:
        if _redis_store is None:
            try:
                _redis_store = RedisAuthStore(url)
                logger.info("Auth throttle using Redis")
            except Exception:
                _redis_failed = True
                logger.warning("Redis unavailable for auth throttle; using in-memory store", exc_info=True)
                return _memory()
        return _redis_store
    return _memory()


def reset_throttle_state() -> None:
    """إعادة ضبط مخزن الذاكرة (للاختبارات). لا يمسح Redis."""
    global _redis_store, _redis_failed
    _memory().clear()
    _redis_store = None
    _redis_failed = False


def increment_window(key: str, window_seconds: int) -> int:
    """عداد نافذة زمنية (مثلاً محاولات IP)."""
    return _store().incr(f"{_PREFIX}win:{key}", int(window_seconds))


def is_locked(username: str) -> Tuple[bool, int]:
    ident = _norm_user(username)
    if not ident:
        return False, 0
    store = _store()
    lock_key = f"{_PREFIX}lock:{ident}"
    if store.get(lock_key):
        return True, store.ttl(lock_key) or lockout_seconds()
    return False, 0


def record_login_failure(username: str) -> Tuple[bool, int]:
    """
    يزيد عداد الفشل. عند بلوغ الحد يُقفل الاسم.
    يعيد (now_locked, retry_after_seconds).
    """
    ident = _norm_user(username)
    if not ident:
        return False, 0
    store = _store()
    fail_key = f"{_PREFIX}fail:{ident}"
    lock_key = f"{_PREFIX}lock:{ident}"
    window = lockout_seconds()
    n = store.incr(fail_key, window)
    if n >= lockout_max_failures():
        store.set(lock_key, "1", window)
        logger.warning("Login lockout engaged user_key=%s failures=%s", ident, n)
        return True, store.ttl(lock_key) or window
    return False, 0


def record_login_success(username: str) -> None:
    ident = _norm_user(username)
    if not ident:
        return
    store = _store()
    store.delete(f"{_PREFIX}fail:{ident}")
    store.delete(f"{_PREFIX}lock:{ident}")
