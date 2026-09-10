from __future__ import annotations

import hashlib
import math
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import jwt


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


DELIVERY_WS_TICKET_SECRET = os.getenv("DELIVERY_WS_TICKET_SECRET", "dev-delivery-ws-secret")
DELIVERY_WS_TICKET_TTL_SECONDS = env_int("DELIVERY_WS_TICKET_TTL_SECONDS", 60)
DELIVERY_WS_HEARTBEAT_SECONDS = env_int("DELIVERY_WS_HEARTBEAT_SECONDS", 25)
DELIVERY_WS_LOCATION_MIN_INTERVAL_SECONDS = env_int("DELIVERY_WS_LOCATION_MIN_INTERVAL_SECONDS", 2)
DELIVERY_WS_LOCATION_PERSIST_INTERVAL_SECONDS = env_int(
    "DELIVERY_WS_LOCATION_PERSIST_INTERVAL_SECONDS", 15
)
DELIVERY_WS_LOCATION_MIN_DISTANCE_METERS = env_int("DELIVERY_WS_LOCATION_MIN_DISTANCE_METERS", 50)


def fingerprint_subject(access_token: str) -> str:
    """
    Empreinte stable (non réversible) du token d'auth pour lier un ticket à un "subject".
    Évite d'exposer l'identité réelle tant que l'intégration Supabase n'est pas branchée ici.
    """
    h = hashlib.sha256()
    h.update(access_token.encode("utf-8"))
    return h.hexdigest()


def issue_ticket(
    role: str,
    channel: str,
    subject: str,
    scope: Dict[str, Any],
    ttl_seconds: Optional[int] = None,
) -> Tuple[str, int]:
    ttl = ttl_seconds or DELIVERY_WS_TICKET_TTL_SECONDS
    now = int(time.time())
    exp = now + ttl
    payload = {
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": exp,
        "role": role,
        "channel": channel,  # "order" | "assignments" | "shop"
        "sub": subject,
        "scope": scope,
    }
    token = jwt.encode(payload, DELIVERY_WS_TICKET_SECRET, algorithm="HS256")
    return token, ttl


def verify_ticket(token: str) -> Dict[str, Any]:
    return jwt.decode(token, DELIVERY_WS_TICKET_SECRET, algorithms=["HS256"])


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def should_persist_location(
    last_persist_ts: Optional[float],
    last_location: Optional[Dict[str, Any]],
    new_location: Dict[str, Any],
) -> bool:
    """
    Politique MVP:
    - intervalle temps minimal
    - OU distance minimale depuis le dernier point persisté
    """
    now_ts = time.time()
    if last_persist_ts is None:
        return True
    if now_ts - last_persist_ts >= DELIVERY_WS_LOCATION_PERSIST_INTERVAL_SECONDS:
        return True
    if last_location:
        try:
            dist = haversine_meters(
                float(last_location.get("latitude")),
                float(last_location.get("longitude")),
                float(new_location.get("latitude")),
                float(new_location.get("longitude")),
            )
            if dist >= DELIVERY_WS_LOCATION_MIN_DISTANCE_METERS:
                return True
        except Exception:
            # Si calcul impossible, tomber sur l'intervalle temps
            pass
    return False


async def persist_location_point(_point: Dict[str, Any]) -> None:
    """
    Stub de persistance. À raccorder à Supabase/Postgres.
    Intention: insérer une ligne dans une table de tracking (order_id, member_id, lat, lng, captured_at, created_at).
    """
    # No-op MVP (on conserve l'API async pour faciliter l'intégration future).
    return
