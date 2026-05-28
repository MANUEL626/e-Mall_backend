"""
Catalogue produits pour customers : lecture via service role (hors RLS membre).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from supabase import Client

from config.supabase_client import supabase_admin


class CustomerCatalogService:
    DEFAULT_TIMEZONE = "Africa/Lome"
    TREND_EVENT_TYPES = (
        "search",
        "view",
        "post_view",
        "wishlist_add",
        "cart_add",
        "purchase",
        "cart_abandon",
    )
    _SELECT_FIELDS = (
        "id, organization_id, name, category, unit_sale_price, sale_currency, stock_status, "
        "primary_image_storage_path, additional_image_storage_paths, description, "
        "created_at, updated_at"
    )

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    @staticmethod
    def _normalize_categories(categories: Optional[Sequence[str]]) -> Optional[List[str]]:
        if not categories:
            return None
        out = [c.strip() for c in categories if c and str(c).strip()]
        return out or None

    @staticmethod
    def _normalize_country(country: Any) -> Optional[str]:
        if not isinstance(country, str):
            return None
        country = country.strip().upper()
        if len(country) != 2 or not country.isalpha():
            return None
        return country

    @staticmethod
    def _normalize_interests(raw: Any) -> Set[str]:
        if not isinstance(raw, list):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if not isinstance(value, str) or not value:
            return datetime.fromtimestamp(0, tz=timezone.utc)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.fromtimestamp(0, tz=timezone.utc)

    def _customer_context(self, customer_id: Optional[str]) -> Dict[str, Any]:
        if not customer_id:
            return {
                "country": None,
                "interests": set(),
                "subscribed_org_ids": set(),
            }

        params_res = (
            self.db.table("customer_params")
            .select("extra")
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        params = (params_res.data or [{}])[0] or {}
        extra = params.get("extra") if isinstance(params.get("extra"), dict) else {}
        country = self._normalize_country(extra.get("country"))
        interests = self._normalize_interests(extra.get("interests"))

        subs_res = (
            self.db.table("customer_organization_subscriptions")
            .select("organization_id")
            .eq("customer_id", customer_id)
            .eq("status", "active")
            .execute()
        )
        subscribed_org_ids = {
            str(row["organization_id"])
            for row in (subs_res.data or [])
            if row.get("organization_id")
        }

        return {
            "country": country,
            "interests": interests,
            "subscribed_org_ids": subscribed_org_ids,
        }

    def _organization_context(self, organization_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        if not organization_ids:
            return {}
        org_res = (
            self.db.table("organizations")
            .select("id, name, countries")
            .in_("id", list({str(oid) for oid in organization_ids}))
            .execute()
        )
        return {str(o["id"]): o for o in (org_res.data or [])}

    def _relevance_score(
        self,
        row: Dict[str, Any],
        *,
        org: Optional[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> int:
        score = 0
        oid = str(row.get("organization_id") or "")
        if oid and oid in context.get("subscribed_org_ids", set()):
            score += 100

        country = context.get("country")
        org_countries = org.get("countries") if org else []
        if country and isinstance(org_countries, list):
            normalized_org_countries = {
                c.strip().upper() for c in org_countries if isinstance(c, str)
            }
            if country in normalized_org_countries:
                score += 50

        interests = context.get("interests", set())
        category = str(row.get("category") or "").strip()
        if category and category in interests:
            score += 30

        return score

    def _sort_rows_for_customer(
        self,
        rows: List[Dict[str, Any]],
        *,
        customer_id: Optional[str],
        date_field: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        if not rows:
            return [], {}

        context = self._customer_context(customer_id)
        org_map = self._organization_context(
            [str(r["organization_id"]) for r in rows if r.get("organization_id")]
        )

        def sort_key(row: Dict[str, Any]):
            score = self._relevance_score(
                row,
                org=org_map.get(str(row.get("organization_id") or "")),
                context=context,
            )
            # Higher score and newer content first.
            ts = self._parse_datetime(row.get(date_field))
            return (-score, -ts.timestamp(), str(row.get("id") or row.get("organization_article_id") or ""))

        return sorted(rows, key=sort_key), org_map

    def _rows_to_products(
        self,
        rows: List[Dict[str, Any]],
        org_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        if org_map is None:
            org_map = self._organization_context(
                [str(r["organization_id"]) for r in rows if r.get("organization_id")]
            )
        out: List[Dict[str, Any]] = []
        for r in rows:
            oid = str(r["organization_id"])
            org = org_map.get(oid) or {}
            add_paths = r.get("additional_image_storage_paths") or []
            if not isinstance(add_paths, list):
                add_paths = []
            out.append(
                {
                    "id": r["id"],
                    "organization_id": r["organization_id"],
                    "organization_name": org.get("name") or "",
                    "name": r["name"],
                    "category": r["category"],
                    "unit_sale_price": Decimal(str(r["unit_sale_price"])),
                    "sale_currency": r.get("sale_currency") or "xof",
                    "stock_status": r["stock_status"],
                    "primary_image_storage_path": r["primary_image_storage_path"],
                    "additional_image_storage_paths": add_paths,
                    "description": r.get("description"),
                }
            )
        return out

    def _build_base_query(
        self,
        *,
        name_ilike: Optional[str] = None,
        categories: Optional[Sequence[str]] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
    ):
        q = (
            self.db.table("organization_articles")
            .select(self._SELECT_FIELDS, count="exact")
            .eq("active", True)
        )
        if name_ilike:
            term = name_ilike.strip()
            if term:
                q = q.ilike("name", f"%{term}%")
        cats = self._normalize_categories(categories)
        if cats is not None:
            q = q.in_("category", cats)
        if min_price is not None:
            q = q.gte("unit_sale_price", float(min_price))
        if max_price is not None:
            q = q.lte("unit_sale_price", float(max_price))
        return q

    def list_catalog_page(
        self,
        *,
        limit: int,
        offset: int,
        customer_id: Optional[str] = None,
        name_ilike: Optional[str] = None,
        categories: Optional[Sequence[str]] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        q = self._build_base_query(
            name_ilike=name_ilike,
            categories=categories,
            min_price=min_price,
            max_price=max_price,
        )
        q = q.order("created_at", desc=True)
        q = q.range(offset, offset + max(limit, 1) - 1)
        res = q.execute()
        rows = list(res.data or [])
        total = int(res.count) if res.count is not None else len(rows)
        if not customer_id:
            return self._rows_to_products(rows), total
        sorted_rows, org_map = self._sort_rows_for_customer(
            rows,
            customer_id=customer_id,
            date_field="created_at",
        )
        page = sorted_rows[offset : offset + max(limit, 1)]
        return self._rows_to_products(page, org_map), total

    def format_catalog_products(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Réutilise l’enrichissement nom d’organisation pour des lignes `organization_articles`."""
        return self._rows_to_products(rows)

    def get_public_catalog_product(self, organization_article_id: str) -> Optional[Dict[str, Any]]:
        """Article actif enrichi pour une lecture publique de partage."""
        res = (
            self.db.table("organization_articles")
            .select(self._SELECT_FIELDS)
            .eq("id", organization_article_id)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        rows = list(res.data or [])
        products = self._rows_to_products(rows)
        return products[0] if products else None

    def list_public_article_posts(self, organization_article_id: str) -> List[Dict[str, Any]]:
        """Posts actifs pour un article actif (vitrine customer)."""
        article = (
            self.db.table("organization_articles")
            .select("id")
            .eq("id", organization_article_id)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        if not (article.data or []):
            raise LookupError("Article introuvable ou inactif")
        res = (
            self.db.table("organization_article_posts")
            .select(
                "id, slot, media_kind, media_storage_path, "
                "video_mobile_low_storage_path, thumbnail_storage_path, "
                "caption, processing_status, media_width, media_height, "
                "media_duration_seconds, created_at, updated_at"
            )
            .eq("organization_article_id", organization_article_id)
            .eq("active", True)
            .order("slot")
            .execute()
        )
        rows = list(res.data or [])
        out: List[Dict[str, Any]] = []
        for row in rows:
            if row.get("media_kind") == "image":
                out.append(row)
                continue
            low_path = row.get("video_mobile_low_storage_path")
            if row.get("processing_status") == "ready" and low_path:
                row["media_storage_path"] = low_path
                out.append(row)
        return out

    def list_article_post_feed_page(
        self,
        *,
        limit: int,
        offset: int,
        customer_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Posts actifs + article actif (vue `customer_article_post_feed`), tri récents d’abord.
        """
        res = (
            self.db.table("customer_article_post_feed")
            .select("*", count="exact")
            .order("post_created_at", desc=True)
            .range(offset, offset + max(limit, 1) - 1)
            .execute()
        )
        rows = list(res.data or [])
        total = int(res.count) if res.count is not None else len(rows)
        if not customer_id:
            return self._feed_rows_to_items(rows), total
        sorted_rows, org_map = self._sort_rows_for_customer(
            rows,
            customer_id=customer_id,
            date_field="post_created_at",
        )
        return self._feed_rows_to_items(sorted_rows, org_map), total

    def list_trending_products(
        self,
        *,
        customer_id: str,
        period: str = "30d",
        limit: int = 20,
        country: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        start, end = self._trend_period_window(period)
        context = self._customer_context(customer_id)
        requested_country = self._normalize_country(country) or context.get("country")
        requested_category = category.strip() if isinstance(category, str) and category.strip() else None
        if requested_category:
            context["interests"] = set(context.get("interests", set())) | {requested_category}

        trend_query = (
            self.db.table("customer_article_trend_events")
            .select("article_id,event_type,weight")
            .gte("occurred_at", start.isoformat())
            .lt("occurred_at", end.isoformat())
        )
        metrics: Dict[str, Dict[str, Any]] = {}
        for event in self._execute_paged(trend_query):
            article_id = event.get("article_id")
            if not article_id:
                continue
            event_type = str(event.get("event_type") or "")
            if event_type not in self.TREND_EVENT_TYPES:
                continue
            article_key = str(article_id)
            metric = metrics.setdefault(
                article_key,
                {
                    "trend_score": Decimal("0"),
                    "events": {key: 0 for key in self.TREND_EVENT_TYPES},
                },
            )
            metric["events"][event_type] += 1
            metric["trend_score"] += Decimal(str(event.get("weight") or "0"))

        if not metrics:
            return [], 0

        article_rows: List[Dict[str, Any]] = []
        for chunk in self._chunks(list(metrics.keys()), 200):
            article_query = (
                self.db.table("organization_articles")
                .select(self._SELECT_FIELDS)
                .eq("active", True)
                .in_("id", chunk)
            )
            if requested_category:
                article_query = article_query.eq("category", requested_category)
            article_rows.extend(self._execute_paged(article_query))

        if not article_rows:
            return [], 0

        org_map = self._organization_context(
            [str(row["organization_id"]) for row in article_rows if row.get("organization_id")]
        )

        def sort_key(row: Dict[str, Any]):
            article_id = str(row["id"])
            metric = metrics.get(article_id, {})
            score = Decimal(str(metric.get("trend_score") or "0"))
            relevance = self._relevance_score(row, org=org_map.get(str(row.get("organization_id"))), context=context)
            org = org_map.get(str(row.get("organization_id") or "")) or {}
            org_countries = org.get("countries") if isinstance(org.get("countries"), list) else []
            country_bonus = 0
            if requested_country and requested_country in {
                c.strip().upper() for c in org_countries if isinstance(c, str)
            }:
                country_bonus = 50
            stock_bonus = 20 if row.get("stock_status") != "out_of_stock" else 0
            return (
                -(score + Decimal(relevance + country_bonus + stock_bonus)),
                str(row.get("name") or ""),
            )

        sorted_rows = sorted(article_rows, key=sort_key)
        page = sorted_rows[: max(limit, 1)]
        products = self._rows_to_products(page, org_map)
        out = []
        for product in products:
            article_id = str(product["id"])
            metric = metrics.get(article_id, {})
            product["trend_score"] = Decimal(str(metric.get("trend_score") or "0"))
            product["events"] = metric.get("events") or {
                key: 0 for key in self.TREND_EVENT_TYPES
            }
            out.append(product)
        return out, len(article_rows)

    def _feed_rows_to_items(
        self,
        rows: List[Dict[str, Any]],
        org_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        if org_map is None:
            org_map = self._organization_context(
                [str(r["organization_id"]) for r in rows if r.get("organization_id")]
            )
        out: List[Dict[str, Any]] = []
        for r in rows:
            oid = str(r["organization_id"])
            org = org_map.get(oid) or {}
            add_paths = r.get("additional_image_storage_paths") or []
            if not isinstance(add_paths, list):
                add_paths = []
            out.append(
                {
                    "organization_id": r["organization_id"],
                    "organization_name": org.get("name") or "",
                    "organization_article_id": r["organization_article_id"],
                    "name": r["name"],
                    "category": r["category"],
                    "unit_sale_price": Decimal(str(r["unit_sale_price"])),
                    "sale_currency": r.get("sale_currency") or "xof",
                    "stock_status": r["stock_status"],
                    "primary_image_storage_path": r["primary_image_storage_path"],
                    "additional_image_storage_paths": add_paths,
                    "description": r.get("description"),
                    "slot": r["slot"],
                    "media_kind": r["media_kind"],
                    "media_storage_path": r["media_storage_path"],
                    "video_mobile_low_storage_path": r.get("video_mobile_low_storage_path"),
                    "thumbnail_storage_path": r.get("thumbnail_storage_path"),
                    "caption": r.get("caption"),
                    "processing_status": r.get("processing_status") or "ready",
                    "media_width": r.get("media_width"),
                    "media_height": r.get("media_height"),
                    "media_duration_seconds": r.get("media_duration_seconds"),
                }
            )
        return out

    def _trend_period_window(self, period: str) -> Tuple[datetime, datetime]:
        tz = ZoneInfo(self.DEFAULT_TIMEZONE)
        end = datetime.now(tz)
        if period == "7d":
            return end - timedelta(days=7), end
        if period == "30d":
            return end - timedelta(days=30), end
        if period == "90d":
            return end - timedelta(days=90), end
        year_start = datetime(end.year, 1, 1, tzinfo=tz)
        return year_start, end

    @staticmethod
    def _chunks(values: List[str], size: int):
        for index in range(0, len(values), size):
            yield values[index : index + size]

    def _execute_paged(self, query: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        offset = 0
        page_size = 1000
        while True:
            res = query.range(offset, offset + page_size - 1).execute()
            batch = list(res.data or [])
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return rows
