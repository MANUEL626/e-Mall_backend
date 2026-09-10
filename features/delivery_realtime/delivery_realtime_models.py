from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class TicketResponse(BaseModel):
    ticket: str
    expires_in: int = Field(..., ge=1, le=600)


class DeliveryLocationUpdatePayload(BaseModel):
    order_id: str
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = Field(None, ge=0)
    speed_mps: Optional[float] = Field(None, ge=0)
    heading_degrees: Optional[float] = Field(None, ge=0, le=360)
    captured_at: str  # ISO 8601

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v: float) -> float:
        if v < -90 or v > 90:
            raise ValueError("latitude invalide")
        return v

    @field_validator("longitude")
    @classmethod
    def _lng(cls, v: float) -> float:
        if v < -180 or v > 180:
            raise ValueError("longitude invalide")
        return v


class DeliverySnapshotPayload(BaseModel):
    order_id: str
    organization_id: Optional[str] = None
    shop_id: Optional[str] = None
    status: str  # "pending"|"in_progress"|"in_delivery"|"cancelled"|"completed"
    delivery_member_id: Optional[str] = None
    last_location: Optional[Dict[str, Any]] = None
    eta_minutes: Optional[int] = None


def make_server_event(event_type: str, seq: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    from time import gmtime, strftime

    return {
        "type": event_type,
        "seq": seq,
        "sent_at": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
        "payload": payload,
    }
