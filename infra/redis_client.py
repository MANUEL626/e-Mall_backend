from __future__ import annotations

import os
import asyncio
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

# Instance Redis partagée (event loop locale au worker)
_redis: Optional[Redis] = None


def _redis_url() -> str:
    # Par défaut, privilégie le service Docker "redis" (docker-compose).
    # En local hors Docker, définir explicitement REDIS_URL=redis://localhost:6379/0.
    return os.getenv("REDIS_URL", "redis://redis:6379/0")


def redis_prefix() -> str:
    return os.getenv("REDIS_PREFIX", "emall")


def make_key(*parts: str) -> str:
    # Clés normalisées: {prefix}:part1:part2:...
    prefix = redis_prefix()
    cleaned = [p.strip().replace(" ", "_") for p in parts if p is not None]
    return ":".join([prefix, *cleaned])


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis n'est pas initialisé. Appeler init_redis() au démarrage de l'application.")
    return _redis


async def init_redis(app=None) -> Redis:
    """
    Initialise un client Redis asynchrone et le stocke en global.
    Si 'app' est fourni (FastAPI), attache aussi app.state.redis.
    """
    global _redis
    if _redis is not None:
        return _redis

    client: Redis = Redis.from_url(
        _redis_url(),
        encoding="utf-8",
        decode_responses=True,  # renvoie des str, pratique pour JSON
        health_check_interval=30,
    )
    # Ping avec retries pour laisser Redis démarrer dans les environnements orchestrés
    last_exc: Exception | None = None
    for attempt in range(1, 11):  # ~jusqu'à ~10 tentatives
        try:
            await client.ping()
            last_exc = None
            break
        except (RedisConnectionError, OSError) as e:
            last_exc = e
            await asyncio.sleep(min(0.5 * attempt, 2.0))
    if last_exc is not None:
        # Si toujours en échec après retries, on propage l'erreur
        raise last_exc

    _redis = client
    if app is not None:
        setattr(app.state, "redis", _redis)
    return _redis


async def close_redis(app=None) -> None:
    """Ferme proprement la connexion Redis."""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
    if app is not None and hasattr(app.state, "redis"):
        try:
            delattr(app.state, "redis")
        except Exception:
            pass
