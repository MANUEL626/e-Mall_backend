"""
Routes for organization subscription plans and entitlements.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.organization_subscriptions.organization_subscriptions_models import (
    OrganizationSubscriptionEntitlements,
    OrganizationSubscriptionOut,
    OrganizationSubscriptionPatch,
    OrganizationSubscriptionPlansResponse,
)
from features.organization_subscriptions.organization_subscriptions_service import (
    OrganizationSubscriptionForbidden,
    OrganizationSubscriptionNotFound,
    OrganizationSubscriptionService,
)

router = APIRouter(
    prefix="/api/v1/organization-subscriptions",
    tags=["Organization subscriptions"],
)

security = HTTPBearer()
_auth = AuthService()
_service = OrganizationSubscriptionService()


def _current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.get("/plans", response_model=OrganizationSubscriptionPlansResponse)
def list_subscription_plans(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Liste les plans actifs disponibles pour les organisations."""

    _current_user_id(credentials)
    return OrganizationSubscriptionPlansResponse(plans=_service.list_plans())


@router.get(
    "/organizations/{organization_id}",
    response_model=OrganizationSubscriptionOut,
)
def get_organization_subscription(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Retourne l'abonnement interne de l'organisation."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_subscription(user_id, str(organization_id))
        return OrganizationSubscriptionOut.model_validate(payload)
    except OrganizationSubscriptionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        ) from exc
    except OrganizationSubscriptionForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get(
    "/organizations/{organization_id}/entitlements",
    response_model=OrganizationSubscriptionEntitlements,
)
def get_organization_entitlements(
    organization_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Retourne les droits effectifs, limites et usages pour le front."""

    user_id = _current_user_id(credentials)
    try:
        payload = _service.get_entitlements(user_id, str(organization_id))
        return OrganizationSubscriptionEntitlements.model_validate(payload)
    except OrganizationSubscriptionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        ) from exc
    except OrganizationSubscriptionForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.patch(
    "/organizations/{organization_id}",
    response_model=OrganizationSubscriptionOut,
)
def update_organization_subscription(
    organization_id: UUID,
    body: OrganizationSubscriptionPatch,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Met a jour manuellement l'abonnement.

    Reserve a l'admin de l'organisation pour la phase interne/dev. Stripe
    alimentera les memes champs via webhook dans une prochaine etape.
    """

    user_id = _current_user_id(credentials)
    try:
        payload = _service.update_subscription(
            user_id,
            str(organization_id),
            body.model_dump(mode="json", exclude_unset=True),
        )
        return OrganizationSubscriptionOut.model_validate(payload)
    except OrganizationSubscriptionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        ) from exc
    except OrganizationSubscriptionForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

