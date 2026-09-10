from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from infra.redis_client import get_redis, make_key

def _ttl() -> int:
    try:
        return int(os.getenv("DELIVERY_LAST_POINT_TTL_SECONDS", "120"))
    except Exception:
        return 120


async def set_last_location(order_id: str, payload: Dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
    """
    Enregistre la dernière position pour une commande.
    payload doit être JSON-sérialisable et contenir au minimum latitude/longitude/captured_at.
    """
    r = get_redis()
    key = make_key("delivery", "last", order_id)
    await r.setex(key, int(ttl_seconds or _ttl()), json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


async def get_last_location(order_id: str) -> Optional[Dict[str, Any]]:
    """
    Récupère la dernière position connue pour une commande, ou None si expirée/absente.
    """
    r = get_redis()
    key = make_key("delivery", "last", order_id)
    raw = await r.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def publish_location_update(shop_id: Optional[str], order_id: str, payload: Dict[str, Any]) -> int:
    """
    Publie un message temps réel sur des canaux Redis pour diffusion multi-workers.
    Retourne le nombre total de récepteurs.
    """
    r = get_redis()
    receivers = 0
    # Canal commande
    receivers += await r.publish(make_key("pubsub", "order", order_id), json.dumps(payload, ensure_ascii=False))
    # Canal boutique (si fourni)
    if shop_id:
        receivers += await r.publish(make_key("pubsub", "shop", shop_id, "deliveries"), json.dumps(payload, ensure_ascii=False))
    return receivers
