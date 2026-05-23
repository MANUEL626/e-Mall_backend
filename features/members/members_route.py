"""
Routes réservées aux utilisateurs `public.users.user_type = member`.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.customers.customer_subscriptions_models import (
    MemberSubscriberItem,
    MemberSubscribersPage,
)
from features.customers.customer_subscriptions_service import CustomerSubscriptionsService
from features.members.members_models import (
    MemberMeResponse,
    MemberParamsOut,
    MemberParamsPatch,
    MemberProfilePatch,
)
from features.members.members_service import (
    MembersService,
    NotMemberError,
    NotOrgMemberError,
    ProfileNotFoundError,
)

router = APIRouter(prefix="/api/v1/members", tags=["Members"])

security = HTTPBearer()
_auth = AuthService()
_service = MembersService()
_subscriptions = CustomerSubscriptionsService()

_SUBSCRIBERS_LIMIT_DEFAULT = 50
_SUBSCRIBERS_LIMIT_MAX = 200


def _require_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


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


@router.patch("/me/profile")
def update_current_member_profile(
    body: MemberProfilePatch,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Complete ou modifie le profil affichable du membre connecte.

    Utile apres inscription directe ou apres acceptation d'une invitation.
    """
    user_id = _require_user_id(credentials)
    try:
        return _service.update_my_profile(
            user_id,
            first_name=body.first_name,
            last_name=body.last_name,
            username=body.username,
            profile_picture=body.profile_picture,
        )
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/me/params", response_model=MemberParamsOut)
def get_current_member_params(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Lit les parametres personnels du membre.

    Si la ligne n'existe pas encore, elle est creee avec `locale = "fr"`.
    """
    user_id = _require_user_id(credentials)
    try:
        return _service.get_or_create_member_params(user_id)
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.patch("/me/params", response_model=MemberParamsOut)
def update_current_member_params(
    body: MemberParamsPatch,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Met a jour les parametres personnels du membre.

    Langues supportees: `fr`, `en`, `de`, `zh`.
    """
    user_id = _require_user_id(credentials)
    try:
        return _service.update_member_params(
            user_id,
            locale=body.locale,
            extra=body.extra,
        )
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/organizations/{organization_id}/subscribers",
    response_model=MemberSubscribersPage,
)
def list_organization_subscribers(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    limit: int = Query(
        _SUBSCRIBERS_LIMIT_DEFAULT,
        ge=1,
        le=_SUBSCRIBERS_LIMIT_MAX,
        description="Taille de page.",
    ),
    offset: int = Query(0, ge=0, description="Décalage pagination."),
):
    """
    Abonnés actifs d’une organisation (membre actif de cette organisation uniquement).
    Retour minimal : identifiant client public et pseudo applicatif.
    """
    user_id = _require_user_id(credentials)
    try:
        _service.assert_user_is_member(user_id)
        _service.assert_active_member_of_org(user_id, str(organization_id))
    except NotMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte n'est pas un membre d'organisation",
        ) from exc
    except NotOrgMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé pour cette organisation",
        ) from exc

    items, total = _subscriptions.list_active_subscribers_page(
        str(organization_id),
        limit=limit,
        offset=offset,
    )

    return MemberSubscribersPage(
        items=[MemberSubscriberItem.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )
