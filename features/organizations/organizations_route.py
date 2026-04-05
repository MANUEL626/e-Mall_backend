"""
Inscription : utilisateur membre + organisation (créateur = premier admin member via trigger).
"""

from fastapi import APIRouter, HTTPException, status

from features.organizations.organizations_models import (
    RegisterMemberOrganizationRequest,
    RegisterMemberOrganizationResponse,
)
from features.organizations.organizations_service import OrganizationsService

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])

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
            email=str(body.email),
            password=body.password,
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
