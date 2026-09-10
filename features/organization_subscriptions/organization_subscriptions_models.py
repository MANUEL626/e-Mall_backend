"""
Pydantic models for organization subscriptions.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class OrganizationSubscriptionPlanCode(str, Enum):
    freemium = "freemium"
    standard = "standard"
    premium = "premium"


class OrganizationSubscriptionStatus(str, Enum):
    trialing = "trialing"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"
    expired = "expired"
    suspended = "suspended"


class OrganizationSubscriptionSource(str, Enum):
    internal = "internal"
    manual = "manual"
    stripe = "stripe"
    promo = "promo"


class OrganizationSubscriptionBillingInterval(str, Enum):
    monthly = "monthly"
    yearly = "yearly"


class OrganizationSubscriptionPlanOut(BaseModel):
    code: OrganizationSubscriptionPlanCode
    name: str
    description: Optional[str] = None
    features: Dict[str, Any] = Field(default_factory=dict)
    limits: Dict[str, Any] = Field(default_factory=dict)
    price_currency: str = "xof"
    monthly_price_amount: Optional[Decimal] = None
    yearly_price_amount: Optional[Decimal] = None
    yearly_savings_amount: Optional[Decimal] = None
    yearly_savings_percent: Optional[Decimal] = None
    stripe_product_id: Optional[str] = None
    stripe_monthly_price_id: Optional[str] = None
    stripe_yearly_price_id: Optional[str] = None
    active: bool = True
    sort_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganizationSubscriptionPlansResponse(BaseModel):
    plans: List[OrganizationSubscriptionPlanOut]


class OrganizationSubscriptionCheckoutCreate(BaseModel):
    plan: OrganizationSubscriptionPlanCode
    billing_interval: OrganizationSubscriptionBillingInterval


class OrganizationSubscriptionCheckoutResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str


class OrganizationSubscriptionPortalResponse(BaseModel):
    portal_url: str


class OrganizationSubscriptionInvoiceOut(BaseModel):
    id: str
    number: Optional[str] = None
    status: Optional[str] = None
    currency: Optional[str] = None
    amount_due: int = 0
    amount_paid: int = 0
    amount_remaining: int = 0
    created: Optional[datetime] = None
    due_date: Optional[datetime] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    hosted_invoice_url: Optional[str] = None
    invoice_pdf: Optional[str] = None
    subscription_id: Optional[str] = None


class OrganizationSubscriptionInvoicesResponse(BaseModel):
    invoices: List[OrganizationSubscriptionInvoiceOut]


class OrganizationSubscriptionOut(BaseModel):
    organization_id: UUID
    plan: OrganizationSubscriptionPlanCode
    effective_plan: OrganizationSubscriptionPlanCode = OrganizationSubscriptionPlanCode.freemium
    status: OrganizationSubscriptionStatus
    effective_status: OrganizationSubscriptionStatus
    source: OrganizationSubscriptionSource
    billing_interval: OrganizationSubscriptionBillingInterval = OrganizationSubscriptionBillingInterval.monthly
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    stripe_price_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    plan_details: Optional[OrganizationSubscriptionPlanOut] = None
    effective_plan_details: Optional[OrganizationSubscriptionPlanOut] = None


class OrganizationSubscriptionUsage(BaseModel):
    active_articles: int = 0
    team_members: int = 0
    monthly_walk_in_sales: int = 0


class OrganizationSubscriptionEntitlements(BaseModel):
    organization_id: UUID
    plan: OrganizationSubscriptionPlanCode
    effective_plan: OrganizationSubscriptionPlanCode
    status: OrganizationSubscriptionStatus
    effective_status: OrganizationSubscriptionStatus
    is_active: bool
    features: Dict[str, Any] = Field(default_factory=dict)
    limits: Dict[str, Any] = Field(default_factory=dict)
    usage: OrganizationSubscriptionUsage
    exceeded_limits: Dict[str, bool] = Field(default_factory=dict)
    subscription: OrganizationSubscriptionOut


class OrganizationSubscriptionPatch(BaseModel):
    """Manual/dev update. Stripe webhooks will use the same internal fields later."""

    plan: Optional[OrganizationSubscriptionPlanCode] = None
    status: Optional[OrganizationSubscriptionStatus] = None
    source: Optional[OrganizationSubscriptionSource] = None
    billing_interval: Optional[OrganizationSubscriptionBillingInterval] = None
    current_period_end: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    stripe_price_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "OrganizationSubscriptionPatch":
        if (
            self.plan is None
            and self.status is None
            and self.source is None
            and self.billing_interval is None
            and self.current_period_end is None
            and self.trial_end is None
            and self.cancel_at_period_end is None
            and self.stripe_price_id is None
            and self.metadata is None
        ):
            raise ValueError("Au moins un champ d'abonnement est requis")
        return self
