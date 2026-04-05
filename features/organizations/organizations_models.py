"""
Modèles Pydantic : inscription membre + organisation.
"""

from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class OrganizationCategory(str, Enum):
    """Valeurs de `public.organization_type_enum`."""

    delivery = "delivery"
    sales = "sales"


class RegisterMemberOrganizationRequest(BaseModel):
    organization_name: str = Field(..., min_length=1, max_length=500)
    organization_category: OrganizationCategory
    organization_description: Optional[str] = Field(None, max_length=10_000)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class RegisterMemberOrganizationResponse(BaseModel):
    success: bool
    message: str
    user_id: UUID
    username: str
    organization_id: UUID
