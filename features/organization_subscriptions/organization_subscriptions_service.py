"""
Internal subscription engine for organizations.

Stripe will later update `organization_subscriptions`; product code should keep
reading entitlements from this service.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

from config.supabase_client import supabase_admin


class OrganizationSubscriptionNotFound(Exception):
    """No organization exists for the requested id."""


class OrganizationSubscriptionForbidden(Exception):
    """The user is not allowed to read or update this subscription."""


class OrganizationSubscriptionFeatureDenied(Exception):
    """The current plan does not allow the requested feature."""


class OrganizationSubscriptionLimitExceeded(Exception):
    """The current plan limit is reached."""


class OrganizationSubscriptionService:
    ACTIVE_STATUSES = {"active", "trialing"}
    _plans_cache: Optional[tuple[datetime, List[Dict[str, Any]]]] = None
    _plan_cache_ttl = timedelta(minutes=5)

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    def _membership(
        self,
        user_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("members")
            .select("member_type,activity_status")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def assert_org_member(self, user_id: str, organization_id: str) -> Dict[str, Any]:
        membership = self._membership(user_id, organization_id)
        if not membership or membership.get("activity_status") is not True:
            raise OrganizationSubscriptionForbidden(
                "Acces refuse pour cette organisation"
            )
        return membership

    def assert_org_admin(self, user_id: str, organization_id: str) -> Dict[str, Any]:
        membership = self.assert_org_member(user_id, organization_id)
        if membership.get("member_type") != "admin":
            raise OrganizationSubscriptionForbidden(
                "Seul un administrateur peut modifier l'abonnement"
            )
        return membership

    def list_plans(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        if self._plans_cache is not None:
            cached_at, rows = self._plans_cache
            if now - cached_at < self._plan_cache_ttl:
                return [dict(row) for row in rows]

        res = (
            self.db.table("organization_subscription_plans")
            .select("*")
            .eq("active", True)
            .order("sort_order", desc=False)
            .execute()
        )
        rows = list(res.data or [])
        self.__class__._plans_cache = (now, rows)
        return [dict(row) for row in rows]

    def _get_plan(self, plan_code: str) -> Optional[Dict[str, Any]]:
        for row in self.list_plans():
            if str(row.get("code")) == plan_code:
                return row
        return None

    def _organization_exists(self, organization_id: str) -> bool:
        res = (
            self.db.table("organizations")
            .select("id")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    def _ensure_subscription(self, organization_id: str) -> Dict[str, Any]:
        res = (
            self.db.table("organization_subscriptions")
            .select("*")
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]

        if not self._organization_exists(organization_id):
            raise OrganizationSubscriptionNotFound()

        created = (
            self.db.table("organization_subscriptions")
            .insert(
                {
                    "organization_id": organization_id,
                    "plan": "freemium",
                    "status": "active",
                    "source": "internal",
                    "metadata": {"created_by_api": True},
                }
            )
            .execute()
        )
        created_rows = created.data or []
        if not created_rows:
            raise OrganizationSubscriptionNotFound()
        return created_rows[0]

    def get_subscription(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        subscription = self._ensure_subscription(organization_id)
        plan = self._get_plan(str(subscription.get("plan")))
        return {**subscription, "plan_details": plan}

    def update_subscription(
        self,
        user_id: str,
        organization_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.assert_org_admin(user_id, organization_id)
        self._ensure_subscription(organization_id)

        payload = {k: v for k, v in updates.items() if v is not None}
        if payload.get("source") is None:
            payload.pop("source", None)
        if "metadata" in payload and payload["metadata"] is None:
            payload.pop("metadata", None)
        if not payload:
            raise ValueError("Aucune donnee d'abonnement a mettre a jour")

        res = (
            self.db.table("organization_subscriptions")
            .update(payload)
            .eq("organization_id", organization_id)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise OrganizationSubscriptionNotFound()
        plan = self._get_plan(str(rows[0].get("plan")))
        return {**rows[0], "plan_details": plan}

    def _count_active_articles(self, organization_id: str) -> int:
        res = (
            self.db.table("organization_articles")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        return int(getattr(res, "count", None) or len(res.data or []))

    def _count_team_members(self, organization_id: str) -> int:
        res = (
            self.db.table("members")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        return int(getattr(res, "count", None) or len(res.data or []))

    def _count_monthly_walk_in_sales(self, organization_id: str) -> int:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        res = (
            self.db.table("organization_customer_sale_orders")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("fulfillment_type", "walk_in_offline")
            .gte("created_at", month_start.isoformat())
            .limit(1)
            .execute()
        )
        return int(getattr(res, "count", None) or len(res.data or []))

    def _usage_count_for_limit(self, organization_id: str, limit_key: str) -> int:
        if limit_key == "active_articles":
            return self._count_active_articles(organization_id)
        if limit_key == "team_members":
            return self._count_team_members(organization_id)
        if limit_key == "monthly_walk_in_sales":
            return self._count_monthly_walk_in_sales(organization_id)
        return 0

    @staticmethod
    def _limit_exceeded(limit_value: Any, usage_value: int) -> bool:
        if limit_value is None:
            return False
        try:
            return usage_value > int(limit_value)
        except (TypeError, ValueError):
            return False

    def get_entitlements(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        subscription = self.get_subscription(user_id, organization_id)
        return self._build_entitlements(organization_id, subscription)

    def get_entitlements_for_org(self, organization_id: str) -> Dict[str, Any]:
        subscription = self._ensure_subscription(organization_id)
        plan = self._get_plan(str(subscription.get("plan")))
        return self._build_entitlements(
            organization_id,
            {**subscription, "plan_details": plan},
        )

    def _build_entitlements(
        self,
        organization_id: str,
        subscription: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan = subscription.get("plan_details") or {}
        features = plan.get("features") or {}
        limits = plan.get("limits") or {}
        usage = {
            "active_articles": self._count_active_articles(organization_id),
            "team_members": self._count_team_members(organization_id),
            "monthly_walk_in_sales": self._count_monthly_walk_in_sales(organization_id),
        }
        exceeded_limits = {
            key: self._limit_exceeded(limits.get(key), value)
            for key, value in usage.items()
        }
        return {
            "organization_id": organization_id,
            "plan": subscription.get("plan"),
            "status": subscription.get("status"),
            "is_active": subscription.get("status") in self.ACTIVE_STATUSES,
            "features": features,
            "limits": limits,
            "usage": usage,
            "exceeded_limits": exceeded_limits,
            "subscription": subscription,
        }

    def assert_feature_enabled(self, organization_id: str, feature: str) -> None:
        subscription = self._ensure_subscription(organization_id)
        if subscription.get("status") not in self.ACTIVE_STATUSES:
            raise OrganizationSubscriptionFeatureDenied(
                "Abonnement inactif pour cette organisation"
            )
        plan = self._get_plan(str(subscription.get("plan"))) or {}
        value = (plan.get("features") or {}).get(feature)
        if value is not True:
            raise OrganizationSubscriptionFeatureDenied(
                f"Fonctionnalite non incluse dans l'abonnement: {feature}"
            )

    def assert_usage_below_limit(
        self,
        organization_id: str,
        limit_key: str,
        *,
        increment: int = 1,
    ) -> None:
        subscription = self._ensure_subscription(organization_id)
        if subscription.get("status") not in self.ACTIVE_STATUSES:
            raise OrganizationSubscriptionLimitExceeded(
                "Abonnement inactif pour cette organisation"
            )
        plan = self._get_plan(str(subscription.get("plan"))) or {}
        limits = plan.get("limits") or {}
        limit_value = limits.get(limit_key)
        if limit_value is None:
            return
        current = self._usage_count_for_limit(organization_id, limit_key)
        try:
            maximum = int(limit_value)
        except (TypeError, ValueError):
            return
        if current + increment > maximum:
            raise OrganizationSubscriptionLimitExceeded(
                f"Limite d'abonnement atteinte pour {limit_key}: {current}/{maximum}"
            )
