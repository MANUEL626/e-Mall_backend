"""
Profil membre : `public.users` + `members` + `organizations`.
Lecture via service role après validation du JWT (l’id du token doit correspondre).
"""

from typing import Any, Dict, List, Optional

from supabase import Client

from config.supabase_client import supabase_admin


class ProfileNotFoundError(Exception):
    """Aucune ligne `public.users` pour l’id issu du token."""


class NotMemberError(Exception):
    """`user_type` différent de `member`."""


class NotOrgMemberError(Exception):
    """L’utilisateur n’est pas membre actif de l’organisation ciblée."""


_AUTH_SAFE_KEYS = (
    "id",
    "email",
    "phone",
    "confirmed_at",
    "email_confirmed_at",
    "last_sign_in_at",
    "created_at",
    "updated_at",
    "is_anonymous",
    "role",
)


class MembersService:
    def __init__(self) -> None:
        self.db: Client = supabase_admin

    @staticmethod
    def _public_auth_snapshot(go_true_user: Dict[str, Any]) -> Dict[str, Any]:
        return {k: go_true_user[k] for k in _AUTH_SAFE_KEYS if k in go_true_user}

    @staticmethod
    def _normalize_locale(locale: Optional[str]) -> str:
        value = (locale or "fr").strip().lower()
        if value not in {"fr", "en", "de", "zh"}:
            raise ValueError("locale doit etre fr, en, de ou zh")
        return value

    @staticmethod
    def _clean_required_text(value: Optional[str], field_name: str) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{field_name} ne peut pas etre vide")
        return cleaned

    def _get_member_user(self, user_id: str) -> Dict[str, Any]:
        ures = self.db.table("users").select("*").eq("id", user_id).limit(1).execute()
        rows = ures.data or []
        if not rows:
            raise ProfileNotFoundError()
        user = rows[0]
        if user.get("user_type") != "member":
            raise NotMemberError()
        return user

    def get_me(self, user_id: str, go_true_user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        user = self._get_member_user(user_id)

        mres = (
            self.db.table("members")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        member_rows: List[Dict[str, Any]] = list(mres.data or [])
        org_ids = list({str(m["organization_id"]) for m in member_rows if m.get("organization_id")})

        org_by_id: Dict[str, Dict[str, Any]] = {}
        if org_ids:
            ores = self.db.table("organizations").select("*").in_("id", org_ids).execute()
            for o in ores.data or []:
                org_by_id[str(o["id"])] = o

        memberships: List[Dict[str, Any]] = []
        for m in member_rows:
            oid = m.get("organization_id")
            entry = dict(m)
            entry["organization"] = org_by_id.get(str(oid)) if oid is not None else None
            memberships.append(entry)

        auth_snap = self._public_auth_snapshot(go_true_user) if go_true_user else None
        params = self.get_or_create_member_params(user_id)

        return {
            "user": user,
            "memberships": memberships,
            "auth": auth_snap,
            "params": params,
        }

    def update_my_profile(
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        profile_picture: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._get_member_user(user_id)
        payload: Dict[str, Any] = {}

        clean_first_name = self._clean_required_text(first_name, "first_name")
        if clean_first_name is not None:
            payload["first_name"] = clean_first_name

        clean_last_name = self._clean_required_text(last_name, "last_name")
        if clean_last_name is not None:
            payload["last_name"] = clean_last_name

        clean_username = self._clean_required_text(username, "username")
        if clean_username is not None:
            payload["username"] = clean_username

        if profile_picture is not None:
            stripped = profile_picture.strip()
            payload["profile_picture"] = stripped or None

        if not payload:
            raise ValueError(
                "Au moins un parmi first_name, last_name, username, profile_picture est requis"
            )

        try:
            res = (
                self.db.table("users")
                .update(payload)
                .eq("id", user_id)
                .execute()
            )
        except Exception as exc:
            err_l = str(exc).lower()
            if "duplicate" in err_l or "23505" in err_l or "unique" in err_l:
                raise ValueError("E-mail ou nom d'utilisateur deja utilise") from exc
            raise ValueError("Impossible de mettre a jour le profil membre") from exc

        rows = res.data or []
        if not rows:
            return self._get_member_user(user_id)
        return rows[0]

    def get_or_create_member_params(self, user_id: str) -> Dict[str, Any]:
        self._get_member_user(user_id)
        res = (
            self.db.table("member_params")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]

        ins = (
            self.db.table("member_params")
            .insert({"user_id": user_id, "locale": "fr", "extra": {}})
            .execute()
        )
        inserted = ins.data or []
        if inserted:
            return inserted[0]

        res = (
            self.db.table("member_params")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]
        raise ValueError("Impossible de creer les parametres membre")

    def update_member_params(
        self,
        user_id: str,
        locale: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current = self.get_or_create_member_params(user_id)
        payload: Dict[str, Any] = {}

        if locale is not None:
            payload["locale"] = self._normalize_locale(locale)

        if extra is not None:
            merged = dict(current.get("extra") or {})
            merged.update(extra)
            payload["extra"] = merged

        if not payload:
            return current

        res = (
            self.db.table("member_params")
            .update(payload)
            .eq("user_id", user_id)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]
        return self.get_or_create_member_params(user_id)

    def assert_active_member_of_org(self, user_id: str, organization_id: str) -> None:
        mres = (
            self.db.table("members")
            .select("id")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        if not (mres.data or []):
            raise NotOrgMemberError()

    def assert_user_is_member(self, user_id: str) -> None:
        self._get_member_user(user_id)
