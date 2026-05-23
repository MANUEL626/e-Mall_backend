"""
Routes FastAPI pour l'authentification customer (OTP téléphone + bootstrap).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_models import (
    CustomerBootstrapRequest,
    CustomerBootstrapResponse,
    CustomerProfileUpdateRequest,
)
from features.auth.auth_service import AuthService
from features.customers.customer_i18n import CustomerI18nService, translate_message

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

auth_service = AuthService()
_i18n = CustomerI18nService()
security = HTTPBearer()


def _locale_from_token(access_token: str) -> str:
    try:
        user_id = auth_service.get_user_id_from_access_token(access_token)
        return _i18n.locale_for_user_id(user_id)
    except Exception:
        return "fr"


def _localized_detail(message: str, access_token: str) -> str:
    return translate_message(message, _locale_from_token(access_token))


@router.post("/customer/bootstrap", response_model=CustomerBootstrapResponse)
async def bootstrap_customer_after_phone_login(
    body: CustomerBootstrapRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Bootstrap customer après vérification OTP téléphone.
    Reçoit le JWT utilisateur Supabase (Authorization: Bearer <access_token>).
    """
    try:
        result = auth_service.bootstrap_customer_from_token(
            access_token=credentials.credentials,
            first_name=body.first_name,
            last_name=body.last_name,
            username=body.username,
        )
        return CustomerBootstrapResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_localized_detail(str(exc), credentials.credentials),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du bootstrap customer: {str(exc)}",
        )


@router.patch("/customer/profile", response_model=CustomerBootstrapResponse)
async def update_customer_profile(
    body: CustomerProfileUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Met à jour le profil `public.users` du customer connecté (JWT).

    Champs optionnels : seuls ceux fournis dans le corps sont modifiés.
    Au moins un champ doit être envoyé.
    """
    try:
        result = auth_service.update_customer_profile_from_token(
            access_token=credentials.credentials,
            username=body.username,
            prenom=body.prenom,
            nom=body.nom,
            mail=body.mail,
            profilepicture=body.profilepicture,
        )
        return CustomerBootstrapResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_localized_detail(str(exc), credentials.credentials),
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_localized_detail(str(exc), credentials.credentials),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour du profil: {str(exc)}",
        )
