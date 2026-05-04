"""
Catalogue produits pour customers : lecture via service role (hors RLS membre).
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from supabase import Client

from config.supabase_client import supabase_admin


class CustomerCatalogService:
    _SELECT_FIELDS = (
        "id, organization_id, name, category, unit_sale_price, stock_status, "
        "primary_image_storage_path, additional_image_storage_paths, description"
    )

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    @staticmethod
    def _normalize_categories(categories: Optional[Sequence[str]]) -> Optional[List[str]]:
        if not categories:
            return None
        out = [c.strip() for c in categories if c and str(c).strip()]
        return out or None

    def _rows_to_products(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        org_ids = list({str(r["organization_id"]) for r in rows})
        org_res = (
            self.db.table("organizations")
            .select("id, name")
            .in_("id", org_ids)
            .execute()
        )
        org_map = {str(o["id"]): o.get("name") or "" for o in (org_res.data or [])}
        out: List[Dict[str, Any]] = []
        for r in rows:
            oid = str(r["organization_id"])
            add_paths = r.get("additional_image_storage_paths") or []
            if not isinstance(add_paths, list):
                add_paths = []
            out.append(
                {
                    "id": r["id"],
                    "organization_id": r["organization_id"],
                    "organization_name": org_map.get(oid, ""),
                    "name": r["name"],
                    "category": r["category"],
                    "unit_sale_price": Decimal(str(r["unit_sale_price"])),
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
        end = offset + max(limit, 1) - 1
        q = q.range(offset, end)
        res = q.execute()
        rows = list(res.data or [])
        total = int(res.count) if res.count is not None else len(rows)
        return self._rows_to_products(rows), total

    def format_catalog_products(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Réutilise l’enrichissement nom d’organisation pour des lignes `organization_articles`."""
        return self._rows_to_products(rows)

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
            .select("id, slot, media_kind, media_storage_path, caption, created_at, updated_at")
            .eq("organization_article_id", organization_article_id)
            .eq("active", True)
            .order("slot")
            .execute()
        )
        return list(res.data or [])

    def list_article_post_feed_page(
        self,
        *,
        limit: int,
        offset: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Posts actifs + article actif (vue `customer_article_post_feed`), tri récents d’abord.
        """
        end = offset + max(limit, 1) - 1
        res = (
            self.db.table("customer_article_post_feed")
            .select("*", count="exact")
            .order("post_created_at", desc=True)
            .range(offset, end)
            .execute()
        )
        rows = list(res.data or [])
        total = int(res.count) if res.count is not None else len(rows)
        return self._feed_rows_to_items(rows), total

    def _feed_rows_to_items(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        org_ids = list({str(r["organization_id"]) for r in rows})
        org_res = (
            self.db.table("organizations")
            .select("id, name")
            .in_("id", org_ids)
            .execute()
        )
        org_map = {str(o["id"]): o.get("name") or "" for o in (org_res.data or [])}
        out: List[Dict[str, Any]] = []
        for r in rows:
            oid = str(r["organization_id"])
            add_paths = r.get("additional_image_storage_paths") or []
            if not isinstance(add_paths, list):
                add_paths = []
            out.append(
                {
                    "organization_id": r["organization_id"],
                    "organization_name": org_map.get(oid, ""),
                    "organization_article_id": r["organization_article_id"],
                    "name": r["name"],
                    "category": r["category"],
                    "unit_sale_price": Decimal(str(r["unit_sale_price"])),
                    "stock_status": r["stock_status"],
                    "primary_image_storage_path": r["primary_image_storage_path"],
                    "additional_image_storage_paths": add_paths,
                    "description": r.get("description"),
                    "slot": r["slot"],
                    "media_kind": r["media_kind"],
                    "media_storage_path": r["media_storage_path"],
                    "caption": r.get("caption"),
                }
            )
        return out
