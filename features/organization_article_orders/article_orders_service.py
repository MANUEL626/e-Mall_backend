"""
Commandes d'articles : création, liste, réception (stock), annulation.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from postgrest.exceptions import APIError
from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_article_orders.article_orders_models import (
    ArticleOrderCreate,
    ArticleOrderReceiveRequest,
)
from features.organization_articles.organization_articles_models import CurrencyCode
from features.organization_subscriptions.organization_subscriptions_service import (
    OrganizationSubscriptionFeatureDenied,
    OrganizationSubscriptionService,
)

_ARTICLE_ORDER_SELECT = (
    "id,organization_id,shop_id,status,currency,note,created_at,updated_at,"
    "organization_article_order_lines("
    "id,order_id,article_id,quantity_ordered,unit_price,total_price,"
    "quantity_received,shortage_reason,received_at,created_at"
    ")"
)


class ArticleOrdersService:
    def __init__(self) -> None:
        self.db: Client = supabase_admin
        self.subscriptions = OrganizationSubscriptionService()

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

    def _organization_default_purchase_currency(self, organization_id: str) -> str:
        return CurrencyCode.xof.value

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

    def _normalize_money(self, value: Decimal, scale: str = "0.01") -> Decimal:
        return Decimal(str(value)).quantize(Decimal(scale), rounding=ROUND_HALF_UP)

    @staticmethod
    def _rpc_missing(exc: APIError) -> bool:
        code = getattr(exc, "code", None)
        return code in {"PGRST202", "PGRST204", "PGRST205"}

    def _normalize_rpc_order_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for row in rows:
            lines = row.get("organization_article_order_lines")
            if not isinstance(lines, list):
                row["organization_article_order_lines"] = []
            row["total_amount"] = self._normalize_money(
                Decimal(str(row.get("total_amount") or "0"))
            )
        return rows

    def _attach_total_amount(self, row: Dict[str, Any]) -> Dict[str, Any]:
        lines = row.get("organization_article_order_lines") or []
        total = sum(
            (Decimal(str(line.get("total_price") or "0")) for line in lines),
            Decimal("0"),
        )
        row["total_amount"] = self._normalize_money(total)
        return row

    def _select_order_with_lines(self, order_id: str) -> Dict[str, Any]:
        res = (
            self.db.table("organization_article_orders")
            .select(_ARTICLE_ORDER_SELECT)
            .eq("id", order_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Commande introuvable")
        row = rows[0]
        nested = row.get("organization_article_order_lines")
        if nested is None:
            row["organization_article_order_lines"] = []
        return self._attach_total_amount(row)

    def create_article_order(
        self,
        user_id: str,
        organization_id: str,
        body: ArticleOrderCreate,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        try:
            self.subscriptions.assert_feature_enabled(organization_id, "supplier_orders")
        except OrganizationSubscriptionFeatureDenied as exc:
            raise PermissionError(str(exc)) from exc
        oid = str(organization_id)
        if body.shop_id is None:
            raise ValueError("shop_id est requis pour creer une commande fournisseur")
        shop_id = str(body.shop_id)
        self._assert_sales_shop(oid, shop_id)
        currency = CurrencyCode.xof.value
        oins = (
            self.db.table("organization_article_orders")
            .insert(
                {
                    "organization_id": oid,
                    "shop_id": shop_id,
                    "status": "open",
                    "currency": currency,
                    "note": body.note.strip() if body.note and body.note.strip() else None,
                }
            )
            .execute()
        )
        orows = oins.data or []
        if not orows:
            raise RuntimeError("Création de la commande refusée")
        order_id = str(orows[0]["id"])

        line_rows = []
        for line in body.lines:
            total_price = self._normalize_money(line.total_price)
            unit_price = self._normalize_money(
                total_price / Decimal(line.quantity_ordered),
                "0.0001",
            )
            line_rows.append(
                {
                    "order_id": order_id,
                    "article_id": str(line.article_id),
                    "quantity_ordered": line.quantity_ordered,
                    "unit_price": str(unit_price),
                    "total_price": str(total_price),
                }
            )
        lins = (
            self.db.table("organization_article_order_lines")
            .insert(line_rows)
            .execute()
        )
        if not (lins.data or []) and line_rows:
            self.db.table("organization_article_orders").delete().eq("id", order_id).execute()
            raise RuntimeError("Création des lignes refusée")

        return self._select_order_with_lines(order_id)

    def list_article_orders(
        self,
        user_id: str,
        organization_id: str,
        status: Optional[str] = None,
        shop_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self.assert_org_member(user_id, organization_id)
        if shop_id is not None:
            self._assert_sales_shop(str(organization_id), shop_id)
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        try:
            res = self.db.rpc(
                "list_article_orders_with_lines",
                {
                    "p_user_id": user_id,
                    "p_organization_id": str(organization_id),
                    "p_shop_id": shop_id,
                    "p_status": status,
                    "p_limit": safe_limit,
                    "p_offset": safe_offset,
                },
            ).execute()
            return self._normalize_rpc_order_rows(list(res.data or []))
        except APIError as exc:
            if not self._rpc_missing(exc):
                raise

        q = (
            self.db.table("organization_article_orders")
            .select(_ARTICLE_ORDER_SELECT)
            .eq("organization_id", str(organization_id))
            .order("created_at", desc=True)
        )
        if status is not None:
            q = q.eq("status", status)
        if shop_id is not None:
            q = q.eq("shop_id", shop_id)
        res = q.range(safe_offset, safe_offset + safe_limit - 1).execute()
        rows = res.data or []
        for row in rows:
            if row.get("organization_article_order_lines") is None:
                row["organization_article_order_lines"] = []
            self._attach_total_amount(row)
        return rows

    def get_article_order(
        self,
        user_id: str,
        organization_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        row = self._select_order_with_lines(order_id)
        if str(row.get("organization_id")) != str(organization_id):
            raise LookupError("Commande introuvable")
        return row

    def receive_article_order(
        self,
        user_id: str,
        organization_id: str,
        order_id: str,
        body: ArticleOrderReceiveRequest,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        row = self._select_order_with_lines(order_id)
        if str(row.get("organization_id")) != str(organization_id):
            raise LookupError("Commande introuvable")
        if row.get("status") != "open":
            raise ValueError("Seule une commande « ouverte » peut être réceptionnée")

        db_lines: List[Dict[str, Any]] = row.get("organization_article_order_lines") or []
        if len(body.lines) != len(db_lines):
            raise ValueError(
                "Le corps doit contenir exactement une entrée par ligne de commande"
            )

        by_id = {str(l["id"]): l for l in db_lines}
        payload_ids = {str(x.line_id) for x in body.lines}
        if payload_ids != set(by_id.keys()):
            raise ValueError("Les line_id ne correspondent pas aux lignes de cette commande")

        for item in body.lines:
            lid = str(item.line_id)
            db_line = by_id[lid]
            if db_line.get("quantity_received") is not None:
                raise ValueError("Cette commande a déjà été réceptionnée (ou en partie)")
            qo = int(db_line["quantity_ordered"])
            qr = item.quantity_received
            if qr > qo:
                raise ValueError(
                    f"Quantité reçue ({qr}) supérieure à la quantité commandée ({qo})"
                )
            if qr < qo:
                reason = (item.shortage_reason or "").strip()
                if not reason:
                    raise ValueError(
                        "Motif obligatoire lorsque la quantité reçue est inférieure "
                        "à la quantité commandée"
                    )

        payload = [
            {
                "line_id": str(item.line_id),
                "quantity_received": item.quantity_received,
                "shortage_reason": item.shortage_reason,
            }
            for item in body.lines
        ]
        try:
            self.db.rpc(
                "receive_organization_article_order",
                {
                    "p_order_id": order_id,
                    "p_organization_id": str(organization_id),
                    "p_lines": payload,
                },
            ).execute()
        except Exception as exc:
            msg = str(exc)
            raise ValueError(msg) from exc

        return self._select_order_with_lines(order_id)

    def cancel_article_order(
        self,
        user_id: str,
        organization_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        row = self._select_order_with_lines(order_id)
        if str(row.get("organization_id")) != str(organization_id):
            raise LookupError("Commande introuvable")
        if row.get("status") != "open":
            raise ValueError("Seule une commande « ouverte » peut être annulée")

        for ln in row.get("organization_article_order_lines") or []:
            if ln.get("quantity_received") is not None:
                raise ValueError(
                    "Impossible d'annuler : des quantités ont déjà été réceptionnées"
                )

        upd = (
            self.db.table("organization_article_orders")
            .update({"status": "cancelled"})
            .eq("id", order_id)
            .eq("organization_id", str(organization_id))
            .eq("status", "open")
            .execute()
        )
        if not (upd.data or []):
            raise RuntimeError("Annulation refusée")

        return self._select_order_with_lines(order_id)
