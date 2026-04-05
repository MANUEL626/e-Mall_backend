"""
Routes réservées aux utilisateurs `public.users.user_type = member`.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.members.members_models import MemberMeResponse
from features.members.members_service import (
    MembersService,
    NotMemberError,
    ProfileNotFoundError,
)

router = APIRouter(prefix="/api/v1/members", tags=["Members"])

security = HTTPBearer()
_auth = AuthService()
_service = MembersService()


@router.get("/me", response_model=MemberMeResponse)
def get_current_member_profile(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Retourne le profil du membre connecté : ligne `users`, `username`, prénom/nom,
    e-mail applicatif, et pour chaque adhésion les champs `members` + l’organisation
    complète (`name`, `org_type`, `description`, …).

    Auth : `Authorization: Bearer <access_token Supabase>`.
    """
    token = credentials.credentials
    try:
        go_true = _auth.get_auth_user_from_access_token(token)
        user_id = str(go_true["id"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    try:
        payload = _service.get_me(user_id, go_true_user=go_true)
        return MemberMeResponse(**payload)
    except ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profil utilisateur introuvable",
        ) from exc
    except NotMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte n'est pas un membre d'organisation",
        ) from exc
