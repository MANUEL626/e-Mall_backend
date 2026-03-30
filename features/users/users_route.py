from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Any, Dict, List, Optional
from uuid import UUID

from config.supabase_client import get_supabase_client_with_token, supabase_admin
from features.auth.internal_bearer import require_internal_bearer
from features.users.users_model import (
    UpdateUserRequest,
    UserProfileAggregatedResponse,
    UpdateUserParamsRequest,
    UserParamsResponse,
    UserType,
)

security = HTTPBearer()

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get("/", response_model=List[Dict[str, Any]])
def get_all_users(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Retourne la liste des profils `public.users`.
    Le filtre est appliqué par les RLS (admins = tout, utilisateurs = soi-même).
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = client.table("users").select("*").order("created_at", desc=True).execute()
    return res.data or []


@router.get("/get_by_id/{user_id}", response_model=Dict[str, Any])
def get_user_by_id(user_id: UUID, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Retourne un utilisateur par son `id`.
    La visibilité est gérée par les RLS.
    """
    client = get_supabase_client_with_token(credentials.credentials)
    res = (
        client.table("users")
        .select("*")
        .eq("id", str(user_id))
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    return rows[0]


def _fetch_aggregate_profile(client, user_id: UUID) -> Optional[Dict[str, Any]]:
    """Assemble users + customers ou admins (bypass RLS via service role si nécessaire)."""
    ures = (
        client.table("users")
        .select("*")
        .eq("id", str(user_id))
        .limit(1)
        .execute()
    )
    rows = ures.data or []
    if not rows:
        return None
    user = rows[0]

    uid = str(user_id)
    utype = user.get("user_type")
    player_id = None
    username = None
    admin_id = None

    upres = (
        client.table("user_params")
        .select("is_params_done")
        .eq("user_id", uid)
        .limit(1)
        .execute()
    )
    up_rows = upres.data or []
    is_params_done = (up_rows[0].get("is_params_done") if up_rows else False)

    if utype == UserType.player.value:
        pres = (
            client.table("customers")
            .select("id,username")
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )
        row = (pres.data or [None])[0]
        if row:
            player_id = row.get("id")
            username = row.get("username")
    elif utype in (UserType.admin.value, UserType.super_admin.value):
        ares = (
            client.table("admins")
            .select("id")
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )
        row = (ares.data or [None])[0]
        if row:
            admin_id = row.get("id")

    return {
        "user_id": user["id"],
        "email": user["email"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "phone": user.get("phone"),
        "user_type": user["user_type"],
        "activity_status": user["activity_status"],
        "profile_picture": user.get("profile_picture"),
        "created_at": user["created_at"],
        "is_params_done": is_params_done,
        "player_id": player_id,
        "username": username,
        "admin_id": admin_id,
    }


@router.patch("/{user_id}", response_model=UserProfileAggregatedResponse)
def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    _: None = Depends(require_internal_bearer),
):
    """
    Met à jour un utilisateur (admin / player).

    Champs possibles dans le body :
    - `email`, `firstname`, `lastname`, `phone`, `activitystatus`, `profilepicture`
    - `username` uniquement si `user_type = player`

    Auth : `Authorization: Bearer <INTERNAL_API_BEARER>` (secret interne partagé app ↔ API).
    """
    # 1) Charger le user_type pour savoir où appliquer `username`
    user_row = (
        supabase_admin.table("users")
        .select("id,user_type")
        .eq("id", str(user_id))
        .limit(1)
        .execute()
    )
    urows = user_row.data or []
    if not urows:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    utype = urows[0].get("user_type")
    uid = str(user_id)

    updates_users: Dict[str, Any] = {}
    if body.email is not None:
        updates_users["email"] = body.email
    if body.first_name is not None:
        updates_users["first_name"] = body.first_name
    if body.last_name is not None:
        updates_users["last_name"] = body.last_name
    if body.phone is not None:
        updates_users["phone"] = body.phone
    if body.activity_status is not None:
        updates_users["activity_status"] = body.activity_status
    if body.profile_picture is not None:
        updates_users["profile_picture"] = body.profile_picture

    updates_player: Optional[Dict[str, Any]] = None
    if body.username is not None:
        if utype != UserType.player.value:
            raise HTTPException(status_code=400, detail="`username` n'est autorisé que pour les customers")
        updates_player = {"username": body.username}

    try:
        # 2) Update table users
        if updates_users:
            _ = (
                supabase_admin.table("users")
                .update(updates_users)
                .eq("id", uid)
                .execute()
            )

        # 3) Update table customers si applicable
        if updates_player is not None:
            pres = (
                supabase_admin.table("customers")
                .update(updates_player)
                .eq("user_id", uid)
                .execute()
            )
            if not (pres.data or []):
                raise HTTPException(status_code=404, detail="Profil player introuvable")
    except HTTPException:
        raise
    except Exception as e:
        # Ex: conflit unique sur email/username
        raise HTTPException(status_code=400, detail=str(e))

    # 4) Retourner le profil agrégé après update
    payload = _fetch_aggregate_profile(supabase_admin, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    return UserProfileAggregatedResponse.model_validate(payload)


@router.patch("/{user_id}/params", response_model=UserParamsResponse)
def update_user_params(
    user_id: UUID,
    body: UpdateUserParamsRequest,
    _: None = Depends(require_internal_bearer),
):
    """
    Met à jour les paramètres applicatifs de l'utilisateur.

    Champs body optionnels :
    - `country`
    - `language_setting`
    - `notification`
    - `theme` (light/dark)
    - `is_params_done`

    Auth : `Authorization: Bearer <INTERNAL_API_BEARER>` (secret interne partagé).
    """
    uid = str(user_id)

    # 1) Chercher si la ligne user_params existe
    existing = (
        supabase_admin.table("user_params")
        .select("*")
        .eq("user_id", uid)
        .limit(1)
        .execute()
    )
    rows = existing.data or []
    exists = bool(rows)

    # 2) Construire les updates (update partiel)
    updates: Dict[str, Any] = {}
    if body.country is not None:
        updates["country"] = body.country
    if body.language_setting is not None:
        updates["language_setting"] = body.language_setting
    if body.notification is not None:
        updates["notification"] = body.notification
    if body.theme is not None:
        # pydantic enum -> valeur string ('light'/'dark')
        updates["theme"] = body.theme.value if hasattr(body.theme, "value") else body.theme
    if body.is_params_done is not None:
        updates["is_params_done"] = body.is_params_done

    try:
        if not exists:
            # user_params a des champs NOT NULL : on exige ceux nécessaires lors de la création.
            required_missing = []
            for col in ("country", "language_setting", "theme"):
                if col not in updates:
                    required_missing.append(col)
            if required_missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Champs requis pour créer user_params: {', '.join(required_missing)}",
                )

            new_row = (
                supabase_admin.table("user_params")
                .insert(
                    {
                        "user_id": uid,
                        **updates,
                    }
                )
                .execute()
            )
            created_rows = new_row.data or []
            if not created_rows:
                raise HTTPException(status_code=500, detail="Échec création user_params")
            return UserParamsResponse.model_validate(created_rows[0])

        # update si existe
        if updates:
            _ = (
                supabase_admin.table("user_params")
                .update(updates)
                .eq("user_id", uid)
                .execute()
            )

        # 3) Renvoyer la ligne à jour
        updated = (
            supabase_admin.table("user_params")
            .select("*")
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )
        up_rows = updated.data or []
        if not up_rows:
            raise HTTPException(status_code=404, detail="user_params introuvable")
        return UserParamsResponse.model_validate(up_rows[0])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
