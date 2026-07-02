"""
Flask-Caching — تخزين مؤقت لقوائم القراءة الثقيلة.
"""
from __future__ import annotations

import hashlib
import os
from functools import wraps
from typing import Callable

from flask import request, session

cache = None


def init_app_cache(app) -> None:
    global cache
    from flask_caching import Cache

    timeout = int(os.environ.get("CACHE_TIMEOUT", "60"))
    cache_type = (os.environ.get("CACHE_TYPE") or "SimpleCache").strip()
    redis_url = (os.environ.get("CACHE_REDIS_URL") or "").strip()

    app.config.setdefault("CACHE_DEFAULT_TIMEOUT", timeout)
    if redis_url:
        app.config["CACHE_TYPE"] = "RedisCache"
        app.config["CACHE_REDIS_URL"] = redis_url
    else:
        app.config["CACHE_TYPE"] = cache_type

    cache = Cache(app)
    app.extensions["cache"] = cache


def list_cache_key(prefix: str) -> str:
    """مفتاح يعتمد على المستخدم والدور ومعاملات الاستعلام."""
    user = (session.get("user") or session.get("username") or "").strip()
    role = (session.get("user_role") or "").strip()
    qs = (request.query_string or b"").decode("utf-8", errors="replace")
    raw = f"{prefix}|{user}|{role}|{qs}"
    return f"list:{prefix}:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def cached_list(prefix: str, timeout: int | None = None):
    """مزيّن لدوال list التي تُرجع jsonify-able data."""

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if cache is None:
                return fn(*args, **kwargs)
            key = list_cache_key(prefix)
            hit = safe_cache_get(key)
            if hit is not None:
                return hit
            resp = fn(*args, **kwargs)
            safe_cache_set(key, resp, timeout=timeout)
            return resp

        return wrapper

    return decorator


def safe_cache_get(key: str):
    """قراءة آمنة من الكاش — تتجاهل أخطاء backend غير المهيّأ."""
    if cache is None:
        return None
    try:
        return cache.get(key)
    except Exception:
        return None


def safe_cache_set(key: str, value, timeout: int | None = None) -> None:
    """كتابة آمنة إلى الكاش."""
    if cache is None:
        return
    try:
        if timeout is not None:
            cache.set(key, value, timeout=timeout)
        else:
            cache.set(key, value)
    except Exception:
        pass


def invalidate_list_prefix(prefix: str) -> None:
    """أبطِل مفاتيح قائمة (أفضل جهد — SimpleCache لا يدعم delete_memoized بسهولة)."""
    if cache is None:
        return
    try:
        cache.clear()
    except Exception:
        pass
