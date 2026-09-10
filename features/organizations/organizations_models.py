"""
Modèles Pydantic : inscription membre + organisation.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from features.organization_articles.organization_articles_models import CurrencyCode


class OrganizationCategory(str, Enum):
    """Type de la boutique par defaut (compat: aussi stocke dans org_type)."""

    delivery = "delivery"
    repair = "repair"
    rental = "rental"
    sales = "sales"


class OrganizationDefaultCurrencies(BaseModel):
    purchase: CurrencyCode = CurrencyCode.xof
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
    default_shop_id: Optional[UUID] = None
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
    shop_ids: List[UUID] = Field(
        ...,
        min_length=1,
        description="Boutiques auxquelles affecter le membre invite. Obligatoire en phase multi-boutiques.",
    )
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
    shop_ids: List[UUID] = Field(default_factory=list)


class OrganizationShopType(str, Enum):
    sales = "sales"
    delivery = "delivery"
    repair = "repair"
    rental = "rental"


class OrganizationShopStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    archived = "archived"


class OrganizationShopCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    shop_type: OrganizationShopType
    code: Optional[str] = Field(None, max_length=80)
    description: Optional[str] = Field(None, max_length=10_000)
    is_default: bool = False
    country: Optional[str] = Field(None, max_length=2)
    city: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=1000)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    profile_picture: Optional[str] = Field(None, max_length=25_000_000)
    settings: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        code = value.strip().upper()
        if not code:
            return None
        if len(code) != 2 or not code.isalpha():
            raise ValueError("country doit etre un code pays ISO alpha-2, ex: TG")
        return code


class OrganizationShopUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    code: Optional[str] = Field(None, max_length=80)
    description: Optional[str] = Field(None, max_length=10_000)
    shop_type: Optional[OrganizationShopType] = None
    status: Optional[OrganizationShopStatus] = None
    is_default: Optional[bool] = None
    country: Optional[str] = Field(None, max_length=2)
    city: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=1000)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    profile_picture: Optional[str] = Field(None, max_length=25_000_000)
    settings: Optional[Dict[str, Any]] = None

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        code = value.strip().upper()
        if not code:
            return None
        if len(code) != 2 or not code.isalpha():
            raise ValueError("country doit etre un code pays ISO alpha-2, ex: TG")
        return code

    @model_validator(mode="after")
    def at_least_one_field(self) -> "OrganizationShopUpdateRequest":
        if all(
            value is None
            for value in (
                self.name,
                self.code,
                self.description,
                self.shop_type,
                self.status,
                self.is_default,
                self.country,
                self.city,
                self.address,
                self.longitude,
                self.latitude,
                self.phone,
                self.email,
                self.profile_picture,
                self.settings,
            )
        ):
            raise ValueError("Au moins un champ boutique est requis")
        return self


class OrganizationShopItem(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    shop_type: OrganizationShopType
    status: OrganizationShopStatus
    is_default: bool
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    profile_picture: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    created_by_user_id: Optional[UUID] = None
    created_at: Any
    updated_at: Any


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
    shops: List[Dict[str, Any]] = Field(default_factory=list)


class OrganizationMembersListResponse(BaseModel):
    members: List[OrganizationMemberItem]


class UpdateOrganizationMemberRequest(BaseModel):
    """Au moins un champ doit être fourni."""

    activity_status: Optional[bool] = None
    member_type: Optional[MemberType] = None
    member_role: Optional[MemberRole] = None
    shop_ids: Optional[List[UUID]] = Field(
        None,
        description="Remplace les boutiques affectees a ce membre. Liste vide = retirer les affectations boutique.",
    )

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateOrganizationMemberRequest":
        if (
            self.activity_status is None
            and self.member_type is None
            and self.member_role is None
            and self.shop_ids is None
        ):
            raise ValueError(
                "Au moins un parmi activity_status, member_type, member_role, shop_ids est requis"
            )
        return self
