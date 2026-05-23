"""
Création atomique : compte Auth + `public.users` (member) + `organizations`.
La ligne `members` pour le créateur est ajoutée par le trigger SQL.
Invitation d’un membre : invite GoTrue ou rattachement d’un compte existant + e-mail de récupération si besoin.
"""

from typing import Any, Dict, List, Optional, Union

import requests
from supabase import Client

from config.supabase_client import SUPABASE_ANON_KEY, SUPABASE_URL, supabase_admin


class OrganizationInviteForbidden(Exception):
    """L’inviteur n’est pas admin/supervisor actif de l’organisation."""


class OrganizationNotFound(Exception):
    """Aucune organisation avec cet identifiant."""


class OrganizationMemberNotFound(Exception):
    """Aucune ligne `members` pour cet id dans cette organisation."""


class OrganizationsService:
    def __init__(self) -> None:
        self.db: Client = supabase_admin

    @staticmethod
    def _generated_username(user_id: str) -> str:
        compact = user_id.replace("-", "")
        return f"mem_{compact[:16]}"

    @staticmethod
    def _normalize_countries(countries: Optional[List[str]]) -> List[str]:
        out: List[str] = []
        for item in countries or []:
            code = str(item).strip().upper()
            if not code:
                continue
            if len(code) != 2 or not code.isalpha():
                raise ValueError("Les pays doivent utiliser le format ISO alpha-2, ex: TG, NG")
            if code not in out:
                out.append(code)
        return out

    @staticmethod
    def _normalize_locale(locale: Optional[str]) -> str:
        value = (locale or "fr").strip().lower()
        if value not in {"fr", "en", "de", "zh"}:
            raise ValueError("La langue doit etre fr, en, de ou zh")
        return value

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
        organization_profile_picture: Optional[str] = None,
        organization_countries: Optional[List[str]] = None,
        member_first_name: Optional[str] = None,
        member_last_name: Optional[str] = None,
        member_username: Optional[str] = None,
        member_profile_picture: Optional[str] = None,
        member_locale: Optional[str] = "fr",
    ) -> Dict[str, Any]:
        email_norm = email.strip().lower()
        name_clean = organization_name.strip()
        desc_clean = (
            organization_description.strip()
            if organization_description and organization_description.strip()
            else None
        )
        org_picture = (
            organization_profile_picture.strip()
            if organization_profile_picture and organization_profile_picture.strip()
            else None
        )
        org_countries = self._normalize_countries(organization_countries)
        locale = self._normalize_locale(member_locale)

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
        username = (member_username or "").strip() or self._generated_username(user_id)
        first_name = (
            member_first_name.strip()
            if member_first_name and member_first_name.strip()
            else None
        )
        last_name = (
            member_last_name.strip()
            if member_last_name and member_last_name.strip()
            else None
        )
        member_picture = (
            member_profile_picture.strip()
            if member_profile_picture and member_profile_picture.strip()
            else None
        )

        user_payload = {
            "id": user_id,
            "email": email_norm,
            "username": username,
            "user_type": "member",
            "first_name": first_name,
            "last_name": last_name,
            "profile_picture": member_picture,
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
            "profile_picture": org_picture,
            "countries": org_countries,
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

        try:
            self.db.table("member_params").insert(
                {"user_id": user_id, "locale": locale, "extra": {}}
            ).execute()
        except Exception:
            pass

        return {
            "success": True,
            "message": "Compte membre et organisation créés. Vous pouvez vous connecter.",
            "user_id": user_id,
            "username": username,
            "organization_id": org_id,
            "organization_profile_picture": org_picture,
            "organization_countries": org_countries,
            "member_profile_picture": member_picture,
            "member_locale": locale,
        }

    def _ensure_org_and_inviter(
        self, organization_id: str, inviter_user_id: str
    ) -> Dict[str, Any]:
        ores = (
            self.db.table("organizations")
            .select("id,org_type")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        orows = ores.data or []
        if not orows:
            raise OrganizationNotFound()
        mres = (
            self.db.table("members")
            .select("member_type")
            .eq("user_id", inviter_user_id)
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        mrows = mres.data or []
        if not mrows:
            raise OrganizationInviteForbidden()
        if mrows[0].get("member_type") not in ("admin", "supervisor"):
            raise OrganizationInviteForbidden()
        return orows[0]

    @staticmethod
    def _default_member_role_for_org(org_type: str) -> str:
        return (
            "delivery_management"
            if org_type == "delivery"
            else "sales_management"
        )

    def _find_auth_user_id_by_email(self, email_norm: str) -> Optional[str]:
        page = 1
        per_page = 200
        while page <= 50:
            raw: Any = self.db.auth.admin.list_users(page=page, per_page=per_page)
            users: Union[List[Any], None] = getattr(raw, "users", None)
            if users is None and isinstance(raw, dict):
                users = raw.get("users")
            if users is None:
                users = raw if isinstance(raw, list) else []
            if not users:
                return None
            for u in users:
                em = getattr(u, "email", None)
                if em is None and isinstance(u, dict):
                    em = u.get("email")
                uid = getattr(u, "id", None)
                if uid is None and isinstance(u, dict):
                    uid = u.get("id")
                if em and str(em).strip().lower() == email_norm and uid:
                    return str(uid)
            if len(users) < per_page:
                break
            page += 1
        return None

    def _send_recovery_email(
        self, email_norm: str, redirect_to: Optional[str]
    ) -> None:
        payload: Dict[str, Any] = {"email": email_norm}
        if redirect_to and redirect_to.strip():
            payload["redirect_to"] = redirect_to.strip()
        try:
            requests.post(
                f"{SUPABASE_URL}/auth/v1/recover",
                json=payload,
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json",
                },
                timeout=20,
            )
        except Exception:
            pass

    def _is_already_member(self, user_id: str, organization_id: str) -> bool:
        r = (
            self.db.table("members")
            .select("id")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        return bool(r.data)

    def invite_member_to_organization(
        self,
        organization_id: str,
        inviter_user_id: str,
        email: str,
        redirect_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        email_norm = email.strip().lower()
        org = self._ensure_org_and_inviter(organization_id, inviter_user_id)
        member_role = self._default_member_role_for_org(str(org.get("org_type", "sales")))

        invite_options: Optional[Dict[str, Any]] = None
        if redirect_to and redirect_to.strip():
            invite_options = {"redirect_to": redirect_to.strip()}

        invited_user_id: Optional[str] = None
        invite_sent = False

        try:
            if invite_options:
                inv = self.db.auth.admin.invite_user_by_email(
                    email_norm,
                    options=invite_options,
                )
            else:
                inv = self.db.auth.admin.invite_user_by_email(email_norm)
            if inv.user and inv.user.id:
                invited_user_id = str(inv.user.id)
                invite_sent = True
        except Exception as exc:
            err_l = str(exc).lower()
            if (
                "already" not in err_l
                and "registered" not in err_l
                and "exists" not in err_l
                and "duplicate" not in err_l
                and "déjà" not in err_l
            ):
                raise ValueError(
                    "Invitation impossible : e-mail invalide ou service d'authentification indisponible"
                ) from exc

        if not invited_user_id:
            invited_user_id = self._find_auth_user_id_by_email(email_norm)
            if not invited_user_id:
                raise ValueError(
                    "Impossible de résoudre le compte pour cet e-mail après l’invitation"
                )

        if self._is_already_member(invited_user_id, organization_id):
            raise ValueError("Cet utilisateur est déjà membre de cette organisation")

        ures = (
            self.db.table("users")
            .select("id,user_type,email,username")
            .eq("id", invited_user_id)
            .limit(1)
            .execute()
        )
        urows = ures.data or []
        username = self._generated_username(invited_user_id)

        if not urows:
            user_payload = {
                "id": invited_user_id,
                "email": email_norm,
                "username": username,
                "user_type": "member",
                "first_name": None,
                "last_name": None,
            }
            try:
                ins = self.db.table("users").insert(user_payload).execute()
                if not ins.data:
                    raise ValueError("Création du profil utilisateur refusée")
            except Exception as exc:
                if invite_sent:
                    try:
                        self.db.auth.admin.delete_user(invited_user_id)
                    except Exception:
                        pass
                err_l = str(exc).lower()
                if "duplicate" in err_l or "23505" in err_l:
                    raise ValueError(
                        "Conflit de données (e-mail ou nom d’utilisateur déjà utilisé)"
                    ) from exc
                raise ValueError("Impossible de créer le profil utilisateur") from exc
        else:
            ut = urows[0].get("user_type")
            if ut not in ("member",):
                raise ValueError(
                    "Ce compte est associé à un autre type d’utilisateur ; "
                    "impossible de l’ajouter comme membre d’organisation depuis cet endpoint."
                )

        try:
            mins = (
                self.db.table("members")
                .insert(
                    {
                        "user_id": invited_user_id,
                        "organization_id": organization_id,
                        "member_type": "member",
                        "member_role": member_role,
                    }
                )
                .execute()
            )
            if not mins.data:
                raise ValueError("Ajout du membre refusé")
        except Exception as exc:
            err_l = str(exc).lower()
            if "duplicate" in err_l or "23505" in err_l:
                raise ValueError(
                    "Cet utilisateur est déjà membre de cette organisation"
                ) from exc
            if invite_sent:
                try:
                    self.db.table("users").delete().eq("id", invited_user_id).execute()
                except Exception:
                    pass
                try:
                    self.db.auth.admin.delete_user(invited_user_id)
                except Exception:
                    pass
            raise ValueError("Impossible d’ajouter le membre à l’organisation") from exc

        try:
            self.db.table("member_params").insert(
                {"user_id": invited_user_id, "locale": "fr", "extra": {}}
            ).execute()
        except Exception:
            pass

        if invite_sent:
            msg = (
                "Une invitation a été envoyée à cette adresse. "
                "Le membre pourra définir son mot de passe lors de la première connexion."
            )
        else:
            self._send_recovery_email(email_norm, redirect_to)
            msg = (
                "Le compte a été ajouté à l’organisation. "
                "Un e-mail de connexion (définition ou réinitialisation du mot de passe) a été envoyé."
            )

        return {
            "success": True,
            "message": msg,
            "user_id": invited_user_id,
            "email": email_norm,
            "organization_id": organization_id,
        }

    def _count_active_admins_excluding(
        self, organization_id: str, exclude_member_id: Optional[str] = None
    ) -> int:
        r = (
            self.db.table("members")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("member_type", "admin")
            .eq("activity_status", True)
            .execute()
        )
        rows = r.data or []
        if exclude_member_id:
            rows = [x for x in rows if str(x["id"]) != exclude_member_id]
        return len(rows)

    def list_organization_members(
        self, organization_id: str, actor_user_id: str
    ) -> Dict[str, Any]:
        self._ensure_org_and_inviter(organization_id, actor_user_id)
        mres = (
            self.db.table("members")
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=False)
            .execute()
        )
        rows = mres.data or []
        user_ids = list({str(r["user_id"]) for r in rows})
        users_by_id: Dict[str, Dict[str, Any]] = {}
        if user_ids:
            ures = self.db.table("users").select("*").in_("id", user_ids).execute()
            for u in ures.data or []:
                users_by_id[str(u["id"])] = u
        members_out: List[Dict[str, Any]] = []
        for r in rows:
            uid = str(r["user_id"])
            u = users_by_id.get(uid, {})
            members_out.append({**r, "user": u})
        return {"members": members_out}

    def update_organization_profile(
        self,
        organization_id: str,
        actor_user_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        profile_picture: Optional[str] = None,
        countries: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        self._ensure_org_and_inviter(organization_id, actor_user_id)
        updates: Dict[str, Any] = {}

        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("name ne peut pas etre vide")
            updates["name"] = clean_name

        if description is not None:
            updates["description"] = description.strip() or None

        if profile_picture is not None:
            updates["profile_picture"] = profile_picture.strip() or None

        if countries is not None:
            updates["countries"] = self._normalize_countries(countries)

        if not updates:
            raise ValueError(
                "Au moins un parmi name, description, profile_picture, countries est requis"
            )

        try:
            res = (
                self.db.table("organizations")
                .update(updates)
                .eq("id", organization_id)
                .execute()
            )
        except Exception as exc:
            err_l = str(exc).lower()
            if "duplicate" in err_l or "23505" in err_l or "unique" in err_l:
                raise ValueError("Conflit de donnees pour l'organisation") from exc
            raise ValueError("Impossible de mettre a jour l'organisation") from exc

        rows = res.data or []
        if rows:
            return rows[0]

        ref = (
            self.db.table("organizations")
            .select("*")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        r2 = ref.data or []
        if not r2:
            raise OrganizationNotFound()
        return r2[0]

    def update_organization_member(
        self,
        organization_id: str,
        member_id: str,
        actor_user_id: str,
        activity_status: Optional[bool] = None,
        member_type: Optional[str] = None,
        member_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_org_and_inviter(organization_id, actor_user_id)
        pres = (
            self.db.table("members")
            .select("*")
            .eq("id", member_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        prow = pres.data or []
        if not prow:
            raise OrganizationMemberNotFound()
        current = prow[0]

        effective_active = (
            activity_status
            if activity_status is not None
            else current.get("activity_status")
        )
        effective_type = (
            member_type
            if member_type is not None
            else current.get("member_type")
        )

        if (
            current.get("member_type") == "admin"
            and current.get("activity_status") is True
        ):
            losing_admin = effective_active is False or effective_type != "admin"
            if losing_admin:
                others = self._count_active_admins_excluding(
                    organization_id, exclude_member_id=str(current["id"])
                )
                if others < 1:
                    raise ValueError(
                        "Impossible de retirer le dernier administrateur actif de l'organisation"
                    )

        updates: Dict[str, Any] = {}
        if activity_status is not None:
            updates["activity_status"] = activity_status
        if member_type is not None:
            updates["member_type"] = member_type
        if member_role is not None:
            updates["member_role"] = member_role

        ures = (
            self.db.table("members")
            .update(updates)
            .eq("id", member_id)
            .eq("organization_id", organization_id)
            .execute()
        )
        urows = ures.data or []
        updated = urows[0] if urows else None
        if not updated:
            ref = (
                self.db.table("members")
                .select("*")
                .eq("id", member_id)
                .eq("organization_id", organization_id)
                .limit(1)
                .execute()
            )
            r2 = ref.data or []
            if not r2:
                raise OrganizationMemberNotFound()
            updated = r2[0]

        uid = str(updated["user_id"])
        ufetch = (
            self.db.table("users").select("*").eq("id", uid).limit(1).execute()
        )
        urow = (ufetch.data or [{}])[0]
        return {**updated, "user": urow}
