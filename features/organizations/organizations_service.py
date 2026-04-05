"""
Création atomique : compte Auth + `public.users` (member) + `organizations`.
La ligne `members` pour le créateur est ajoutée par le trigger SQL.
"""

from typing import Any, Dict, Optional

from supabase import Client

from config.supabase_client import supabase_admin


class OrganizationsService:
    def __init__(self) -> None:
        self.db: Client = supabase_admin

    @staticmethod
    def _generated_username(user_id: str) -> str:
        compact = user_id.replace("-", "")
        return f"mem_{compact[:16]}"

    @staticmethod
    def _auth_error_message(exc: Exception) -> str:
        msg = str(exc).strip().lower()
        if "already" in msg or "registered" in msg or "exists" in msg:
            return "Un compte existe déjà avec cet e-mail"
        return "Création du compte impossible (e-mail ou mot de passe invalide)"

    def register_member_with_organization(
        self,
        organization_name: str,
        organization_category: str,
        organization_description: Optional[str],
        email: str,
        password: str,
    ) -> Dict[str, Any]:
        email_norm = email.strip().lower()
        name_clean = organization_name.strip()
        desc_clean = (
            organization_description.strip()
            if organization_description and organization_description.strip()
            else None
        )

        user_id: Optional[str] = None

        try:
            auth_res = self.db.auth.admin.create_user(
                {
                    "email": email_norm,
                    "password": password,
                    "email_confirm": True,
                }
            )
        except Exception as exc:
            raise ValueError(self._auth_error_message(exc)) from exc

        if not auth_res.user or not auth_res.user.id:
            raise ValueError("Réponse Auth invalide après création utilisateur")

        user_id = str(auth_res.user.id)
        username = self._generated_username(user_id)

        user_payload = {
            "id": user_id,
            "email": email_norm,
            "username": username,
            "user_type": "member",
            "first_name": None,
            "last_name": None,
        }

        try:
            ures = self.db.table("users").insert(user_payload).execute()
            if not ures.data:
                raise ValueError("Insertion profil utilisateur refusée")
        except Exception as exc:
            try:
                self.db.auth.admin.delete_user(user_id)
            except Exception:
                pass
            err = str(exc).lower()
            if "duplicate" in err or "23505" in err or "unique" in err:
                raise ValueError(
                    "E-mail ou nom d'utilisateur déjà utilisé"
                ) from exc
            raise ValueError("Impossible de créer le profil utilisateur") from exc

        org_payload = {
            "name": name_clean,
            "org_type": organization_category,
            "description": desc_clean,
            "created_by": user_id,
        }

        try:
            ores = self.db.table("organizations").insert(org_payload).execute()
            rows = ores.data or []
            if not rows:
                raise ValueError("Insertion organisation refusée")
            org_id = rows[0]["id"]
        except Exception as exc:
            try:
                self.db.table("users").delete().eq("id", user_id).execute()
            except Exception:
                pass
            try:
                self.db.auth.admin.delete_user(user_id)
            except Exception:
                pass
            err = str(exc).lower()
            if "duplicate" in err or "23505" in err or "unique" in err:
                raise ValueError("Conflit de données pour l'organisation") from exc
            raise ValueError("Impossible de créer l'organisation") from exc

        return {
            "success": True,
            "message": "Compte membre et organisation créés. Vous pouvez vous connecter.",
            "user_id": user_id,
            "username": username,
            "organization_id": org_id,
        }
