"""
Commandes d'articles : création, liste, réception (stock), annulation.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

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
        res = (
            self.db.table("organizations")
            .select("default_currencies")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        defaults = rows[0].get("default_currencies") if rows else None
        purchase = (
            str(defaults.get("purchase") or CurrencyCode.eur.value).strip().lower()
            if isinstance(defaults, dict)
            else CurrencyCode.eur.value
        )
        allowed = {c.value for c in CurrencyCode}
        return purchase if purchase in allowed else CurrencyCode.eur.value

    def _normalize_money(self, value: Decimal, scale: str = "0.01") -> Decimal:
        return Decimal(str(value)).quantize(Decimal(scale), rounding=ROUND_HALF_UP)

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
            .select("*, organization_article_order_lines(*)")
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
        currency = (
            body.currency.value
            if body.currency is not None
            else self._organization_default_purchase_currency(oid)
        )
        oins = (
            self.db.table("organization_article_orders")
            .insert(
                {
                    "organization_id": oid,
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
    ) -> List[Dict[str, Any]]:
        self.assert_org_member(user_id, organization_id)
        q = (
            self.db.table("organization_article_orders")
            .select("*, organization_article_order_lines(*)")
            .eq("organization_id", str(organization_id))
            .order("created_at", desc=True)
        )
        if status is not None:
            q = q.eq("status", status)
        res = q.execute()
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
