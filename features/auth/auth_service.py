"""
Service d'authentification : bootstrap profil customer après OTP Supabase (téléphone).
"""

import logging
import re
from typing import Any, Dict, Optional

from supabase import Client

from config.supabase_client import (
    supabase_admin,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    SUPABASE_ANON_KEY,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AuthService:
    """Service minimal pour le flux customer (téléphone + JWT)."""

    def __init__(self) -> None:
        self.supabase: Client = supabase_admin
        self.supabase_url = SUPABASE_URL
        self.service_role_key = SUPABASE_SERVICE_KEY

        if not self.supabase_url or not self.service_role_key:
            raise ValueError(
                "SUPABASE_URL et SUPABASE_SERVICE_KEY doivent être définis "
                "dans les variables d'environnement"
            )

        logger.info("Service d'authentification initialisé")

    def _normalize_phone(self, phone: Optional[str]) -> Optional[str]:
        if not phone:
            return None
        raw = phone.strip().replace(" ", "").replace("-", "")
        if raw.startswith("00"):
            raw = f"+{raw[2:]}"
        return raw

    def _extract_auth_user_from_access_token(self, access_token: str) -> Dict[str, Any]:
        import requests

        token = (access_token or "").replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Token utilisateur manquant")

        response = requests.get(
            f"{self.supabase_url}/auth/v1/user",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {token}",
            },
            timeout=15,
        )
        if response.status_code != 200:
            raise ValueError("Token invalide ou expiré")

        payload = response.json() or {}
        if not payload.get("id"):
            raise ValueError("Utilisateur introuvable dans le token")
        return payload

    def _safe_default_username(self, phone: Optional[str], user_id: str) -> str:
        if phone:
            digits = re.sub(r"\D", "", phone)
            suffix = digits[-8:] if digits else user_id.replace("-", "")[:8]
        else:
            suffix = user_id.replace("-", "")[:8]
        return f"cust_{suffix}"

    def bootstrap_customer_from_token(
        self,
        access_token: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Find-or-create atomique de `users` + `customers` après OTP validé.
        Nécessite la fonction SQL RPC `bootstrap_customer_profile`.
        """
        auth_user = self._extract_auth_user_from_access_token(access_token)
        user_id = auth_user["id"]
        phone = self._normalize_phone(auth_user.get("phone"))
        email = auth_user.get("email")

        cleaned_first_name = (first_name or "").strip() or "Customer"
        cleaned_last_name = (last_name or "").strip() or "User"
        cleaned_username = (username or "").strip() or self._safe_default_username(phone, user_id)

        if not phone:
            raise ValueError("Le compte auth doit contenir un numéro de téléphone vérifié")

        rpc_payload = {
            "p_user_id": user_id,
            "p_phone": phone,
            "p_email": email,
            "p_first_name": cleaned_first_name,
            "p_last_name": cleaned_last_name,
            "p_username": cleaned_username,
        }
        result = self.supabase.rpc("bootstrap_customer_profile", rpc_payload).execute()
        row = (result.data or [None])[0]
        if not row:
            raise ValueError("Réponse invalide de bootstrap_customer_profile")

        is_new_customer = bool(row.get("is_new_customer"))
        profile_complete = bool(row.get("profile_complete"))

        ures = (
            self.supabase.table("users")
            .select("username,first_name,last_name,profile_picture,email")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        urows = ures.data or []
        if not urows:
            raise ValueError("Profil utilisateur introuvable après bootstrap")

        u = urows[0]
        return {
            "success": True,
            "message": (
                "Compte customer créé, finalisez votre profil."
                if is_new_customer
                else "Connexion customer réussie."
            ),
            "user_id": user_id,
            "is_new_customer": is_new_customer,
            "profile_complete": profile_complete,
            "username": u.get("username") or "",
            "prenom": u.get("first_name"),
            "nom": u.get("last_name"),
            "profilepicture": u.get("profile_picture"),
            "mail": u.get("email"),
        }

    @staticmethod
    def _compute_profile_complete(row: Dict[str, Any]) -> bool:
        """Aligné sur la logique SQL de bootstrap_customer_profile."""
        fn = row.get("first_name")
        ln = row.get("last_name")
        un = row.get("username") or ""
        if fn is None or ln is None or not un:
            return False
        if fn == "Customer" or ln == "User":
            return False
        if un.startswith("cust_"):
            return False
        return True

    def _ensure_customer_row(self, user_id: str) -> None:
        res = (
            self.supabase.table("customers")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not (res.data or []):
            raise PermissionError("Aucun profil customer pour ce compte")

    def update_customer_profile_from_token(
        self,
        access_token: str,
        username: Optional[str] = None,
        prenom: Optional[str] = None,
        nom: Optional[str] = None,
        mail: Optional[str] = None,
        profilepicture: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Met à jour public.users pour l'utilisateur du JWT (customer uniquement).
        """
        auth_user = self._extract_auth_user_from_access_token(access_token)
        user_id = str(auth_user["id"])

        self._ensure_customer_row(user_id)

        updates: Dict[str, Any] = {}
        if username is not None:
            u = username.strip()
            if not u:
                raise ValueError("username ne peut pas être vide")
            updates["username"] = u
        if prenom is not None:
            p = prenom.strip()
            if not p:
                raise ValueError("prenom ne peut pas être vide")
            updates["first_name"] = p
        if nom is not None:
            n = nom.strip()
            if not n:
                raise ValueError("nom ne peut pas être vide")
            updates["last_name"] = n
        if mail is not None:
            updates["email"] = str(mail).strip().lower() if mail else None
        if profilepicture is not None:
            pic = profilepicture.strip()
            updates["profile_picture"] = pic if pic else None

        if not updates:
            raise ValueError("Aucun champ à mettre à jour")

        try:
            ures = (
                self.supabase.table("users")
                .update(updates)
                .eq("id", user_id)
                .execute()
            )
        except Exception as exc:
            err = str(exc).lower()
            if "duplicate" in err or "23505" in str(exc) or "unique" in err:
                raise ValueError(
                    "Email ou nom d'utilisateur déjà utilisé par un autre compte"
                ) from exc
            raise

        rows = ures.data or []
        if not rows:
            refetch = (
                self.supabase.table("users")
                .select("username,first_name,last_name,profile_picture,email")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            r2 = refetch.data or []
            if not r2:
                raise ValueError("Mise à jour impossible (utilisateur introuvable)")
            u = r2[0]
        else:
            u = rows[0]
        profile_complete = self._compute_profile_complete(u)

        # Même contrat JSON que le bootstrap ; après PATCH, is_new_customer est toujours false.
        return {
            "success": True,
            "message": "Connexion customer réussie.",
            "user_id": user_id,
            "is_new_customer": False,
            "profile_complete": profile_complete,
            "username": u.get("username") or "",
            "prenom": u.get("first_name"),
            "nom": u.get("last_name"),
            "profilepicture": u.get("profile_picture"),
            "mail": u.get("email"),
        }
