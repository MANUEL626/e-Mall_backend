from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from typing import Any, Dict, List

from config.supabase_client import get_supabase_client_with_token

security = HTTPBearer()

router = APIRouter(prefix="/api/v1/customers", tags=["Player"])


class UpdatePlayerRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)


@router.get("/", response_model=List[Dict[str, Any]])
def list_players(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Liste les entrées de `public.customers`.
    La visibilité est gérée par les RLS.
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("customers").select("*").execute()
    return res.data or []


@router.get("/me", response_model=Dict[str, Any])
def get_my_player_profile(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Retourne l'entrée `customers` correspondant à l'utilisateur connecté (si player).
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("customers").select("*").limit(1).execute()
    data = res.data or []
    if not data:
        raise HTTPException(status_code=404, detail="Profil player introuvable")
    return data[0]


@router.patch("/me", response_model=Dict[str, Any])
def update_my_player_profile(
    body: UpdatePlayerRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Met à jour le `username` du joueur connecté.
    RLS: l'utilisateur peut mettre à jour uniquement sa propre ligne.
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("customers").update({"username": body.username}).execute()
    data = res.data or []
    if not data:
        raise HTTPException(status_code=403, detail="Action non autorisée")
    return data[0]
