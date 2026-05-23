"""Modèles Pydantic : abonnements client → organisation."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SubscribeOrganizationBody(BaseModel):
    organization_id: UUID = Field(..., description="Identifiant de l’organisation marchande.")


class CustomerSubscriptionOrganization(BaseModel):
    id: UUID
    name: str
    org_type: str


class CustomerSubscriptionItem(BaseModel):
    id: UUID
    organization_id: UUID
    organization: CustomerSubscriptionOrganization
    status: str
    subscribed_at: Any
    cancelled_at: Optional[Any] = None


class CustomerSubscriptionsListResponse(BaseModel):
    items: List[CustomerSubscriptionItem]


class CustomerSubscribeResponse(BaseModel):
    id: UUID
    organization_id: UUID
    status: str
    subscribed_at: Any


class MemberSubscriberItem(BaseModel):
    customer_id: UUID
    username: str
    subscribed_at: Any


class MemberSubscribersPage(BaseModel):
    items: List[MemberSubscriberItem]
    total: int
    limit: int
    offset: int


class CustomerOrganizationSummary(BaseModel):
    """Aperçu léger d’une organisation pour l’app client."""

    id: UUID
    name: str
    subscriber_count: int = Field(..., ge=0, description="Nombre d’abonnements actifs.")
