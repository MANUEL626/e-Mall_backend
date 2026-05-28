"""
CRUD articles d'organisation (service role après contrôle membre actif).
"""

from typing import Any, Dict, List, Optional

from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_articles.organization_articles_models import (
    CurrencyCode,
    OrganizationArticleCreate,
    OrganizationArticleUpdate,
    WholesalePriceTier,
)
from features.organization_subscriptions.organization_subscriptions_service import (
    OrganizationSubscriptionLimitExceeded,
    OrganizationSubscriptionService,
)


class OrganizationArticlesService:
    def __init__(self) -> None:
        self.db: Client = supabase_admin
        self.subscriptions = OrganizationSubscriptionService()

    @staticmethod
    def _org_path_prefix(organization_id: str) -> str:
        return f"{organization_id.strip()}/"

    @staticmethod
    def _wholesale_to_db(tiers: Optional[List[WholesalePriceTier]]) -> Optional[Any]:
        if tiers is None:
            return None
        return [
            {
                "min_quantity": t.min_quantity,
                "max_quantity": t.max_quantity,
                "unit_price": float(t.unit_price),
            }
            for t in tiers
        ]

    def _organization_default_sale_currency(self, organization_id: str) -> str:
        res = (
            self.db.table("organizations")
            .select("default_currencies")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Organisation introuvable")
        defaults = rows[0].get("default_currencies")
        if not isinstance(defaults, dict):
            return CurrencyCode.xof.value
        sale = str(defaults.get("sale") or CurrencyCode.xof.value).strip().lower()
        allowed = {c.value for c in CurrencyCode}
        return sale if sale in allowed else CurrencyCode.xof.value

    def _assert_paths_belong_to_org(
        self,
        organization_id: str,
        primary: str,
        additional: List[str],
    ) -> None:
        prefix = self._org_path_prefix(organization_id)
        if not primary.startswith(prefix):
            raise ValueError(
                "L'image principale doit utiliser le préfixe "
                f"{organization_id}/… dans le bucket organization-articles"
            )
        for path in additional:
            if not path.startswith(prefix):
                raise ValueError(
                    "Chaque image additionnelle doit utiliser le même préfixe "
                    f"{organization_id}/…"
                )

    def assert_org_member(self, user_id: str, organization_id: str) -> None:
        res = (
            self.db.table("members")
            .select("id")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        if not (res.data or []):
            raise PermissionError(
                "Accès refusé : vous n'êtes pas membre actif de cette organisation"
            )

    def list_articles(
        self,
        user_id: str,
        organization_id: str,
        active_only: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        self.assert_org_member(user_id, organization_id)
        q = (
            self.db.table("organization_articles")
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=True)
        )
        if active_only is True:
            q = q.eq("active", True)
        elif active_only is False:
            q = q.eq("active", False)
        res = q.execute()
        return list(res.data or [])

    def get_article(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        res = (
            self.db.table("organization_articles")
            .select("*")
            .eq("id", article_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Article introuvable")
        return rows[0]

    def create_article(
        self,
        user_id: str,
        organization_id: str,
        body: OrganizationArticleCreate,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        if body.active:
            try:
                self.subscriptions.assert_usage_below_limit(
                    organization_id,
                    "active_articles",
                    increment=1,
                )
            except OrganizationSubscriptionLimitExceeded as exc:
                raise ValueError(str(exc)) from exc
        oid = str(organization_id)
        self._assert_paths_belong_to_org(
            oid,
            body.primary_image_storage_path,
            body.additional_image_storage_paths,
        )
        row = {
            "organization_id": oid,
            "name": body.name.strip(),
            "category": body.category.value,
            "unit_sale_price": float(body.unit_sale_price),
            "sale_currency": (
                body.sale_currency.value
                if body.sale_currency is not None
                else self._organization_default_sale_currency(oid)
            ),
            "wholesale_prices": self._wholesale_to_db(body.wholesale_prices),
            "stock_quantity": body.stock_quantity,
            "alert_quantity": body.alert_quantity,
            "description": body.description,
            "primary_image_storage_path": body.primary_image_storage_path.strip(),
            "additional_image_storage_paths": body.additional_image_storage_paths,
            "active": body.active,
        }
        ins = self.db.table("organization_articles").insert(row).execute()
        rows = ins.data or []
        if not rows:
            raise RuntimeError("Création de l'article refusée")
        return rows[0]

    def update_article(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        body: OrganizationArticleUpdate,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        existing = self.get_article(user_id, organization_id, article_id)
        updates: Dict[str, Any] = {}
        if body.name is not None:
            updates["name"] = body.name.strip()
        if body.category is not None:
            updates["category"] = body.category.value
        if body.unit_sale_price is not None:
            updates["unit_sale_price"] = float(body.unit_sale_price)
        if body.sale_currency is not None:
            updates["sale_currency"] = body.sale_currency.value
        if body.wholesale_prices is not None:
            updates["wholesale_prices"] = self._wholesale_to_db(body.wholesale_prices)
        if body.stock_quantity is not None:
            updates["stock_quantity"] = body.stock_quantity
        if body.alert_quantity is not None:
            updates["alert_quantity"] = body.alert_quantity
        if body.description is not None:
            updates["description"] = body.description
        if body.primary_image_storage_path is not None:
            updates["primary_image_storage_path"] = body.primary_image_storage_path.strip()
        if body.additional_image_storage_paths is not None:
            updates["additional_image_storage_paths"] = body.additional_image_storage_paths
        if body.active is not None:
            updates["active"] = body.active

        if not updates:
            return existing

        if existing.get("active") is not True and updates.get("active") is True:
            try:
                self.subscriptions.assert_usage_below_limit(
                    organization_id,
                    "active_articles",
                    increment=1,
                )
            except OrganizationSubscriptionLimitExceeded as exc:
                raise ValueError(str(exc)) from exc

        oid = str(organization_id)
        primary = updates.get(
            "primary_image_storage_path", existing["primary_image_storage_path"]
        )
        additional = updates.get(
            "additional_image_storage_paths",
            existing.get("additional_image_storage_paths") or [],
        )
        self._assert_paths_belong_to_org(oid, primary, list(additional))

        upd = (
            self.db.table("organization_articles")
            .update(updates)
            .eq("id", article_id)
            .eq("organization_id", oid)
            .execute()
        )
        rows = upd.data or []
        if rows:
            return rows[0]
        return self.get_article(user_id, organization_id, article_id)

    def delete_article(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
    ) -> None:
        self.assert_org_member(user_id, organization_id)
        _ = self.get_article(user_id, organization_id, article_id)
        self.db.table("organization_articles").delete().eq("id", article_id).eq(
            "organization_id", str(organization_id)
        ).execute()
