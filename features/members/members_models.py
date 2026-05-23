"""
Reponses API : profil membre connecte, profil affichable et parametres.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class MemberMeResponse(BaseModel):
    """Profil `public.users` + adhesions `members` avec l'organisation jointe."""

    user: Dict[str, Any] = Field(
        ...,
        description="Ligne public.users (id, email, first_name, last_name, username, user_type, ...)",
    )
    memberships: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Chaque element: champs members + cle organization (ligne organizations)",
    )
    auth: Optional[Dict[str, Any]] = Field(
        None,
        description="Champs utiles issus du JWT GoTrue (email, phone, ...) sans secrets",
    )
    params: Optional[Dict[str, Any]] = Field(
        None,
        description="Parametres personnels du membre, notamment locale: fr, en, de, zh.",
    )


class MemberProfilePatch(BaseModel):
    """Mise a jour partielle du profil `public.users` d'un membre."""

    first_name: Optional[str] = Field(None, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)
    username: Optional[str] = Field(None, max_length=50)
    profile_picture: Optional[str] = Field(None, max_length=25_000_000)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "MemberProfilePatch":
        if (
            self.first_name is None
            and self.last_name is None
            and self.username is None
            and self.profile_picture is None
        ):
            raise ValueError(
                "Au moins un parmi first_name, last_name, username, profile_picture est requis"
            )
        return self


class MemberParamsOut(BaseModel):
    user_id: UUID
    locale: str
    extra: Optional[dict] = None
    updated_at: datetime


class MemberParamsPatch(BaseModel):
    """Mise a jour partielle des parametres personnels du membre."""

    locale: Optional[str] = Field(
        None,
        description="Langue membre: fr, en, de, zh.",
    )
    extra: Optional[dict] = None

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        locale = value.strip().lower()
        if locale not in {"fr", "en", "de", "zh"}:
            raise ValueError("locale doit etre fr, en, de ou zh")
        return locale

    @model_validator(mode="after")
    def at_least_one_field(self) -> "MemberParamsPatch":
        if self.locale is None and self.extra is None:
            raise ValueError("Au moins un parmi locale, extra est requis")
        return self
