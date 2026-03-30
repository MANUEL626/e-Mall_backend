"""
Modèles Pydantic pour l'authentification customer (OTP téléphone).
"""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field
from uuid import UUID


class CustomerBootstrapRequest(BaseModel):
    """
    Données optionnelles pour la création initiale du profil customer.
    Le JWT utilisateur est transmis dans Authorization: Bearer <access_token>.
    """

    first_name: Optional[str] = Field(None, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)
    username: Optional[str] = Field(None, max_length=50)


class CustomerBootstrapResponse(BaseModel):
    """
    Réponse standard profil customer : bootstrap (POST) ou mise à jour (PATCH).
    Même forme JSON pour simplifier le client Flutter.
    """

    success: bool
    message: str
    user_id: UUID
    is_new_customer: bool
    profile_complete: bool
    username: str
    prenom: Optional[str] = None
    nom: Optional[str] = None
    profilepicture: Optional[str] = None
    mail: Optional[str] = None


class CustomerProfileUpdateRequest(BaseModel):
    """
    Mise à jour du profil customer (champs optionnels : seuls ceux envoyés sont modifiés).
    Auth : Authorization: Bearer <access_token>.
    """

    username: Optional[str] = Field(None, max_length=50)
    prenom: Optional[str] = Field(None, max_length=50)
    nom: Optional[str] = Field(None, max_length=50)
    mail: Optional[EmailStr] = None
    # Base64 ou data-URL : plusieurs Mo ; 2048 caractères suffisent seulement pour une URL courte.
    profilepicture: Optional[str] = Field(
        None,
        max_length=25_000_000,
        description="URL publique ou image encodée base64 / data:image/...;base64,...",
    )

