"""Service de tracking des signaux tendance customer."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from supabase import Client

from config.supabase_client import supabase_admin
from features.customers.customer_analytics_models import CustomerArticleTrendEventCreate


class CustomerAnalyticsService:
    _DEDUP_WINDOW_SECONDS = 45

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    @staticmethod
    def _normalize_locale(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        value = value.strip()
        if not value:
            return None
        return value.replace("_", "-")

    @staticmethod
    def _normalize_country(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            return None
        return value

    def _get_customer_params_context(self, customer_id: str) -> Dict[str, Optional[str]]:
        res = (
            self.db.table("customer_params")
            .select("locale, extra")
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return {"locale": None, "country": None}

        row = rows[0] or {}
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        return {
            "locale": self._normalize_locale(row.get("locale")),
            "country": self._normalize_country(extra.get("country")),
        }

    def _get_article(self, article_id: UUID) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("organization_articles")
            .select("id, organization_id, category, active")
            .eq("id", str(article_id))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def _organization_exists(self, organization_id: UUID) -> bool:
        res = (
            self.db.table("organizations")
            .select("id")
            .eq("id", str(organization_id))
            .limit(1)
            .execute()
        )
        return bool(res.data or [])

    def _find_recent_duplicate(
        self,
        payload: Dict[str, Any],
        *,
        since: datetime,
    ) -> Optional[Dict[str, Any]]:
        query = (
            self.db.table("customer_article_trend_events")
            .select("id, organization_id, article_id, event_type, occurred_at")
            .eq("customer_id", payload["customer_id"])
            .eq("organization_id", payload["organization_id"])
            .eq("event_type", payload["event_type"])
            .gte("occurred_at", since.isoformat())
            .order("occurred_at", desc=True)
            .limit(1)
        )

        if payload.get("article_id"):
            query = query.eq("article_id", payload["article_id"])
        else:
            query = query.is_("article_id", "null")

        if payload.get("search_query"):
            query = query.eq("search_query", payload["search_query"])
        else:
            query = query.is_("search_query", "null")

        if payload.get("source"):
            query = query.eq("source", payload["source"])
        else:
            query = query.is_("source", "null")

        rows = query.execute().data or []
        return rows[0] if rows else None

    def create_article_event(
        self,
        *,
        customer_id: str,
        body: CustomerArticleTrendEventCreate,
    ) -> Dict[str, Any]:
        article: Optional[Dict[str, Any]] = None
        if body.article_id is not None:
            article = self._get_article(body.article_id)
            if not article or not article.get("active"):
                raise LookupError("Article introuvable ou inactif")
            if str(article["organization_id"]) != str(body.organization_id):
                raise ValueError("article_id ne correspond pas a organization_id")
        elif not self._organization_exists(body.organization_id):
            raise LookupError("Organisation introuvable")

        params = self._get_customer_params_context(customer_id)
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "organization_id": str(body.organization_id),
            "article_id": str(body.article_id) if body.article_id else None,
            "customer_id": customer_id,
            "event_type": body.event_type.value,
            "search_query": body.search_query,
            "category": (article or {}).get("category")
            or (body.category.value if body.category else None),
            "country": body.country or params.get("country"),
            "locale": self._normalize_locale(body.locale) or params.get("locale"),
            "source": body.source,
            "metadata": body.metadata,
            "occurred_at": now.isoformat(),
        }

        since = now - timedelta(seconds=self._DEDUP_WINDOW_SECONDS)
        duplicate = self._find_recent_duplicate(payload, since=since)
        if duplicate:
            duplicate["deduplicated"] = True
            return duplicate

        res = (
            self.db.table("customer_article_trend_events")
            .insert(payload)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise RuntimeError("Evenement tendance non cree")

        row = rows[0]
        row["deduplicated"] = False
        return row

    def create_purchase_events_for_order(self, order_row: Dict[str, Any]) -> int:
        if order_row.get("status") != "completed" or not order_row.get("customer_id"):
            return 0

        lines = list(order_row.get("organization_customer_sale_order_lines") or [])
        line_ids = [str(line["id"]) for line in lines if line.get("id")]
        if not line_ids:
            return 0

        existing_res = (
            self.db.table("customer_article_trend_events")
            .select("sale_order_line_id")
            .eq("event_type", "purchase")
            .in_("sale_order_line_id", line_ids)
            .execute()
        )
        existing_line_ids = {
            str(row["sale_order_line_id"])
            for row in (existing_res.data or [])
            if row.get("sale_order_line_id")
        }

        article_ids = [str(line["article_id"]) for line in lines if line.get("article_id")]
        article_category_by_id: Dict[str, Any] = {}
        if article_ids:
            articles_res = (
                self.db.table("organization_articles")
                .select("id, category")
                .in_("id", list(set(article_ids)))
                .execute()
            )
            article_category_by_id = {
                str(row["id"]): row.get("category")
                for row in (articles_res.data or [])
                if row.get("id")
            }

        params = self._get_customer_params_context(str(order_row["customer_id"]))
        payloads = []
        for line in lines:
            line_id = str(line.get("id") or "")
            article_id = str(line.get("article_id") or "")
            if not line_id or line_id in existing_line_ids or not article_id:
                continue

            quantity = int(line.get("quantity") or 0)
            unit_price = Decimal(str(line.get("unit_price_snapshot") or "0"))
            payloads.append(
                {
                    "organization_id": str(order_row["organization_id"]),
                    "article_id": article_id,
                    "customer_id": str(order_row["customer_id"]),
                    "event_type": "purchase",
                    "category": article_category_by_id.get(article_id),
                    "country": params.get("country"),
                    "locale": params.get("locale"),
                    "source": "customer_sale_completed",
                    "metadata": {
                        "order_id": str(order_row["id"]),
                        "order_line_id": line_id,
                        "quantity": quantity,
                        "unit_price_snapshot": str(unit_price),
                        "line_total": str(unit_price * quantity),
                        "currency": line.get("currency_snapshot") or order_row.get("currency"),
                        "fulfillment_type": order_row.get("fulfillment_type"),
                    },
                    "sale_order_id": str(order_row["id"]),
                    "sale_order_line_id": line_id,
                }
            )

        if not payloads:
            return 0

        res = self.db.table("customer_article_trend_events").insert(payloads).execute()
        return len(res.data or [])
