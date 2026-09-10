from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket


def utc_now_ts() -> float:
    return time.time()


def iso_utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ConnectionInfo:
    websocket: WebSocket
    role: str  # "customer" | "member"
    subject: str  # fingerprinted user/member id surrogate
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rooms: Set[str] = field(default_factory=set)
    created_at_ts: float = field(default_factory=utc_now_ts)
    last_heartbeat_ts: float = field(default_factory=utc_now_ts)
    next_seq: int = 1


class DeliveryConnectionManager:
    """
    Gestionnaire mono-instance (en mémoire) pour les connexions et rooms WebSocket.
    Non adapté au multi-workers sans broker/pub-sub.
    """

    def __init__(self) -> None:
        self._connections: Dict[WebSocket, ConnectionInfo] = {}
        self._rooms: Dict[str, Set[WebSocket]] = {}
        # Etats live par commande
        self._order_last_location: Dict[str, Dict[str, Any]] = {}
        self._order_last_persist_ts: Dict[str, float] = {}
        # Verrou de diffusion
        self._lock = asyncio.Lock()

    async def accept(self, websocket: WebSocket, role: str, subject: str) -> ConnectionInfo:
        await websocket.accept()
        info = ConnectionInfo(websocket=websocket, role=role, subject=subject)
        self._connections[websocket] = info
        return info

    def get_info(self, websocket: WebSocket) -> Optional[ConnectionInfo]:
        return self._connections.get(websocket)

    async def close(self, websocket: WebSocket, code: int = 1000) -> None:
        try:
            await websocket.close(code=code)
        finally:
            self.disconnect(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        info = self._connections.pop(websocket, None)
        if not info:
            return
        for room in list(info.rooms):
            self.leave_room(websocket, room)

    def join_room(self, websocket: WebSocket, room: str) -> None:
        info = self._connections.get(websocket)
        if not info:
            return
        info.rooms.add(room)
        self._rooms.setdefault(room, set()).add(websocket)

    def leave_room(self, websocket: WebSocket, room: str) -> None:
        if room in self._rooms:
            self._rooms[room].discard(websocket)
            if not self._rooms[room]:
                self._rooms.pop(room, None)
        info = self._connections.get(websocket)
        if info:
            info.rooms.discard(room)

    async def broadcast_room(self, room: str, message: Dict[str, Any]) -> None:
        # Envoi en parallèle, erreurs isolées
        sockets = list(self._rooms.get(room, set()))
        if not sockets:
            return
        data = json.dumps(message)
        async with self._lock:
            coros = []
            for ws in sockets:
                try:
                    coros.append(ws.send_text(data))
                except RuntimeError:
                    # socket peut être déjà fermé
                    self.disconnect(ws)
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)

    def next_seq(self, websocket: WebSocket) -> int:
        info = self._connections.get(websocket)
        if not info:
            return 1
        seq = info.next_seq
        info.next_seq += 1
        return seq

    def update_last_location(self, order_id: str, location: Dict[str, Any]) -> None:
        self._order_last_location[order_id] = location

    def get_last_location(self, order_id: str) -> Optional[Dict[str, Any]]:
        return self._order_last_location.get(order_id)

    def set_last_persist_ts(self, order_id: str, ts: float) -> None:
        self._order_last_persist_ts[order_id] = ts

    def get_last_persist_ts(self, order_id: str) -> Optional[float]:
        return self._order_last_persist_ts.get(order_id)

    def build_snapshot(
        self,
        order_id: str,
        organization_id: Optional[str],
        shop_id: Optional[str],
        status: str = "in_delivery",
        delivery_member_id: Optional[str] = None,
        eta_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Construit un snapshot à partir de l'état mémoire minimal. En absence d'intégration DB,
        on retourne le dernier point connu + métadonnées du scope.
        """
        last_loc = self.get_last_location(order_id)
        return {
            "order_id": order_id,
            "organization_id": organization_id,
            "shop_id": shop_id,
            "status": status,
            "delivery_member_id": delivery_member_id,
            "last_location": last_loc,
            "eta_minutes": eta_minutes,
        }


# Singleton process-local pour le MVP mono-instance
delivery_ws_manager = DeliveryConnectionManager()
