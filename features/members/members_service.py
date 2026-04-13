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

    def get_me(self, user_id: str, go_true_user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ures = self.db.table("users").select("*").eq("id", user_id).limit(1).execute()
        rows = ures.data or []
        if not rows:
            raise ProfileNotFoundError()
        user = rows[0]
        if user.get("user_type") != "member":
            raise NotMemberError()

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

        return {
            "user": user,
            "memberships": memberships,
            "auth": auth_snap,
        }
