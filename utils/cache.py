from __future__ import annotations

import asyncio
import hashlib
import json
import os
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, TypeVar, cast

from infra.redis_client import get_redis, make_key

T = TypeVar("T")


def _default_ttl() -> int:
    try:
        return int(os.getenv("CACHE_DEFAULT_TTL_SECONDS", "120"))
    except Exception:
        return 120


async def cache_get_json(key: str) -> Optional[Any]:
    r = get_redis()
    data = await r.get(key)
    if data is None:
        return None
    try:
        return json.loads(data)
    except Exception:
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    r = get_redis()
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    ttl = int(ttl_seconds or _default_ttl())
    await r.setex(key, ttl, payload)


def make_hashed_key(namespace: str, **params: Any) -> str:
    """
    Construit une clé stable à partir d'un namespace et d'un dict de paramètres.
    """
    items = sorted((k, str(v)) for k, v in params.items())
    raw = "&".join(f"{k}={v}" for k, v in items)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()  # court et suffisant pour un cache
    return make_key(namespace, h)


def cached(ttl_seconds: Optional[int] = None, namespace: str = "api") -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Décorateur pour cacher le résultat JSON-sérialisable d'une coroutine.
    La clé est basée sur le namespace et les arguments nommés.
    Usage:
        @cached(ttl_seconds=60, namespace="perf:dashboard")
        async def handler(org_id: str, period: str, limit: int = 10): ...
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            key = make_hashed_key(namespace, **kwargs)
            cached_val = await cache_get_json(key)
            if cached_val is not None:
                return cast(T, cached_val)
            result = await func(*args, **kwargs)
            try:
                await cache_set_json(key, result, ttl_seconds)
            except Exception:
                # Ne pas interrompre la requête si Redis échoue
                pass
            return result
        return wrapper
    return decorator
