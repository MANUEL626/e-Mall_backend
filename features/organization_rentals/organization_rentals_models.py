from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from features.organization_articles.organization_articles_models import CurrencyCode


class RentalReservationStatus(str, Enum):
    reserved = "reserved"
    rented = "rented"
    returned = "returned"
    late = "late"
    maintenance = "maintenance"
    cancelled = "cancelled"


class RentalProformaStatus(str, Enum):
    draft = "draft"
    issued = "issued"
    accepted = "accepted"
    expired = "expired"
    cancelled = "cancelled"
    converted = "converted"


class RentalProformaPaymentStatus(str, Enum):
    unpaid = "unpaid"
    partially_paid = "partially_paid"
    paid = "paid"
    refunded = "refunded"


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _blank_to_zero(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return Decimal("0")
    return value


def _normalize_decimal(value: Any) -> Any:
    value = _blank_to_none(value)
    if isinstance(value, str):
        return value.replace(",", ".").strip()
    return value


def _normalize_currency(value: Any) -> Any:
    value = _blank_to_none(value)
    if isinstance(value, str):
        return value.strip().lower()
    return value


class RentalReservationCreate(BaseModel):
    rental_asset_id: UUID
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=64)
    starts_at: datetime
    ends_at: datetime
    quantity: int = Field(1, ge=1)
    daily_rate: Optional[Decimal] = Field(None, ge=0)
    deposit_amount: Decimal = Field(Decimal("0"), ge=0)
    total_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=10000)

    @model_validator(mode="after")
    def period_is_valid(self) -> "RentalReservationCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("La date de fin doit etre apres la date de debut")
        return self

    @field_validator("daily_rate", "total_amount", mode="before")
    @classmethod
    def normalize_optional_decimal(cls, value: Any) -> Any:
        return _normalize_decimal(value)

    @field_validator("deposit_amount", mode="before")
    @classmethod
    def normalize_required_decimal(cls, value: Any) -> Any:
        return _blank_to_zero(_normalize_decimal(value))

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: Any) -> Any:
        return _normalize_currency(value)

    @field_validator("assigned_member_id", mode="before")
    @classmethod
    def normalize_optional_uuid(cls, value: Any) -> Any:
        return _blank_to_none(value)


class RentalOrderLineCreate(BaseModel):
    rental_asset_id: UUID
    quantity: int = Field(1, ge=1)
    daily_rate: Optional[Decimal] = Field(None, ge=0)
    total_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None

    @model_validator(mode="before")
    @classmethod
    def accept_common_asset_aliases(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if not data.get("rental_asset_id"):
            data["rental_asset_id"] = (
                data.get("asset_id")
                or data.get("article_id")
                or data.get("resource_id")
                or data.get("id")
            )
        return data

    @field_validator("daily_rate", "total_amount", mode="before")
    @classmethod
    def normalize_optional_decimal(cls, value: Any) -> Any:
        return _normalize_decimal(value)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: Any) -> Any:
        return _normalize_currency(value)


class RentalOrderCreate(BaseModel):
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=64)
    starts_at: datetime
    ends_at: datetime
    lines: List[RentalOrderLineCreate] = Field(..., min_length=1)
    deposit_amount: Decimal = Field(Decimal("0"), ge=0)
    discount_amount: Decimal = Field(Decimal("0"), ge=0)
    discount_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    discount_label: Optional[str] = Field(None, max_length=255)
    currency: Optional[CurrencyCode] = None
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=10000)

    @model_validator(mode="before")
    @classmethod
    def accept_common_lines_aliases(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data: Dict[str, Any] = dict(values)
        if "lines" not in data:
            data["lines"] = data.get("items") or data.get("assets") or data.get("articles")
        if "discount_amount" not in data and "discount" in data:
            data["discount_amount"] = data.get("discount")
        return data

    @model_validator(mode="after")
    def order_is_valid(self) -> "RentalOrderCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("La date de fin doit etre apres la date de debut")
        if self.discount_amount and self.discount_percent is not None:
            raise ValueError("Utiliser discount_amount ou discount_percent, pas les deux")
        asset_ids = [str(line.rental_asset_id) for line in self.lines]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("Un actif louable ne doit apparaitre qu'une fois par lot")
        return self

    @field_validator("deposit_amount", "discount_amount", mode="before")
    @classmethod
    def normalize_required_decimal(cls, value: Any) -> Any:
        return _blank_to_zero(_normalize_decimal(value))

    @field_validator("discount_percent", mode="before")
    @classmethod
    def normalize_optional_decimal(cls, value: Any) -> Any:
        return _normalize_decimal(value)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: Any) -> Any:
        return _normalize_currency(value)

    @field_validator("assigned_member_id", mode="before")
    @classmethod
    def normalize_optional_uuid(cls, value: Any) -> Any:
        return _blank_to_none(value)


class RentalProformaCreate(BaseModel):
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=64)
    customer_email: Optional[str] = Field(None, max_length=320)
    customer_address: Optional[str] = Field(None, max_length=1000)
    starts_at: datetime
    ends_at: datetime
    lines: List[RentalOrderLineCreate] = Field(..., min_length=1)
    security_deposit_amount: Decimal = Field(Decimal("0"), ge=0)
    discount_amount: Decimal = Field(Decimal("0"), ge=0)
    discount_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    discount_label: Optional[str] = Field(None, max_length=255)
    advance_required_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None
    assigned_member_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=10000)
    terms: Optional[str] = Field(None, max_length=20000)

    @model_validator(mode="before")
    @classmethod
    def accept_common_aliases(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data: Dict[str, Any] = dict(values)
        if "lines" not in data:
            data["lines"] = data.get("items") or data.get("assets") or data.get("articles")
        if "security_deposit_amount" not in data and "deposit_amount" in data:
            data["security_deposit_amount"] = data.get("deposit_amount")
        if "discount_amount" not in data and "discount" in data:
            data["discount_amount"] = data.get("discount")
        return data

    @model_validator(mode="after")
    def proforma_is_valid(self) -> "RentalProformaCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("La date de fin doit etre apres la date de debut")
        if self.discount_amount and self.discount_percent is not None:
            raise ValueError("Utiliser discount_amount ou discount_percent, pas les deux")
        asset_ids = [str(line.rental_asset_id) for line in self.lines]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("Un actif louable ne doit apparaitre qu'une fois par proforma")
        return self

    @field_validator("security_deposit_amount", "discount_amount", mode="before")
    @classmethod
    def normalize_required_decimal(cls, value: Any) -> Any:
        return _blank_to_zero(_normalize_decimal(value))

    @field_validator("discount_percent", "advance_required_amount", mode="before")
    @classmethod
    def normalize_optional_decimal(cls, value: Any) -> Any:
        return _normalize_decimal(value)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: Any) -> Any:
        return _normalize_currency(value)

    @field_validator("assigned_member_id", mode="before")
    @classmethod
    def normalize_optional_uuid(cls, value: Any) -> Any:
        return _blank_to_none(value)


class RentalProformaUpdate(BaseModel):
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=64)
    customer_email: Optional[str] = Field(None, max_length=320)
    customer_address: Optional[str] = Field(None, max_length=1000)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    lines: Optional[List[RentalOrderLineCreate]] = Field(None, min_length=1)
    security_deposit_amount: Optional[Decimal] = Field(None, ge=0)
    discount_amount: Optional[Decimal] = Field(None, ge=0)
    discount_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    discount_label: Optional[str] = Field(None, max_length=255)
    advance_required_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None
    assigned_member_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=10000)
    terms: Optional[str] = Field(None, max_length=20000)

    @field_validator(
        "security_deposit_amount",
        "discount_amount",
        "discount_percent",
        "advance_required_amount",
        mode="before",
    )
    @classmethod
    def normalize_optional_decimal(cls, value: Any) -> Any:
        return _normalize_decimal(value)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: Any) -> Any:
        return _normalize_currency(value)

    @field_validator("assigned_member_id", mode="before")
    @classmethod
    def normalize_optional_uuid(cls, value: Any) -> Any:
        return _blank_to_none(value)


class RentalProformaPaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0)
    currency: Optional[CurrencyCode] = None
    payment_method: str = Field("cash", min_length=1, max_length=64)
    payment_reference: Optional[str] = Field(None, max_length=255)
    idempotency_key: Optional[str] = Field(None, max_length=255)
    paid_at: Optional[datetime] = None
    note: Optional[str] = Field(None, max_length=1000)
    auto_convert: bool = True

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value: Any) -> Any:
        return _normalize_decimal(value)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: Any) -> Any:
        return _normalize_currency(value)


class RentalReservationUpdate(BaseModel):
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=64)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    quantity: Optional[int] = Field(None, ge=1)
    daily_rate: Optional[Decimal] = Field(None, ge=0)
    deposit_amount: Optional[Decimal] = Field(None, ge=0)
    total_amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[CurrencyCode] = None
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=10000)

    @field_validator(
        "daily_rate",
        "deposit_amount",
        "total_amount",
        mode="before",
    )
    @classmethod
    def normalize_optional_decimal(cls, value: Any) -> Any:
        return _normalize_decimal(value)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, value: Any) -> Any:
        return _normalize_currency(value)

    @field_validator("assigned_member_id", mode="before")
    @classmethod
    def normalize_optional_uuid(cls, value: Any) -> Any:
        return _blank_to_none(value)


class RentalStatusUpdate(BaseModel):
    status: RentalReservationStatus
    note: Optional[str] = Field(None, max_length=10000)


class RentalActionRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=10000)


class RentalAvailabilityResponse(BaseModel):
    organization_id: UUID
    shop_id: UUID
    rental_asset_id: UUID
    starts_at: datetime
    ends_at: datetime
    stock_quantity: int
    reserved_quantity_now: int
    overlapping_reserved_quantity: int
    available_quantity: int


class RentalAssetSnapshot(BaseModel):
    id: UUID
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    unit_purchase_price: Optional[Decimal] = None
    unit_rental_price: Optional[Decimal] = None
    rental_currency: Optional[CurrencyCode] = None
    rental_bulk_prices: Optional[Any] = None
    primary_image_storage_path: Optional[str] = None
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    active: Optional[bool] = None

    model_config = {"from_attributes": True}


class RentalOrderLineResponse(BaseModel):
    id: UUID
    rental_order_id: UUID
    rental_asset_id: UUID
    quantity: int
    daily_rate: Optional[Decimal] = None
    line_subtotal: Decimal = Decimal("0")
    currency: CurrencyCode = CurrencyCode.xof
    created_at: datetime
    asset: Optional[RentalAssetSnapshot] = None

    model_config = {"from_attributes": True}


class RentalProformaLineResponse(BaseModel):
    id: UUID
    rental_proforma_id: UUID
    rental_asset_id: UUID
    quantity: int
    daily_rate: Decimal = Decimal("0")
    line_subtotal: Decimal = Decimal("0")
    currency: CurrencyCode = CurrencyCode.xof
    asset_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class RentalProformaPaymentResponse(BaseModel):
    id: UUID
    rental_proforma_id: UUID
    organization_id: UUID
    shop_id: UUID
    amount: Decimal
    currency: CurrencyCode
    payment_method: str
    payment_reference: Optional[str] = None
    status: str
    paid_at: datetime
    note: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RentalProformaResponse(BaseModel):
    id: UUID
    organization_id: UUID
    shop_id: UUID
    proforma_number: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_address: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    subtotal_amount: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    discount_label: Optional[str] = None
    security_deposit_amount: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")
    total_payable_amount: Decimal = Decimal("0")
    advance_required_amount: Decimal = Decimal("0")
    amount_paid: Decimal = Decimal("0")
    currency: CurrencyCode = CurrencyCode.xof
    status: RentalProformaStatus
    payment_status: RentalProformaPaymentStatus
    assigned_member_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    converted_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    converted_rental_order_id: Optional[UUID] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    organization_snapshot: Dict[str, Any] = Field(default_factory=dict)
    shop_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_by_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    lines: List[RentalProformaLineResponse] = Field(default_factory=list)
    payments: List[RentalProformaPaymentResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RentalOrderResponse(BaseModel):
    id: UUID
    organization_id: UUID
    shop_id: UUID
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    deposit_amount: Decimal = Decimal("0")
    subtotal_amount: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    discount_label: Optional[str] = None
    total_amount: Decimal = Decimal("0")
    currency: CurrencyCode = CurrencyCode.xof
    status: RentalReservationStatus
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    returned_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    lines: List[RentalOrderLineResponse] = Field(default_factory=list)
    source_proforma_id: Optional[UUID] = None

    model_config = {"from_attributes": True}


class RentalProformaPaymentResult(BaseModel):
    proforma: RentalProformaResponse
    rental_order: Optional[RentalOrderResponse] = None
    conversion_error: Optional[str] = None


class RentalInvoiceResponse(BaseModel):
    id: UUID
    rental_order_id: UUID
    organization_id: UUID
    shop_id: UUID
    invoice_number: str
    currency: CurrencyCode = CurrencyCode.xof
    subtotal_amount: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    deposit_amount: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")
    total_items: int = 0
    total_lines: int = 0
    status: str = "issued"
    customer_label: Optional[str] = None
    organization_snapshot: Dict[str, Any] = Field(default_factory=dict)
    shop_snapshot: Dict[str, Any] = Field(default_factory=dict)
    rental_snapshot: Dict[str, Any] = Field(default_factory=dict)
    lines_snapshot: List[Dict[str, Any]] = Field(default_factory=list)
    issued_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RentalReservationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    shop_id: UUID
    rental_asset_id: UUID
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    quantity: int
    daily_rate: Optional[Decimal] = None
    deposit_amount: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")
    currency: CurrencyCode = CurrencyCode.xof
    status: RentalReservationStatus
    assigned_member_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    returned_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    asset: Optional[RentalAssetSnapshot] = None

    model_config = {"from_attributes": True}
