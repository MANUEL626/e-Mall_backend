"""
Pydantic models for organization subscriptions.
"""

from datetime import datetime
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


class OrganizationSubscriptionPlanOut(BaseModel):
    code: OrganizationSubscriptionPlanCode
    name: str
    description: Optional[str] = None
    features: Dict[str, Any] = Field(default_factory=dict)
    limits: Dict[str, Any] = Field(default_factory=dict)
    stripe_product_id: Optional[str] = None
    stripe_monthly_price_id: Optional[str] = None
    stripe_yearly_price_id: Optional[str] = None
    active: bool = True
    sort_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrganizationSubscriptionPlansResponse(BaseModel):
    plans: List[OrganizationSubscriptionPlanOut]


class OrganizationSubscriptionOut(BaseModel):
    organization_id: UUID
    plan: OrganizationSubscriptionPlanCode
    status: OrganizationSubscriptionStatus
    source: OrganizationSubscriptionSource
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    plan_details: Optional[OrganizationSubscriptionPlanOut] = None


class OrganizationSubscriptionUsage(BaseModel):
    active_articles: int = 0
    team_members: int = 0
    monthly_walk_in_sales: int = 0


class OrganizationSubscriptionEntitlements(BaseModel):
    organization_id: UUID
    plan: OrganizationSubscriptionPlanCode
    status: OrganizationSubscriptionStatus
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
    current_period_end: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "OrganizationSubscriptionPatch":
        if (
            self.plan is None
            and self.status is None
            and self.source is None
            and self.current_period_end is None
            and self.trial_end is None
            and self.cancel_at_period_end is None
            and self.metadata is None
        ):
            raise ValueError("Au moins un champ d'abonnement est requis")
        return self

