"""
CRUD articles d'organisation (service role après contrôle membre actif).
"""

from typing import Any, Dict, List, Optional

from postgrest.exceptions import APIError
from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_articles.organization_articles_models import (
    CurrencyCode,
    OrganizationArticleCreate,
    OrganizationArticleStockPatch,
    OrganizationArticleUpdate,
    OrganizationStockScope,
    ShopStockResourceCreate,
    ShopStockResourceUpdate,
    WholesalePriceTier,
)
from features.organization_subscriptions.organization_subscriptions_service import (
    OrganizationSubscriptionLimitExceeded,
    OrganizationSubscriptionService,
)

_ARTICLE_SELECT_COLUMNS = (
    "id,organization_id,name,category,unit_sale_price,sale_currency,"
    "wholesale_prices,stock_quantity,alert_quantity,stock_status,"
    "description,primary_image_storage_path,additional_image_storage_paths,"
    "active,resource_scope,created_at,updated_at"
)

_SHOP_STOCK_SELECT_COLUMNS = (
    "id,organization_id,shop_id,article_id,stock_scope,stock_quantity,"
    "reserved_quantity,alert_quantity,stock_status,active,created_at,updated_at"
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
        return CurrencyCode.xof.value

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

    def _default_sales_shop_id(self, organization_id: str) -> str:
        res = (
            self.db.table("organization_shops")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("shop_type", "sales")
            .eq("is_default", True)
            .neq("status", "archived")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return str(rows[0]["id"])
        fallback = (
            self.db.table("organization_shops")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("shop_type", "sales")
            .neq("status", "archived")
            .order("created_at")
            .limit(1)
            .execute()
        )
        fallback_rows = fallback.data or []
        if not fallback_rows:
            raise ValueError("Aucune boutique de vente active pour cette organisation")
        return str(fallback_rows[0]["id"])

    def _assert_sales_shop(self, organization_id: str, shop_id: str) -> None:
        res = (
            self.db.table("organization_shops")
            .select("id")
            .eq("id", shop_id)
            .eq("organization_id", organization_id)
            .eq("shop_type", "sales")
            .neq("status", "archived")
            .limit(1)
            .execute()
        )
        if not (res.data or []):
            raise ValueError("Boutique de vente introuvable pour cette organisation")

    def _get_shop(self, organization_id: str, shop_id: str) -> Dict[str, Any]:
        res = (
            self.db.table("organization_shops")
            .select("id,organization_id,name,shop_type,status")
            .eq("id", shop_id)
            .eq("organization_id", organization_id)
            .neq("status", "archived")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise ValueError("Boutique introuvable pour cette organisation")
        return rows[0]

    @staticmethod
    def _scope_compatible_with_shop(shop_type: str, stock_scope: str) -> bool:
        if shop_type == "sales":
            return stock_scope == OrganizationStockScope.sales_item.value
        if shop_type == "repair":
            return stock_scope in {
                OrganizationStockScope.repair_supply.value,
                OrganizationStockScope.repair_tool.value,
            }
        if shop_type == "rental":
            return stock_scope == OrganizationStockScope.rental_asset.value
        return False

    def _assert_resource_shop_scope(
        self,
        organization_id: str,
        shop_id: str,
        stock_scope: str,
    ) -> Dict[str, Any]:
        shop = self._get_shop(organization_id, shop_id)
        if stock_scope == OrganizationStockScope.sales_item.value:
            raise ValueError("Utiliser les endpoints articles pour le stock sales_item")
        if not self._scope_compatible_with_shop(str(shop["shop_type"]), stock_scope):
            raise ValueError("Le type de ressource n'est pas compatible avec cette boutique")
        return shop

    def _stock_by_article(
        self,
        organization_id: str,
        shop_id: str,
        article_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        if not article_ids:
            return {}
        res = (
            self.db.table("organization_shop_article_stocks")
            .select(_SHOP_STOCK_SELECT_COLUMNS)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .in_("article_id", article_ids)
            .execute()
        )
        return {str(row["article_id"]): row for row in res.data or []}

    def _attach_shop_stock(
        self,
        rows: List[Dict[str, Any]],
        organization_id: str,
        shop_id: str,
    ) -> List[Dict[str, Any]]:
        stock_by_article = self._stock_by_article(
            organization_id,
            shop_id,
            [str(row["id"]) for row in rows if row.get("id")],
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            stock = stock_by_article.get(str(item.get("id")))
            item["shop_id"] = shop_id
            item["stock_scope"] = "sales_item"
            item["reserved_quantity"] = 0
            if stock:
                item["shop_id"] = stock.get("shop_id")
                item["stock_quantity"] = stock.get("stock_quantity", 0)
                item["reserved_quantity"] = stock.get("reserved_quantity", 0)
                item["alert_quantity"] = stock.get("alert_quantity", 0)
                item["stock_status"] = stock.get("stock_status", "out_of_stock")
                item["stock_scope"] = stock.get("stock_scope", "sales_item")
            else:
                item["stock_quantity"] = 0
                item["stock_status"] = "out_of_stock"
            out.append(item)
        return out

    def _sync_legacy_article_stock(
        self,
        organization_id: str,
        shop_id: str,
        article_id: str,
        stock_row: Dict[str, Any],
    ) -> None:
        if self._default_sales_shop_id(organization_id) != str(shop_id):
            return
        self.db.table("organization_articles").update(
            {
                "stock_quantity": int(stock_row.get("stock_quantity") or 0),
                "alert_quantity": int(stock_row.get("alert_quantity") or 0),
            }
        ).eq("id", article_id).eq("organization_id", organization_id).execute()

    def _resource_stock_scopes_for_shop(self, shop_type: str) -> List[str]:
        if shop_type == "repair":
            return [
                OrganizationStockScope.repair_supply.value,
                OrganizationStockScope.repair_tool.value,
            ]
        if shop_type == "rental":
            return [OrganizationStockScope.rental_asset.value]
        return []

    def _resource_rows_from_stock_rows(
        self,
        organization_id: str,
        stocks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        article_ids = [str(row["article_id"]) for row in stocks if row.get("article_id")]
        if not article_ids:
            return []
        articles = (
            self.db.table("organization_articles")
            .select(
                "id,organization_id,name,category,resource_scope,description,"
                "unit_purchase_price,unit_sale_price,sale_currency,wholesale_prices,"
                "primary_image_storage_path,additional_image_storage_paths,active,"
                "created_at,updated_at"
            )
            .eq("organization_id", organization_id)
            .in_("id", article_ids)
            .execute()
        )
        articles_by_id = {str(row["id"]): row for row in articles.data or []}
        out: List[Dict[str, Any]] = []
        for stock in stocks:
            article = articles_by_id.get(str(stock.get("article_id")))
            if not article:
                continue
            item = dict(article)
            item["shop_id"] = stock.get("shop_id")
            item["stock_scope"] = stock.get("stock_scope")
            item["stock_quantity"] = stock.get("stock_quantity", 0)
            item["reserved_quantity"] = stock.get("reserved_quantity", 0)
            item["alert_quantity"] = stock.get("alert_quantity", 0)
            item["stock_status"] = stock.get("stock_status", "out_of_stock")
            item["active"] = stock.get("active", article.get("active", True))
            item["unit_purchase_price"] = article.get("unit_purchase_price") or 0
            if str(stock.get("stock_scope")) == OrganizationStockScope.rental_asset.value:
                item["unit_rental_price"] = article.get("unit_sale_price") or 0
                item["rental_currency"] = CurrencyCode.xof.value
                item["rental_bulk_prices"] = article.get("wholesale_prices")
            else:
                item["unit_rental_price"] = None
                item["rental_currency"] = None
                item["rental_bulk_prices"] = None
            item["created_at"] = stock.get("created_at") or article.get("created_at")
            item["updated_at"] = stock.get("updated_at") or article.get("updated_at")
            out.append(item)
        return out

    def _get_resource_stock_row(
        self,
        organization_id: str,
        shop_id: str,
        resource_id: str,
    ) -> Dict[str, Any]:
        res = (
            self.db.table("organization_shop_article_stocks")
            .select(_SHOP_STOCK_SELECT_COLUMNS)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("article_id", resource_id)
            .neq("stock_scope", OrganizationStockScope.sales_item.value)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Ressource de stock introuvable dans cette boutique")
        return rows[0]

    def _get_shop_ids_for_scope(
        self,
        organization_id: str,
        stock_scope: str,
        target_shop_id: str,
    ) -> List[str]:
        target_shop = self._get_shop(organization_id, target_shop_id)
        shop_type = str(target_shop["shop_type"])
        res = (
            self.db.table("organization_shops")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("shop_type", shop_type)
            .neq("status", "archived")
            .execute()
        )
        ids = [
            str(row["id"])
            for row in res.data or []
            if self._scope_compatible_with_shop(shop_type, stock_scope)
        ]
        return ids or [target_shop_id]

    def list_stock_resources(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        active_only: Optional[bool] = None,
        stock_scope: Optional[OrganizationStockScope] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self.assert_org_member(user_id, organization_id)
        shop = self._get_shop(organization_id, shop_id)
        allowed = self._resource_stock_scopes_for_shop(str(shop["shop_type"]))
        if not allowed:
            raise ValueError("Cette boutique ne gere pas de stock dedie dans cette phase")
        if stock_scope is not None:
            if stock_scope.value == OrganizationStockScope.sales_item.value:
                raise ValueError("Utiliser les endpoints articles pour le stock sales_item")
            if stock_scope.value not in allowed:
                raise ValueError("Le type de ressource n'est pas compatible avec cette boutique")
            allowed = [stock_scope.value]
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        q = (
            self.db.table("organization_shop_article_stocks")
            .select(_SHOP_STOCK_SELECT_COLUMNS)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .in_("stock_scope", allowed)
            .order("created_at", desc=True)
        )
        if active_only is True:
            q = q.eq("active", True)
        elif active_only is False:
            q = q.eq("active", False)
        q = q.range(safe_offset, safe_offset + safe_limit - 1)
        return self._resource_rows_from_stock_rows(organization_id, list(q.execute().data or []))

    def get_stock_resource(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        resource_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        stock = self._get_resource_stock_row(organization_id, shop_id, resource_id)
        self._assert_resource_shop_scope(
            organization_id,
            shop_id,
            str(stock["stock_scope"]),
        )
        rows = self._resource_rows_from_stock_rows(organization_id, [stock])
        if not rows:
            raise LookupError("Ressource introuvable")
        return rows[0]

    def create_stock_resource(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        body: ShopStockResourceCreate,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        oid = str(organization_id)
        sid = str(shop_id)
        scope = body.stock_scope.value
        self._assert_resource_shop_scope(oid, sid, scope)
        primary = body.primary_image_storage_path.strip() if body.primary_image_storage_path else None
        additional = body.additional_image_storage_paths
        if primary is not None:
            self._assert_paths_belong_to_org(oid, primary, additional)
        elif additional:
            raise ValueError("Une image principale est requise si des images additionnelles sont fournies")

        article_payload = {
            "organization_id": oid,
            "name": body.name.strip(),
            "category": body.category.value,
            "unit_purchase_price": float(body.unit_purchase_price),
            "unit_sale_price": float(body.unit_rental_price or 0),
            "sale_currency": CurrencyCode.xof.value,
            "wholesale_prices": self._wholesale_to_db(body.rental_bulk_prices),
            "stock_quantity": 0,
            "alert_quantity": 0,
            "description": body.description,
            "primary_image_storage_path": primary,
            "additional_image_storage_paths": additional,
            "active": body.active,
            "resource_scope": scope,
        }
        ins = self.db.table("organization_articles").insert(article_payload).execute()
        rows = ins.data or []
        if not rows:
            raise RuntimeError("Creation de la ressource refusee")
        resource_id = str(rows[0]["id"])

        shop_ids = self._get_shop_ids_for_scope(oid, scope, sid)
        stock_rows = [
            {
                "organization_id": oid,
                "shop_id": compatible_shop_id,
                "article_id": resource_id,
                "stock_scope": scope,
                "stock_quantity": body.stock_quantity if compatible_shop_id == sid else 0,
                "reserved_quantity": 0,
                "alert_quantity": body.alert_quantity,
                "active": body.active,
            }
            for compatible_shop_id in shop_ids
        ]
        if stock_rows:
            self.db.table("organization_shop_article_stocks").insert(stock_rows).execute()
        return self.get_stock_resource(user_id, oid, sid, resource_id)

    def update_stock_resource(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        resource_id: str,
        body: ShopStockResourceUpdate,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        oid = str(organization_id)
        sid = str(shop_id)
        stock = self._get_resource_stock_row(oid, sid, resource_id)
        stock_scope = str(stock["stock_scope"])
        self._assert_resource_shop_scope(oid, sid, stock_scope)
        current = self.get_stock_resource(user_id, oid, sid, resource_id)

        article_updates: Dict[str, Any] = {}
        if body.name is not None:
            article_updates["name"] = body.name.strip()
        if body.category is not None:
            article_updates["category"] = body.category.value
        if body.unit_purchase_price is not None:
            article_updates["unit_purchase_price"] = float(body.unit_purchase_price)
        if body.unit_rental_price is not None:
            if stock_scope != OrganizationStockScope.rental_asset.value:
                raise ValueError("Le prix de location est reserve aux rental_asset")
            article_updates["unit_sale_price"] = float(body.unit_rental_price)
        if body.rental_currency is not None:
            if stock_scope != OrganizationStockScope.rental_asset.value:
                raise ValueError("La devise de location est reservee aux rental_asset")
            article_updates["sale_currency"] = CurrencyCode.xof.value
        if body.rental_bulk_prices is not None:
            if stock_scope != OrganizationStockScope.rental_asset.value:
                raise ValueError("Les prix de location en lot sont reserves aux rental_asset")
            article_updates["wholesale_prices"] = self._wholesale_to_db(
                body.rental_bulk_prices
            )
        if body.description is not None:
            article_updates["description"] = body.description
        if body.primary_image_storage_path is not None:
            article_updates["primary_image_storage_path"] = body.primary_image_storage_path.strip()
        if body.additional_image_storage_paths is not None:
            article_updates["additional_image_storage_paths"] = body.additional_image_storage_paths
        if body.active is not None:
            article_updates["active"] = body.active

        primary = article_updates.get(
            "primary_image_storage_path",
            current.get("primary_image_storage_path"),
        )
        additional = article_updates.get(
            "additional_image_storage_paths",
            current.get("additional_image_storage_paths") or [],
        )
        if primary:
            self._assert_paths_belong_to_org(oid, str(primary), list(additional))
        elif additional:
            raise ValueError("Une image principale est requise si des images additionnelles sont fournies")

        if article_updates:
            (
                self.db.table("organization_articles")
                .update(article_updates)
                .eq("id", resource_id)
                .eq("organization_id", oid)
                .execute()
            )

        stock_updates: Dict[str, Any] = {}
        if body.stock_quantity is not None:
            stock_updates["stock_quantity"] = body.stock_quantity
        if body.alert_quantity is not None:
            stock_updates["alert_quantity"] = body.alert_quantity
        if body.active is not None:
            stock_updates["active"] = body.active
        if stock_updates:
            (
                self.db.table("organization_shop_article_stocks")
                .update(stock_updates)
                .eq("id", stock["id"])
                .execute()
            )
        return self.get_stock_resource(user_id, oid, sid, resource_id)

    def _upsert_article_stock(
        self,
        organization_id: str,
        shop_id: str,
        article_id: str,
        *,
        stock_quantity: Optional[int] = None,
        alert_quantity: Optional[int] = None,
        active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._assert_sales_shop(organization_id, shop_id)
        existing = (
            self.db.table("organization_shop_article_stocks")
            .select(_SHOP_STOCK_SELECT_COLUMNS)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("article_id", article_id)
            .limit(1)
            .execute()
        )
        updates: Dict[str, Any] = {}
        if stock_quantity is not None:
            updates["stock_quantity"] = stock_quantity
        if alert_quantity is not None:
            updates["alert_quantity"] = alert_quantity
        if active is not None:
            updates["active"] = active

        existing_rows = existing.data or []
        if existing_rows:
            if updates:
                res = (
                    self.db.table("organization_shop_article_stocks")
                    .update(updates)
                    .eq("id", existing_rows[0]["id"])
                    .execute()
                )
                rows = res.data or []
                row = rows[0] if rows else {**existing_rows[0], **updates}
            else:
                row = existing_rows[0]
        else:
            payload = {
                "organization_id": organization_id,
                "shop_id": shop_id,
                "article_id": article_id,
                "stock_scope": "sales_item",
                "stock_quantity": stock_quantity or 0,
                "alert_quantity": alert_quantity or 0,
                "active": True if active is None else active,
            }
            res = (
                self.db.table("organization_shop_article_stocks")
                .insert(payload)
                .execute()
            )
            rows = res.data or []
            if not rows:
                raise RuntimeError("Creation du stock boutique refusee")
            row = rows[0]

        self._sync_legacy_article_stock(organization_id, shop_id, article_id, row)
        return row

    def list_articles(
        self,
        user_id: str,
        organization_id: str,
        active_only: Optional[bool] = None,
        shop_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if shop_id is None:
            raise ValueError("shop_id est requis pour lire le stock d'une boutique")
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        try:
            res = self.db.rpc(
                "list_shop_articles_with_stock",
                {
                    "p_user_id": user_id,
                    "p_organization_id": organization_id,
                    "p_shop_id": shop_id,
                    "p_active_only": active_only,
                    "p_limit": safe_limit,
                    "p_offset": safe_offset,
                },
            ).execute()
        except APIError as exc:
            message = str(getattr(exc, "message", None) or exc)
            if "membre actif" in message or "Acces refuse" in message:
                raise PermissionError(message) from exc
            if "Boutique de vente introuvable" in message:
                raise ValueError(message) from exc
            if "list_shop_articles_with_stock" in message:
                raise RuntimeError(
                    "Migration RPC articles + stock non appliquee. "
                    "Executer `supabase db push` puis relancer l'API."
                ) from exc
            raise
        return list(res.data or [])

    def get_article(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        shop_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        if shop_id is None:
            raise ValueError("shop_id est requis pour lire le stock d'une boutique")
        sid = shop_id
        self._assert_sales_shop(organization_id, sid)
        res = (
            self.db.table("organization_articles")
            .select(_ARTICLE_SELECT_COLUMNS)
            .eq("id", article_id)
            .eq("organization_id", organization_id)
            .eq("resource_scope", OrganizationStockScope.sales_item.value)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Article introuvable")
        return self._attach_shop_stock([rows[0]], organization_id, sid)[0]

    def assert_article_exists(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        allowed_scopes: Optional[List[str]] = None,
    ) -> None:
        self.assert_org_member(user_id, organization_id)
        scopes = allowed_scopes or [OrganizationStockScope.sales_item.value]
        res = (
            self.db.table("organization_articles")
            .select("id")
            .eq("id", article_id)
            .eq("organization_id", organization_id)
            .in_("resource_scope", scopes)
            .limit(1)
            .execute()
        )
        if not (res.data or []):
            raise LookupError("Article introuvable")

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
        if body.shop_id is None:
            raise ValueError("shop_id est requis pour creer un article de vente")
        default_shop_id = self._default_sales_shop_id(oid)
        target_shop_id = str(body.shop_id)
        self._assert_sales_shop(oid, target_shop_id)
        legacy_stock_quantity = (
            body.stock_quantity if target_shop_id == default_shop_id else 0
        )
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
            "sale_currency": CurrencyCode.xof.value,
            "wholesale_prices": self._wholesale_to_db(body.wholesale_prices),
            "stock_quantity": legacy_stock_quantity,
            "alert_quantity": body.alert_quantity,
            "description": body.description,
            "primary_image_storage_path": body.primary_image_storage_path.strip(),
            "additional_image_storage_paths": body.additional_image_storage_paths,
            "active": body.active,
            "resource_scope": OrganizationStockScope.sales_item.value,
        }
        ins = self.db.table("organization_articles").insert(row).execute()
        rows = ins.data or []
        if not rows:
            raise RuntimeError("Création de l'article refusée")
        article_id = str(rows[0]["id"])
        self._upsert_article_stock(
            oid,
            target_shop_id,
            article_id,
            stock_quantity=body.stock_quantity,
            alert_quantity=body.alert_quantity,
            active=body.active,
        )
        return self.get_article(user_id, oid, article_id, shop_id=target_shop_id)

    def update_article(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        body: OrganizationArticleUpdate,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        oid = str(organization_id)
        if body.shop_id is None:
            raise ValueError("shop_id est requis pour modifier un article de vente")
        target_shop_id = str(body.shop_id)
        self._assert_sales_shop(oid, target_shop_id)
        existing = self.get_article(user_id, oid, article_id, shop_id=target_shop_id)
        updates: Dict[str, Any] = {}
        if body.name is not None:
            updates["name"] = body.name.strip()
        if body.category is not None:
            updates["category"] = body.category.value
        if body.unit_sale_price is not None:
            updates["unit_sale_price"] = float(body.unit_sale_price)
        if body.sale_currency is not None:
            updates["sale_currency"] = CurrencyCode.xof.value
        if body.wholesale_prices is not None:
            updates["wholesale_prices"] = self._wholesale_to_db(body.wholesale_prices)
        if body.description is not None:
            updates["description"] = body.description
        if body.primary_image_storage_path is not None:
            updates["primary_image_storage_path"] = body.primary_image_storage_path.strip()
        if body.additional_image_storage_paths is not None:
            updates["additional_image_storage_paths"] = body.additional_image_storage_paths
        if body.active is not None:
            updates["active"] = body.active

        stock_update_requested = (
            body.stock_quantity is not None
            or body.alert_quantity is not None
            or body.active is not None
        )

        if not updates and not stock_update_requested:
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

        primary = updates.get(
            "primary_image_storage_path", existing["primary_image_storage_path"]
        )
        additional = updates.get(
            "additional_image_storage_paths",
            existing.get("additional_image_storage_paths") or [],
        )
        self._assert_paths_belong_to_org(oid, primary, list(additional))

        if updates:
            (
                self.db.table("organization_articles")
                .update(updates)
                .eq("id", article_id)
                .eq("organization_id", oid)
                .execute()
            )
        if stock_update_requested:
            self._upsert_article_stock(
                oid,
                target_shop_id,
                article_id,
                stock_quantity=body.stock_quantity,
                alert_quantity=body.alert_quantity,
                active=body.active,
            )
        return self.get_article(user_id, oid, article_id, shop_id=target_shop_id)

    def patch_article_stock(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
        shop_id: str,
        body: OrganizationArticleStockPatch,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        oid = str(organization_id)
        self._assert_sales_shop(oid, shop_id)
        _ = self.get_article(user_id, oid, article_id, shop_id=shop_id)
        self._upsert_article_stock(
            oid,
            shop_id,
            article_id,
            stock_quantity=body.stock_quantity,
            alert_quantity=body.alert_quantity,
            active=body.active,
        )
        return self.get_article(user_id, oid, article_id, shop_id=shop_id)

    def delete_article(
        self,
        user_id: str,
        organization_id: str,
        article_id: str,
    ) -> None:
        self.assert_article_exists(user_id, organization_id, article_id)
        self.db.table("organization_articles").delete().eq("id", article_id).eq(
            "organization_id", str(organization_id)
        ).execute()
