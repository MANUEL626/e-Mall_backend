"""
Modèles Pydantic : ventes client (alignés sur les enums Postgres).
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CustomerSaleFulfillment(str, Enum):
    pickup = "pickup"
    delivery = "delivery"
    walk_in_offline = "walk_in_offline"


class CustomerSaleOrderStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    in_delivery = "in_delivery"
    cancelled = "cancelled"
    completed = "completed"


class StatusGroup(str, Enum):
    """Filtre API `status_group` / `bucket` (guide §11.2)."""

    in_progress = "in_progress"
    in_delivery = "in_delivery"
    cancelled = "cancelled"
    completed = "completed"


class CustomerParamsOut(BaseModel):
    customer_id: UUID
    locale: str
    default_longitude: Optional[float] = None
    default_latitude: Optional[float] = None
    extra: Optional[dict] = None
    updated_at: datetime


class CustomerParamsPatch(BaseModel):
    locale: Optional[str] = None
    default_longitude: Optional[float] = None
    default_latitude: Optional[float] = None
    extra: Optional[dict] = None


class SaleOrderLineIn(BaseModel):
    article_id: UUID
    quantity: int = Field(..., ge=1)


class CustomerSaleOrderCreate(BaseModel):
    organization_id: UUID
    fulfillment_type: CustomerSaleFulfillment
    lines: List[SaleOrderLineIn] = Field(..., min_length=1)
    delivery_longitude: Optional[float] = None
    delivery_latitude: Optional[float] = None
    notes: Optional[str] = None


class WalkInSaleCreate(BaseModel):
    lines: List[SaleOrderLineIn] = Field(..., min_length=1)
    external_customer_label: Optional[str] = None
    notes: Optional[str] = None


class PatchOrderStatusBody(BaseModel):
    status: CustomerSaleOrderStatus
    note: Optional[str] = None


class ConfirmReceiptBody(BaseModel):
    secret: str = Field(..., min_length=1)
    note: Optional[str] = None


class AssignDeliveryBody(BaseModel):
    member_id: UUID = Field(
        ...,
        description="id de la ligne `members` (livreur) pour cette organisation",
    )


class QrPayloadOut(BaseModel):
    order_id: UUID
    organization_id: UUID
    secret: str
    """Secret en clair : à encoder dans le QR (affichage côté magasin / livreur)."""
    qr_payload: str
    """Chaîne compacte pour QR (ex. préfixe app)."""


class SaleOrderLineOut(BaseModel):
    id: UUID
    article_id: UUID
    article_name: Optional[str] = None
    quantity: int
    unit_price_snapshot: Decimal


class SaleOrderOut(BaseModel):
    id: UUID
    organization_id: UUID
    fulfillment_type: CustomerSaleFulfillment
    customer_id: Optional[UUID] = None
    status: CustomerSaleOrderStatus
    assigned_delivery_member_id: Optional[UUID] = None
    delivery_longitude: Optional[float] = None
    delivery_latitude: Optional[float] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    external_customer_label: Optional[str] = None
    subtotal_amount: Decimal
    total_items: int
    total_lines: int
    created_at: datetime
    updated_at: datetime


class SaleOrderDetailOut(BaseModel):
    order: SaleOrderOut
    lines: List[SaleOrderLineOut]


class StatusEventOut(BaseModel):
    id: UUID
    order_id: UUID
    from_status: Optional[CustomerSaleOrderStatus] = None
    to_status: CustomerSaleOrderStatus
    note: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    created_at: datetime


class ReceiptTokenCreated(BaseModel):
    order_id: UUID
    secret: str
    qr_payload: str
    expires_at: Optional[datetime] = None
