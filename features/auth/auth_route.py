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

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

auth_service = AuthService()
security = HTTPBearer()


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour du profil: {str(exc)}",
        )
