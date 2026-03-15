"""Simple in-memory TTL cache for slow API endpoints.

Thread-safe for asyncio (single event loop, no true parallelism).
No external dependencies — plain dict + timestamps.
"""

import time
from functools import wraps
from typing import Any

# Global cache store: key -> (inserted_at, value)
_cache: dict[str, tuple[float, Any]] = {}


def cache_get(key: str, ttl_seconds: float) -> tuple[bool, Any]:
    """Return (hit, value). hit=True if entry exists and is not expired."""
    entry = _cache.get(key)
    if entry is not None:
        inserted_at, value = entry
        if time.time() - inserted_at < ttl_seconds:
            return True, value
        del _cache[key]  # evict stale entry
    return False, None


def cache_set(key: str, value: Any) -> None:
    """Store value with current timestamp."""
    _cache[key] = (time.time(), value)


def cache_clear() -> None:
    """Clear all entries. Call on app startup to avoid serving stale data."""
    _cache.clear()


def cache_size() -> int:
    """Return number of entries currently in cache (for testing/monitoring)."""
    return len(_cache)


def make_cache_key(name: str, **kwargs) -> str:
    """Build a stable cache key from endpoint name + sorted query params."""
    if not kwargs:
        return name
    parts = [f"{k}={v}" for k, v in sorted(kwargs.items())]
    return f"{name}|{'|'.join(parts)}"


def cache_result(ttl_seconds: float = 60.0):
    """Decorator for async FastAPI endpoint functions.

    Caches the return value for *ttl_seconds*. The cache key is derived from
    the function name and all keyword arguments passed by FastAPI's dependency
    injection (query params, path params, etc.).

    Uses functools.wraps so FastAPI can still inspect the original signature
    and inject query parameters correctly.

    Example::

        @router.get("/slow-endpoint")
        @cache_result(ttl_seconds=60)
        async def slow_endpoint(symbol: str = None, window: int = 3600):
            ...
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = make_cache_key(func.__name__, **kwargs)
            hit, value = cache_get(key, ttl_seconds)
            if hit:
                return value
            result = await func(*args, **kwargs)
            cache_set(key, result)
            return result

        return wrapper

    return decorator
