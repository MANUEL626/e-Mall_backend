"""
Vérification d’un Bearer « interne » (secret partagé app ↔ API), distinct du JWT Supabase.
"""

import secrets

from fastapi import Header, HTTPException, status

from config.supabase_client import INTERNAL_API_BEARER


def require_internal_bearer(
    authorization: str | None = Header(None, alias="Authorization"),
) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <token_interne> requis",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, INTERNAL_API_BEARER):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token interne invalide",
            headers={"WWW-Authenticate": "Bearer"},
        )
