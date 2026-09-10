from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from features.organization_articles.organization_articles_models import CurrencyCode


class RepairRequestStatus(str, Enum):
    requested = "requested"
    received = "received"
    diagnosing = "diagnosing"
    quote_sent = "quote_sent"
    approved = "approved"
    repairing = "repairing"
    ready_for_pickup = "ready_for_pickup"
    delivered = "delivered"
    cancelled = "cancelled"


class RepairRequestCreate(BaseModel):
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=64)
    item_label: str = Field(..., min_length=1, max_length=500)
    issue_description: Optional[str] = Field(None, max_length=10000)
    diagnostic: Optional[str] = Field(None, max_length=10000)
    quote_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=10000)


class RepairRequestUpdate(BaseModel):
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=64)
    item_label: Optional[str] = Field(None, min_length=1, max_length=500)
    issue_description: Optional[str] = Field(None, max_length=10000)
    diagnostic: Optional[str] = Field(None, max_length=10000)
    quote_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=10000)


class RepairStatusUpdate(BaseModel):
    status: RepairRequestStatus
    note: Optional[str] = Field(None, max_length=10000)


class RepairActionRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=10000)


class RepairSendQuoteRequest(RepairActionRequest):
    diagnostic: Optional[str] = Field(None, max_length=10000)
    quote_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None


class RepairPartCreate(BaseModel):
    resource_id: UUID
    quantity: int = Field(..., ge=1)
    unit_cost: Optional[Decimal] = Field(None, ge=0)
    total_cost: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None
    note: Optional[str] = Field(None, max_length=2000)


class RepairPartResponse(BaseModel):
    id: UUID
    organization_id: UUID
    shop_id: UUID
    repair_request_id: UUID
    resource_id: UUID
    quantity: int
    unit_cost: Optional[Decimal] = None
    total_cost: Decimal = Decimal("0")
    currency: CurrencyCode = CurrencyCode.xof
    note: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RepairInvoiceResponse(BaseModel):
    id: UUID
    repair_request_id: UUID
    organization_id: UUID
    shop_id: UUID
    invoice_number: str
    currency: CurrencyCode = CurrencyCode.xof
    labor_amount: Decimal = Decimal("0")
    parts_amount: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")
    total_parts: int = 0
    total_lines: int = 0
    status: str = "issued"
    customer_label: Optional[str] = None
    organization_snapshot: Dict[str, Any] = Field(default_factory=dict)
    shop_snapshot: Dict[str, Any] = Field(default_factory=dict)
    repair_snapshot: Dict[str, Any] = Field(default_factory=dict)
    parts_snapshot: List[Dict[str, Any]] = Field(default_factory=list)
    issued_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RepairRequestResponse(BaseModel):
    id: UUID
    organization_id: UUID
    shop_id: UUID
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    item_label: str
    issue_description: Optional[str] = None
    diagnostic: Optional[str] = None
    quote_amount: Optional[Decimal] = None
    currency: CurrencyCode = CurrencyCode.xof
    status: RepairRequestStatus
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    received_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
