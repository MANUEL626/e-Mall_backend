from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserType(str, Enum):
    """Types d'utilisateurs compatibles avec le schéma applicatif (public.user_type_enum)."""

    player = "player"
    admin = "admin"
    super_admin = "super_admin"


class UserProfileAggregatedResponse(BaseModel):
    """Profil `public.users` + ligne `customers` ou `admins` selon `user_type` (équivalent de l’ancienne RPC)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    user_type: UserType
    activity_status: bool
    profile_picture: Optional[str] = None
    created_at: datetime
    # Ajout : état de finalisation des paramètres applicatifs (public.user_params.is_params_done)
    is_params_done: bool
    player_id: Optional[UUID] = None
    username: Optional[str] = None
    admin_id: Optional[UUID] = None


class UpdateUserRequest(BaseModel):
    """Mise à jour d'un utilisateur (public.users + éventuellement public.customers)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, alias="firstname")
    last_name: Optional[str] = Field(None, alias="lastname")
    phone: Optional[str] = None
    activity_status: Optional[bool] = Field(None, alias="activitystatus")
    profile_picture: Optional[str] = Field(None, alias="profilepicture")
    username: Optional[str] = None


class ThemeUserParams(str, Enum):
    """Thème utilisable pour `public.user_params.theme`."""

    light = "light"
    dark = "dark"


class UserParamsResponse(BaseModel):
    """Retourne les paramètres applicatifs d'un utilisateur."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    country: str
    language_setting: str
    notification: bool
    theme: ThemeUserParams
    is_params_done: bool
    created_at: datetime
    updated_at: datetime


class UpdateUserParamsRequest(BaseModel):
    """Mise à jour partielle de `public.user_params`."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    country: Optional[str] = None
    language_setting: Optional[str] = None
    notification: Optional[bool] = None
    theme: Optional[ThemeUserParams] = None
    is_params_done: Optional[bool] = None
