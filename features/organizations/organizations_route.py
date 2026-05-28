"""
Inscription : utilisateur membre + organisation (créateur = premier admin member via trigger).
Invitation d’un membre sur une organisation existante (admin / supervisor).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.organizations.organizations_models import (
    InviteOrganizationMemberRequest,
    InviteOrganizationMemberResponse,
    OrganizationMemberItem,
    OrganizationMembersListResponse,
    RegisterMemberOrganizationRequest,
    RegisterMemberOrganizationResponse,
    UpdateOrganizationProfileRequest,
    UpdateOrganizationMemberRequest,
)
from features.organizations.organizations_service import (
    OrganizationInviteForbidden,
    OrganizationMemberNotFound,
    OrganizationNotFound,
    OrganizationsService,
)

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])

security = HTTPBearer()
_auth = AuthService()
_service = OrganizationsService()


@router.post(
    "/register-with-member",
    response_model=RegisterMemberOrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_member_and_organization(body: RegisterMemberOrganizationRequest):
    """
    Crée un compte Supabase (e-mail / mot de passe), un profil `public.users`
    (`user_type` = member, `username` généré), puis une organisation.
    Le trigger `trg_org_default_member` ajoute la ligne `members` pour le créateur.
    """
    try:
        result = _service.register_member_with_organization(
            organization_name=body.organization_name,
            organization_category=body.organization_category.value,
            organization_description=body.organization_description,
            organization_profile_picture=body.organization_profile_picture,
            organization_countries=body.organization_countries,
            organization_default_currencies=body.organization_default_currencies.model_dump(mode="json"),
            email=str(body.email),
            password=body.password,
            member_first_name=body.member_first_name,
            member_last_name=body.member_last_name,
            member_username=body.member_username,
            member_profile_picture=body.member_profile_picture,
            member_locale=body.member_locale,
        )
        return RegisterMemberOrganizationResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inscription impossible : {str(exc)}",
        ) from exc


@router.patch("/{organization_id}")
def update_organization_profile(
    organization_id: UUID,
    body: UpdateOrganizationProfileRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Met a jour la fiche organisation : nom, description, image de profil, pays.

    Auth : `Authorization: Bearer <access_token Supabase>`.
    L'appelant doit etre admin ou supervisor actif de l'organisation.
    """
    try:
        actor_id = _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    try:
        return _service.update_organization_profile(
            organization_id=str(organization_id),
            actor_user_id=actor_id,
            name=body.name,
            description=body.description,
            profile_picture=body.profile_picture,
            countries=body.countries,
            default_currencies=(
                body.default_currencies.model_dump(mode="json")
                if body.default_currencies is not None
                else None
            ),
        )
    except OrganizationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        ) from exc
    except OrganizationInviteForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces refuse pour cette organisation",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post(
    "/{organization_id}/members/invite",
    response_model=InviteOrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member_to_existing_organization(
    organization_id: UUID,
    body: InviteOrganizationMemberRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Ajoute un membre à une organisation à partir de son **e-mail** seul.

    - **Nouveau compte** : envoi d’un e-mail d’invitation Supabase (définition du mot de passe à la première connexion).
    - **Compte déjà inscrit** : rattachement à l’org. + envoi d’un e-mail « récupération » pour définir / réinitialiser le mot de passe.

    L’appelant doit être **admin** ou **supervisor** actif de l’organisation.

    Auth : `Authorization: Bearer <access_token Supabase>`.
    """
    try:
        inviter_id = _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    try:
        result = _service.invite_member_to_organization(
            organization_id=str(organization_id),
            inviter_user_id=inviter_id,
            email=str(body.email),
            redirect_to=body.redirect_to,
        )
        return InviteOrganizationMemberResponse(**result)
    except OrganizationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        ) from exc
    except OrganizationInviteForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas inviter de membre pour cette organisation",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invitation impossible : {str(exc)}",
        ) from exc


@router.get(
    "/{organization_id}/members",
    response_model=OrganizationMembersListResponse,
)
def list_organization_members(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Liste les membres de l’organisation avec le profil utilisateur (`users`) pour chacun.

    Réservé aux membres **admin** ou **supervisor** actifs de l’organisation.

    Auth : `Authorization: Bearer <access_token Supabase>`.
    """
    try:
        actor_id = _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    try:
        data = _service.list_organization_members(
            organization_id=str(organization_id),
            actor_user_id=actor_id,
        )
        return OrganizationMembersListResponse(**data)
    except OrganizationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        ) from exc
    except OrganizationInviteForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé pour cette organisation",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{organization_id}/members/{member_id}",
    response_model=OrganizationMemberItem,
)
def update_organization_member(
    organization_id: UUID,
    member_id: UUID,
    body: UpdateOrganizationMemberRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Met à jour un membre : **activation** (`activity_status`), **type** (`member_type`),
    **rôle** (`member_role`). Au moins un champ doit être fourni.

    On ne peut pas désactiver ou rétrograder le **dernier administrateur actif**.

    Réservé aux membres **admin** ou **supervisor** actifs.

    Auth : `Authorization: Bearer <access_token Supabase>`.
    """
    try:
        actor_id = _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    try:
        row = _service.update_organization_member(
            organization_id=str(organization_id),
            member_id=str(member_id),
            actor_user_id=actor_id,
            activity_status=body.activity_status,
            member_type=body.member_type.value if body.member_type is not None else None,
            member_role=body.member_role.value if body.member_role is not None else None,
        )
        return OrganizationMemberItem(**row)
    except OrganizationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        ) from exc
    except OrganizationInviteForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé pour cette organisation",
        ) from exc
    except OrganizationMemberNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membre introuvable pour cette organisation",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
