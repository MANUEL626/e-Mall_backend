from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from .delivery_connection_manager import delivery_ws_manager
from .delivery_realtime_models import (
    DeliveryLocationUpdatePayload,
    DeliverySnapshotPayload,
    TicketResponse,
    make_server_event,
)
from .delivery_realtime_service import (
    DELIVERY_WS_HEARTBEAT_SECONDS,
    DELIVERY_WS_LOCATION_MIN_INTERVAL_SECONDS,
    fingerprint_subject,
    issue_ticket,
    should_persist_location,
    verify_ticket,
    persist_location_point,
)

router = APIRouter(prefix="/api/v1", tags=["Delivery realtime"])


def require_bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return auth.split(" ", 1)[1].strip()


@router.post("/customer-sales/{order_id}/delivery/ws-ticket", response_model=TicketResponse)
def ticket_customer_order_ws(order_id: str, access_token: str = Depends(require_bearer_token)) -> TicketResponse:
    # TODO: vérifier que le customer est bien propriétaire de la commande
    subject = fingerprint_subject(access_token)
    token, ttl = issue_ticket(
        role="customer",
        channel="order",
        subject=subject,
        scope={"order_id": order_id},
    )
    return TicketResponse(ticket=token, expires_in=ttl)


@router.post("/delivery/assignments/ws-ticket", response_model=TicketResponse)
def ticket_delivery_assignments_ws(access_token: str = Depends(require_bearer_token)) -> TicketResponse:
    # TODO: vérifier que le membre a les droits livreur
    subject = fingerprint_subject(access_token)
    token, ttl = issue_ticket(
        role="member",
        channel="assignments",
        subject=subject,
        scope={},  # Assignations personnelles
    )
    return TicketResponse(ticket=token, expires_in=ttl)


@router.post(
    "/organizations/{organization_id}/shops/{shop_id}/deliveries/ws-ticket",
    response_model=TicketResponse,
)
def ticket_shop_deliveries_ws(
    organization_id: str,
    shop_id: str,
    access_token: str = Depends(require_bearer_token),
) -> TicketResponse:
    # TODO: vérifier l'accès du membre à la boutique
    subject = fingerprint_subject(access_token)
    token, ttl = issue_ticket(
        role="member",
        channel="shop",
        subject=subject,
        scope={"organization_id": organization_id, "shop_id": shop_id},
    )
    return TicketResponse(ticket=token, expires_in=ttl)


@router.websocket("/ws/customer-sales/{order_id}/delivery")
async def ws_customer_order(websocket: WebSocket, order_id: str, ticket: str = Query(...)) -> None:
    try:
        claims = verify_ticket(ticket)
    except Exception:
        await websocket.close(code=4001)
        return
    if claims.get("channel") != "order":
        await websocket.close(code=4003)
        return
    if claims.get("scope", {}).get("order_id") != order_id:
        await websocket.close(code=4003)
        return

    role = claims.get("role") or "customer"
    subject = claims.get("sub") or "unknown"
    info = await delivery_ws_manager.accept(websocket, role=role, subject=subject)
    # Room par commande
    room = f"order:{order_id}"
    delivery_ws_manager.join_room(websocket, room)

    # connection.accepted
    seq = delivery_ws_manager.next_seq(websocket)
    await websocket.send_json(
        make_server_event(
            "connection.accepted",
            seq,
            {"connection_id": info.connection_id, "role": role, "heartbeat_interval_seconds": DELIVERY_WS_HEARTBEAT_SECONDS},
        )
    )

    # delivery.snapshot
    snap = delivery_ws_manager.build_snapshot(
        order_id=order_id,
        organization_id=claims.get("scope", {}).get("organization_id"),
        shop_id=claims.get("scope", {}).get("shop_id"),
        status="in_delivery",
        delivery_member_id=None,
        eta_minutes=None,
    )
    seq = delivery_ws_manager.next_seq(websocket)
    await websocket.send_json(
        make_server_event("delivery.snapshot", seq, DeliverySnapshotPayload(**snap).model_dump())
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                # ping texte simple
                if raw == "ping":
                    seq = delivery_ws_manager.next_seq(websocket)
                    await websocket.send_json(make_server_event("pong", seq, {}))
                continue
            mtype = msg.get("type")
            if mtype == "ping":
                seq = delivery_ws_manager.next_seq(websocket)
                await websocket.send_json(make_server_event("pong", seq, {}))
            # Le canal customer ne publie pas d'autres messages en MVP
    except WebSocketDisconnect:
        delivery_ws_manager.disconnect(websocket)
    except Exception:
        await delivery_ws_manager.close(websocket, code=1011)


@router.websocket("/ws/delivery/assignments")
async def ws_delivery_assignments(websocket: WebSocket, ticket: str = Query(...)) -> None:
    try:
        claims = verify_ticket(ticket)
    except Exception:
        await websocket.close(code=4001)
        return
    if claims.get("channel") != "assignments":
        await websocket.close(code=4003)
        return
    role = claims.get("role") or "member"
    subject = claims.get("sub") or "unknown"
    info = await delivery_ws_manager.accept(websocket, role=role, subject=subject)

    # Room personnelle du livreur
    personal_room = f"delivery_member:{subject}"
    delivery_ws_manager.join_room(websocket, personal_room)

    # connection.accepted
    seq = delivery_ws_manager.next_seq(websocket)
    await websocket.send_json(
        make_server_event(
            "connection.accepted",
            seq,
            {"connection_id": info.connection_id, "role": role, "heartbeat_interval_seconds": DELIVERY_WS_HEARTBEAT_SECONDS},
        )
    )

    # Boucle réception
    try:
        last_msg_ts: float = 0.0
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                if raw == "ping":
                    seq = delivery_ws_manager.next_seq(websocket)
                    await websocket.send_json(make_server_event("pong", seq, {}))
                continue

            mtype = msg.get("type")
            if mtype == "ping":
                seq = delivery_ws_manager.next_seq(websocket)
                await websocket.send_json(make_server_event("pong", seq, {}))
                continue
            if mtype != "delivery.location.update":
                # Ignore en MVP
                continue

            # Rate limit minimal côté réception (intervalle WS)
            now_ts = time.time()
            if now_ts - last_msg_ts < DELIVERY_WS_LOCATION_MIN_INTERVAL_SECONDS:
                # Soft drop
                continue
            last_msg_ts = now_ts

            try:
                payload = DeliveryLocationUpdatePayload(**(msg.get("payload") or {}))
            except Exception as e:
                seq = delivery_ws_manager.next_seq(websocket)
                await websocket.send_json(
                    make_server_event("error", seq, {"code": "invalid_payload", "message": str(e)})
                )
                continue

            # Met à jour l'état mémoire
            location_dict: Dict[str, Any] = {
                "order_id": payload.order_id,
                "delivery_member_id": subject,
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "accuracy_meters": payload.accuracy_meters,
                "speed_mps": payload.speed_mps,
                "heading_degrees": payload.heading_degrees,
                "captured_at": payload.captured_at,
            }
            delivery_ws_manager.update_last_location(payload.order_id, location_dict)

            # Broadcast vers rooms concernées
            evt = make_server_event(
                "delivery.location.updated",
                delivery_ws_manager.next_seq(websocket),
                location_dict,
            )
            # order room
            await delivery_ws_manager.broadcast_room(f"order:{payload.order_id}", evt)

            # shop room si fourni par le client (optionnel pour MVP)
            org_id = (msg.get("payload") or {}).get("organization_id")
            shop_id = (msg.get("payload") or {}).get("shop_id")
            if shop_id:
                await delivery_ws_manager.broadcast_room(f"shop:{shop_id}:deliveries", evt)

            # Persistance throttled (stub)
            last_persist_ts = delivery_ws_manager.get_last_persist_ts(payload.order_id)
            last_loc = delivery_ws_manager.get_last_location(payload.order_id)
            if should_persist_location(last_persist_ts, last_loc, location_dict):
                await persist_location_point(
                    {
                        **location_dict,
                        "organization_id": org_id,
                        "shop_id": shop_id,
                        "created_at": None,
                    }
                )
                delivery_ws_manager.set_last_persist_ts(payload.order_id, now_ts)
    except WebSocketDisconnect:
        delivery_ws_manager.disconnect(websocket)
    except Exception:
        await delivery_ws_manager.close(websocket, code=1011)


@router.websocket("/ws/organizations/{organization_id}/shops/{shop_id}/deliveries")
async def ws_shop_deliveries(websocket: WebSocket, organization_id: str, shop_id: str, ticket: str = Query(...)) -> None:
    try:
        claims = verify_ticket(ticket)
    except Exception:
        await websocket.close(code=4001)
        return
    if claims.get("channel") != "shop":
        await websocket.close(code=4003)
        return
    scope = claims.get("scope") or {}
    if scope.get("organization_id") != organization_id or scope.get("shop_id") != shop_id:
        await websocket.close(code=4003)
        return

    role = claims.get("role") or "member"
    subject = claims.get("sub") or "unknown"
    info = await delivery_ws_manager.accept(websocket, role=role, subject=subject)

    room = f"shop:{shop_id}:deliveries"
    delivery_ws_manager.join_room(websocket, room)

    # connection.accepted
    seq = delivery_ws_manager.next_seq(websocket)
    await websocket.send_json(
        make_server_event(
            "connection.accepted",
            seq,
            {"connection_id": info.connection_id, "role": role, "heartbeat_interval_seconds": DELIVERY_WS_HEARTBEAT_SECONDS},
        )
    )

    # En MVP, pas d'envoi initial spécifique (les dashboards tirent un HTTP + reçoivent les updates live)
    try:
        while True:
            raw = await websocket.receive_text()
            if raw == "ping":
                seq = delivery_ws_manager.next_seq(websocket)
                await websocket.send_json(make_server_event("pong", seq, {}))
            # Canal dashboard: lecture seule en MVP
    except WebSocketDisconnect:
        delivery_ws_manager.disconnect(websocket)
    except Exception:
        await delivery_ws_manager.close(websocket, code=1011)
