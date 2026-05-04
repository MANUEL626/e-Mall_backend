"""
Abonnements client → organisation : service role après validation JWT
(même approche que wishlist / paniers).
"""

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from supabase import Client

from config.supabase_client import supabase_admin


class CustomerSubscriptionsService:
    _ORG_FIELDS = "id, name, org_type"

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    def _organization_row(self, organization_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("organizations")
            .select(self._ORG_FIELDS)
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def get_organization_public_summary(
        self, organization_id: str
    ) -> Optional[Dict[str, Any]]:
        """Nom + nombre d’abonnés actifs (lecture seule)."""
        org = self._organization_row(organization_id)
        if not org:
            return None
        n = self.count_active_subscribers(organization_id)
        return {
            "id": org["id"],
            "name": org.get("name") or "",
            "subscriber_count": n,
        }

    def list_active_for_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        sub_res = (
            self.db.table("customer_organization_subscriptions")
            .select("id, organization_id, status, subscribed_at, cancelled_at")
            .eq("customer_id", customer_id)
            .eq("status", "active")
            .order("subscribed_at", desc=True)
            .execute()
        )
        subs = list(sub_res.data or [])
        if not subs:
            return []

        org_ids = list({str(s["organization_id"]) for s in subs})
        org_res = (
            self.db.table("organizations")
            .select(self._ORG_FIELDS)
            .in_("id", org_ids)
            .execute()
        )
        org_by_id = {str(o["id"]): o for o in (org_res.data or [])}

        out: List[Dict[str, Any]] = []
        for s in subs:
            oid = str(s["organization_id"])
            org = org_by_id.get(oid)
            if not org:
                continue
            out.append(
                {
                    "id": s["id"],
                    "organization_id": s["organization_id"],
                    "organization": {
                        "id": org["id"],
                        "name": org.get("name") or "",
                        "org_type": org.get("org_type") or "",
                    },
                    "status": s["status"],
                    "subscribed_at": s["subscribed_at"],
                    "cancelled_at": s.get("cancelled_at"),
                }
            )
        return out

    def subscribe(self, customer_id: str, organization_id: UUID) -> Dict[str, Any]:
        oid = str(organization_id)
        if not self._organization_row(oid):
            raise ValueError("Organisation introuvable")

        existing = (
            self.db.table("customer_organization_subscriptions")
            .select("id, status")
            .eq("customer_id", customer_id)
            .eq("organization_id", oid)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            sid = str(rows[0]["id"])
            if rows[0].get("status") == "active":
                one = (
                    self.db.table("customer_organization_subscriptions")
                    .select("id, organization_id, status, subscribed_at")
                    .eq("id", sid)
                    .limit(1)
                    .execute()
                )
                data = one.data or []
                if not data:
                    raise RuntimeError("Lecture abonnement impossible")
                return data[0]
            upd = (
                self.db.table("customer_organization_subscriptions")
                .update({"status": "active"})
                .eq("id", sid)
                .execute()
            )
            data = upd.data or []
            if not data:
                raise RuntimeError("Réactivation impossible")
            return {
                "id": data[0]["id"],
                "organization_id": data[0]["organization_id"],
                "status": data[0]["status"],
                "subscribed_at": data[0]["subscribed_at"],
            }

        ins = (
            self.db.table("customer_organization_subscriptions")
            .insert(
                {
                    "customer_id": customer_id,
                    "organization_id": oid,
                    "status": "active",
                }
            )
            .execute()
        )
        data = ins.data or []
        if not data:
            raise RuntimeError("Création abonnement impossible")
        return {
            "id": data[0]["id"],
            "organization_id": data[0]["organization_id"],
            "status": data[0]["status"],
            "subscribed_at": data[0]["subscribed_at"],
        }

    def unsubscribe(self, customer_id: str, organization_id: UUID) -> bool:
        oid = str(organization_id)
        existing = (
            self.db.table("customer_organization_subscriptions")
            .select("id, status")
            .eq("customer_id", customer_id)
            .eq("organization_id", oid)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if not rows or rows[0].get("status") != "active":
            return False
        self.db.table("customer_organization_subscriptions").update(
            {"status": "cancelled"}
        ).eq("id", str(rows[0]["id"])).execute()
        return True

    def count_active_subscribers(self, organization_id: str) -> int:
        q = (
            self.db.table("customer_organization_subscriptions")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("status", "active")
            .execute()
        )
        if q.count is not None:
            return int(q.count)
        return len(q.data or [])

    def list_active_subscribers_page(
        self,
        organization_id: str,
        *,
        limit: int,
        offset: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        total = self.count_active_subscribers(organization_id)
        sub_res = (
            self.db.table("customer_organization_subscriptions")
            .select("customer_id, subscribed_at")
            .eq("organization_id", organization_id)
            .eq("status", "active")
            .order("subscribed_at", desc=True)
            .range(offset, offset + max(limit, 1) - 1)
            .execute()
        )
        subs = list(sub_res.data or [])
        if not subs:
            return [], total

        cust_ids = [str(s["customer_id"]) for s in subs]
        users_res = (
            self.db.table("customers")
            .select("id, user_id")
            .in_("id", cust_ids)
            .execute()
        )
        cust_rows = list(users_res.data or [])
        user_ids = [str(c["user_id"]) for c in cust_rows if c.get("user_id")]
        user_by_id: Dict[str, str] = {}
        if user_ids:
            ures = (
                self.db.table("users")
                .select("id, username")
                .in_("id", user_ids)
                .execute()
            )
            for u in ures.data or []:
                user_by_id[str(u["id"])] = str(u.get("username") or "")

        cust_to_username: Dict[str, str] = {}
        for c in cust_rows:
            uid = c.get("user_id")
            cid = str(c["id"])
            if uid:
                cust_to_username[cid] = user_by_id.get(str(uid), "")

        items: List[Dict[str, Any]] = []
        for s in subs:
            cid = str(s["customer_id"])
            items.append(
                {
                    "customer_id": s["customer_id"],
                    "username": cust_to_username.get(cid, ""),
                    "subscribed_at": s["subscribed_at"],
                }
            )
        return items, total
