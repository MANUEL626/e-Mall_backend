"""
Service d'authentification : bootstrap profil customer après OTP Supabase (téléphone).
"""

import logging
import re
from typing import Any, Dict, Optional

import jwt
import requests
from supabase import Client

from config.supabase_client import (
    SUPABASE_ANON_KEY,
    SUPABASE_JWT_SECRET,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    supabase_admin,
)
from features.customers.customer_i18n import CustomerI18nService, translate_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AuthService:
    """Service minimal pour le flux customer (téléphone + JWT)."""

    def __init__(self) -> None:
        self.supabase: Client = supabase_admin
        self.supabase_url = SUPABASE_URL
        self.service_role_key = SUPABASE_SERVICE_KEY
        self._i18n = CustomerI18nService()

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

    @staticmethod
    def _user_from_verified_jwt(token: str) -> Dict[str, Any]:
        """Décode et vérifie le JWT (HS256) — pas d’appel réseau à GoTrue."""
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
                leeway=30,
            )
        except jwt.ExpiredSignatureError:
            raise ValueError("Token invalide ou expiré") from None
        except jwt.InvalidTokenError:
            raise ValueError("Token invalide ou expiré") from None
        sub = payload.get("sub")
        if not sub:
            raise ValueError("Utilisateur introuvable dans le token")
        return {
            "id": str(sub),
            "email": payload.get("email"),
            "phone": payload.get("phone"),
        }

    def _user_from_gotrue_http(self, token: str) -> Dict[str, Any]:
        """Secours si aucun JWT secret configuré (non recommandé en prod)."""
        try:
            response = requests.get(
                f"{self.supabase_url}/auth/v1/user",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {token}",
                },
                timeout=15,
            )
        except requests.exceptions.RequestException as exc:
            raise ValueError(
                "Impossible de joindre Supabase Auth (réseau ou SSL). "
                "Configurez SUPABASE_JWT_SECRET dans .env pour valider le JWT sans appel HTTP "
                "(Supabase Dashboard → Project Settings → API → JWT Secret ; "
                "en local CLI : super-secret-jwt-token-with-at-least-32-characters-long)."
            ) from exc
        if response.status_code != 200:
            raise ValueError("Token invalide ou expiré")
        body = response.json() or {}
        if not body.get("id"):
            raise ValueError("Utilisateur introuvable dans le token")
        return body

    def _extract_auth_user_from_access_token(self, access_token: str) -> Dict[str, Any]:
        token = (access_token or "").replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Token utilisateur manquant")
        if SUPABASE_JWT_SECRET:
            return self._user_from_verified_jwt(token)
        return self._user_from_gotrue_http(token)

    def get_auth_user_from_access_token(self, access_token: str) -> Dict[str, Any]:
        """Payload utilisateur GoTrue (`GET /auth/v1/user`) à partir du JWT Supabase."""
        return self._extract_auth_user_from_access_token(access_token)

    def get_user_id_from_access_token(self, access_token: str) -> str:
        """Identifiant `auth.users` / `public.users` à partir du JWT Supabase."""
        payload = self.get_auth_user_from_access_token(access_token)
        return str(payload["id"])

    def _safe_default_username(self, phone: Optional[str], user_id: str) -> str:
        if phone:
            digits = re.sub(r"\D", "", phone)
            suffix = digits[-8:] if digits else user_id.replace("-", "")[:8]
        else:
            suffix = user_id.replace("-", "")[:8]
        return f"cust_{suffix}"

    def _ensure_customer_params(self, user_id: str) -> None:
        """
        CrÃ©e les paramÃ¨tres customer dÃ¨s le bootstrap.
        `country` et `interests` restent dans extra pour garder la table extensible.
        """
        cres = (
            self.supabase.table("customers")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        crows = cres.data or []
        if not crows:
            raise ValueError("Profil customer introuvable aprÃ¨s bootstrap")
        customer_id = str(crows[0]["id"])

        existing = (
            self.supabase.table("customer_params")
            .select("customer_id")
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            return

        self.supabase.table("customer_params").insert(
            {
                "customer_id": customer_id,
                "locale": "fr",
                "extra": {"country": None, "interests": []},
            }
        ).execute()

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
        self._ensure_customer_params(user_id)

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
        locale = self._i18n.locale_for_user_id(user_id)
        message = (
            "Compte customer créé, finalisez votre profil."
            if is_new_customer
            else "Connexion customer réussie."
        )
        return {
            "success": True,
            "message": translate_message(message, locale),
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
        locale = self._i18n.locale_for_user_id(user_id)
        return {
            "success": True,
            "message": translate_message("Connexion customer réussie.", locale),
            "user_id": user_id,
            "is_new_customer": False,
            "profile_complete": profile_complete,
            "username": u.get("username") or "",
            "prenom": u.get("first_name"),
            "nom": u.get("last_name"),
            "profilepicture": u.get("profile_picture"),
            "mail": u.get("email"),
        }
