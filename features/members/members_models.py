"""
Réponses API : profil membre connecté + adhésions et organisations.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MemberMeResponse(BaseModel):
    """Profil `public.users` + une entrée par ligne `members` avec l’organisation jointe."""

    user: Dict[str, Any] = Field(
        ...,
        description="Ligne `public.users` (id, email, first_name, last_name, username, user_type, …)",
    )
    memberships: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Chaque élément : champs `members` + clé `organization` (ligne `organizations`)",
    )
    auth: Optional[Dict[str, Any]] = Field(
        None,
        description="Champs utiles issus du JWT GoTrue (email, phone, …) sans secrets",
    )
