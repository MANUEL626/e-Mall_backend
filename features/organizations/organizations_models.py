"""
Modèles Pydantic : inscription membre + organisation.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


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


class InviteOrganizationMemberRequest(BaseModel):
    """Invitation d’un membre par e-mail uniquement (profil complété plus tard)."""

    email: EmailStr
    redirect_to: Optional[str] = Field(
        None,
        max_length=2000,
        description="URL autorisée dans Supabase Auth (redirection après clic sur le lien d’invitation / récupération).",
    )


class InviteOrganizationMemberResponse(BaseModel):
    success: bool
    message: str
    user_id: UUID
    email: str
    organization_id: UUID


class MemberType(str, Enum):
    """Valeurs de `public.member_type_enum`."""

    admin = "admin"
    supervisor = "supervisor"
    member = "member"


class MemberRole(str, Enum):
    """Valeurs de `public.member_role_enum`."""

    sales_management = "sales_management"
    delivery_management = "delivery_management"


class OrganizationMemberItem(BaseModel):
    """Ligne `members` + profil `users` associé."""

    id: UUID
    user_id: UUID
    organization_id: UUID
    member_type: str
    member_role: str
    activity_status: bool
    created_at: Any
    user: Dict[str, Any]


class OrganizationMembersListResponse(BaseModel):
    members: List[OrganizationMemberItem]


class UpdateOrganizationMemberRequest(BaseModel):
    """Au moins un champ doit être fourni."""

    activity_status: Optional[bool] = None
    member_type: Optional[MemberType] = None
    member_role: Optional[MemberRole] = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateOrganizationMemberRequest":
        if (
            self.activity_status is None
            and self.member_type is None
            and self.member_role is None
        ):
            raise ValueError(
                "Au moins un parmi activity_status, member_type, member_role est requis"
            )
        return self
