from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Any, Dict, List

from config.supabase_client import get_supabase_client_with_token

security = HTTPBearer()

router = APIRouter(prefix="/api/v1/admins", tags=["Admins"])


@router.get("/", response_model=List[Dict[str, Any]])
def list_admins(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Liste les entrées de `public.admins`.
    RLS: un admin voit tout, un non-admin ne voit que ses propres lignes (souvent aucune).
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("admins").select("*").execute()
    return res.data or []


@router.get("/me", response_model=Dict[str, Any])
def get_my_admin_profile(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Retourne l'entrée `admins` correspondant à l'utilisateur connecté (si admin).
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("admins").select("*").limit(1).execute()
    data = res.data or []
    if not data:
        raise HTTPException(status_code=404, detail="Vous n'êtes pas admin")
    return data[0]
