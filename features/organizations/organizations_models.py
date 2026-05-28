"""
Modèles Pydantic : inscription membre + organisation.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from features.organization_articles.organization_articles_models import CurrencyCode


class OrganizationCategory(str, Enum):
    """Valeurs de `public.organization_type_enum`."""

    delivery = "delivery"
    sales = "sales"


class OrganizationDefaultCurrencies(BaseModel):
    purchase: CurrencyCode = CurrencyCode.eur
    sale: CurrencyCode = CurrencyCode.xof


class RegisterMemberOrganizationRequest(BaseModel):
    organization_name: str = Field(..., min_length=1, max_length=500)
    organization_category: OrganizationCategory
    organization_description: Optional[str] = Field(None, max_length=10_000)
    organization_profile_picture: Optional[str] = Field(None, max_length=25_000_000)
    organization_countries: List[str] = Field(default_factory=list)
    organization_default_currencies: OrganizationDefaultCurrencies = Field(
        default_factory=OrganizationDefaultCurrencies
    )
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    member_first_name: Optional[str] = Field(None, max_length=50)
    member_last_name: Optional[str] = Field(None, max_length=50)
    member_username: Optional[str] = Field(None, max_length=50)
    member_profile_picture: Optional[str] = Field(None, max_length=25_000_000)
    member_locale: Optional[str] = Field(
        "fr",
        description="Langue membre: fr, en, de, zh.",
    )

    @field_validator("organization_countries")
    @classmethod
    def validate_organization_countries(cls, value: List[str]) -> List[str]:
        out: List[str] = []
        for item in value or []:
            code = str(item).strip().upper()
            if not code:
                continue
            if len(code) != 2 or not code.isalpha():
                raise ValueError(
                    "organization_countries doit contenir des codes pays ISO alpha-2, ex: TG, NG"
                )
            if code not in out:
                out.append(code)
        return out

    @field_validator("member_locale")
    @classmethod
    def validate_member_locale(cls, value: Optional[str]) -> str:
        locale = (value or "fr").strip().lower()
        if locale not in {"fr", "en", "de", "zh"}:
            raise ValueError("member_locale doit etre fr, en, de ou zh")
        return locale


class RegisterMemberOrganizationResponse(BaseModel):
    success: bool
    message: str
    user_id: UUID
    username: str
    organization_id: UUID
    organization_profile_picture: Optional[str] = None
    organization_countries: List[str] = Field(default_factory=list)
    organization_default_currencies: OrganizationDefaultCurrencies = Field(
        default_factory=OrganizationDefaultCurrencies
    )
    member_profile_picture: Optional[str] = None
    member_locale: str = "fr"


class UpdateOrganizationProfileRequest(BaseModel):
    """Mise a jour partielle de la fiche organisation."""

    name: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=10_000)
    profile_picture: Optional[str] = Field(None, max_length=25_000_000)
    countries: Optional[List[str]] = None
    default_currencies: Optional[OrganizationDefaultCurrencies] = None

    @field_validator("countries")
    @classmethod
    def validate_countries(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        out: List[str] = []
        for item in value or []:
            code = str(item).strip().upper()
            if not code:
                continue
            if len(code) != 2 or not code.isalpha():
                raise ValueError(
                    "countries doit contenir des codes pays ISO alpha-2, ex: TG, NG"
                )
            if code not in out:
                out.append(code)
        return out

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateOrganizationProfileRequest":
        if (
            self.name is None
            and self.description is None
            and self.profile_picture is None
            and self.countries is None
            and self.default_currencies is None
        ):
            raise ValueError(
                "Au moins un parmi name, description, profile_picture, countries, default_currencies est requis"
            )
        return self


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
