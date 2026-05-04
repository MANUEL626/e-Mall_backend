"""
Liste de souhaits et paniers : accès via service role après validation JWT (aligné sur le catalogue).
"""

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from supabase import Client

from config.supabase_client import supabase_admin
from features.customers.customer_catalog_service import CustomerCatalogService


class CustomerWishlistCartService:
    _ARTICLE_FIELDS = (
        "id, organization_id, name, category, unit_sale_price, stock_status, "
        "primary_image_storage_path, additional_image_storage_paths, description, active"
    )

    def __init__(self) -> None:
        self.db: Client = supabase_admin
        self._catalog = CustomerCatalogService()

    def get_customer_id_for_user(self, user_id: str) -> Optional[str]:
        res = (
            self.db.table("customers")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return str(rows[0]["id"]) if rows else None

    def _get_active_article(self, organization_article_id: UUID) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("organization_articles")
            .select(self._ARTICLE_FIELDS)
            .eq("id", str(organization_article_id))
            .eq("active", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def list_wishlist(self, customer_id: str) -> List[Dict[str, Any]]:
        res = (
            self.db.table("customer_wishlist_items")
            .select("organization_article_id")
            .eq("customer_id", customer_id)
            .order("created_at", desc=True)
            .execute()
        )
        ids = [r["organization_article_id"] for r in (res.data or [])]
        if not ids:
            return []
        art = (
            self.db.table("organization_articles")
            .select(self._ARTICLE_FIELDS)
            .in_("id", ids)
            .eq("active", True)
            .execute()
        )
        rows = list(art.data or [])
        # Conserver l’ordre de la wishlist (seulement les articles encore actifs)
        id_set = {str(r["id"]) for r in rows}
        order = [i for i in ids if str(i) in id_set]
        by_id = {str(r["id"]): r for r in rows}
        ordered = [by_id[str(i)] for i in order if str(i) in by_id]
        return self._catalog.format_catalog_products(ordered)

    def add_wishlist_item(self, customer_id: str, organization_article_id: UUID) -> None:
        if not self._get_active_article(organization_article_id):
            raise ValueError("Article introuvable ou indisponible")
        existing = (
            self.db.table("customer_wishlist_items")
            .select("id")
            .eq("customer_id", customer_id)
            .eq("organization_article_id", str(organization_article_id))
            .limit(1)
            .execute()
        )
        if existing.data:
            return
        self.db.table("customer_wishlist_items").insert(
            {
                "customer_id": customer_id,
                "organization_article_id": str(organization_article_id),
            }
        ).execute()

    def remove_wishlist_item(self, customer_id: str, organization_article_id: UUID) -> bool:
        res = (
            self.db.table("customer_wishlist_items")
            .delete()
            .eq("customer_id", customer_id)
            .eq("organization_article_id", str(organization_article_id))
            .execute()
        )
        return bool(res.data)

    def _get_or_create_cart(self, customer_id: str, organization_id: str) -> str:
        existing = (
            self.db.table("customer_carts")
            .select("id")
            .eq("customer_id", customer_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            return str(rows[0]["id"])
        ins = (
            self.db.table("customer_carts")
            .insert(
                {
                    "customer_id": customer_id,
                    "organization_id": organization_id,
                }
            )
            .execute()
        )
        data = ins.data or []
        if not data:
            raise RuntimeError("Impossible de créer le panier")
        return str(data[0]["id"])

    def add_cart_item(
        self, customer_id: str, organization_article_id: UUID, quantity: int
    ) -> Tuple[str, str]:
        """
        Retourne (cart_id, line_id) après ajout ou fusion de quantité.
        """
        article = self._get_active_article(organization_article_id)
        if not article:
            raise ValueError("Article introuvable ou indisponible")
        org_id = str(article["organization_id"])
        cart_id = self._get_or_create_cart(customer_id, org_id)

        line = (
            self.db.table("customer_cart_items")
            .select("id, quantity")
            .eq("cart_id", cart_id)
            .eq("organization_article_id", str(organization_article_id))
            .limit(1)
            .execute()
        )
        lr = line.data or []
        if lr:
            lid = str(lr[0]["id"])
            new_q = int(lr[0]["quantity"]) + quantity
            upd = (
                self.db.table("customer_cart_items")
                .update({"quantity": new_q})
                .eq("id", lid)
                .execute()
            )
            if not (upd.data or []):
                raise RuntimeError("Mise à jour de ligne impossible")
            return cart_id, lid

        ins = (
            self.db.table("customer_cart_items")
            .insert(
                {
                    "cart_id": cart_id,
                    "organization_article_id": str(organization_article_id),
                    "quantity": quantity,
                }
            )
            .execute()
        )
        data = ins.data or []
        if not data:
            raise RuntimeError("Impossible d’ajouter la ligne")
        return cart_id, str(data[0]["id"])

    def set_cart_line_quantity(
        self, customer_id: str, line_id: UUID, quantity: int
    ) -> None:
        line = (
            self.db.table("customer_cart_items")
            .select("id, cart_id")
            .eq("id", str(line_id))
            .limit(1)
            .execute()
        )
        lr = line.data or []
        if not lr:
            raise ValueError("Ligne introuvable")
        cart_id = str(lr[0]["cart_id"])
        cart = (
            self.db.table("customer_carts")
            .select("id")
            .eq("id", cart_id)
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        if not (cart.data or []):
            raise ValueError("Ligne introuvable")

        self.db.table("customer_cart_items").update({"quantity": quantity}).eq(
            "id", str(line_id)
        ).execute()

    def remove_cart_line(self, customer_id: str, line_id: UUID) -> bool:
        line = (
            self.db.table("customer_cart_items")
            .select("id, cart_id")
            .eq("id", str(line_id))
            .limit(1)
            .execute()
        )
        lr = line.data or []
        if not lr:
            return False
        cart_id = str(lr[0]["cart_id"])
        cart = (
            self.db.table("customer_carts")
            .select("id")
            .eq("id", cart_id)
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        if not (cart.data or []):
            return False
        self.db.table("customer_cart_items").delete().eq("id", str(line_id)).execute()
        remaining = (
            self.db.table("customer_cart_items")
            .select("id", count="exact")
            .eq("cart_id", cart_id)
            .execute()
        )
        cnt = int(remaining.count) if remaining.count is not None else len(remaining.data or [])
        if cnt == 0:
            self.db.table("customer_carts").delete().eq("id", cart_id).execute()
        return True

    def clear_cart(self, customer_id: str, cart_id: UUID) -> bool:
        cart = (
            self.db.table("customer_carts")
            .select("id")
            .eq("id", str(cart_id))
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        if not (cart.data or []):
            return False
        self.db.table("customer_cart_items").delete().eq("cart_id", str(cart_id)).execute()
        self.db.table("customer_carts").delete().eq("id", str(cart_id)).execute()
        return True

    def list_carts(self, customer_id: str) -> List[Dict[str, Any]]:
        carts_res = (
            self.db.table("customer_carts")
            .select("id, organization_id, updated_at")
            .eq("customer_id", customer_id)
            .order("updated_at", desc=True)
            .execute()
        )
        carts = list(carts_res.data or [])
        if not carts:
            return []

        cart_ids = [str(c["id"]) for c in carts]
        lines_res = (
            self.db.table("customer_cart_items")
            .select("id, cart_id, organization_article_id, quantity")
            .in_("cart_id", cart_ids)
            .execute()
        )
        lines = list(lines_res.data or [])
        article_ids = list({str(l["organization_article_id"]) for l in lines})
        if article_ids:
            art_res = (
                self.db.table("organization_articles")
                .select(self._ARTICLE_FIELDS)
                .in_("id", article_ids)
                .execute()
            )
            article_rows = list(art_res.data or [])
        else:
            article_rows = []
        products = self._catalog.format_catalog_products(article_rows)
        prod_by_id = {str(p["id"]): p for p in products}

        org_ids = list({str(c["organization_id"]) for c in carts})
        org_names = self._org_names(org_ids)

        lines_by_cart: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in cart_ids}
        for ln in lines:
            cid = str(ln["cart_id"])
            if cid in lines_by_cart:
                lines_by_cart[cid].append(ln)

        out: List[Dict[str, Any]] = []
        for c in carts:
            cid = str(c["id"])
            oid = str(c["organization_id"])
            item_payloads: List[Dict[str, Any]] = []
            for ln in lines_by_cart.get(cid, []):
                aid = str(ln["organization_article_id"])
                p = prod_by_id.get(aid)
                if not p:
                    continue
                item_payloads.append(
                    {
                        "line_id": ln["id"],
                        "quantity": int(ln["quantity"]),
                        "product": p,
                    }
                )
            out.append(
                {
                    "cart_id": c["id"],
                    "organization_id": c["organization_id"],
                    "organization_name": org_names.get(oid, ""),
                    "updated_at": c["updated_at"],
                    "items": item_payloads,
                }
            )
        return out

    def _org_names(self, organization_ids: List[str]) -> Dict[str, str]:
        if not organization_ids:
            return {}
        res = (
            self.db.table("organizations")
            .select("id, name")
            .in_("id", organization_ids)
            .execute()
        )
        return {str(o["id"]): (o.get("name") or "") for o in (res.data or [])}
