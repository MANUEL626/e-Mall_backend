"""
Ventes client : commandes, réservations (trigger SQL), QR, walk-in, livraison.
Opérations via service_role après contrôle JWT côté routes.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from supabase import Client
from postgrest.exceptions import APIError

from config.supabase_client import supabase_admin
from features.customers.customer_analytics_service import CustomerAnalyticsService
from features.customer_sales.customer_sales_models import (
    ConfirmReceiptBody,
    CustomerSaleFulfillment,
    CustomerSaleOrderCreate,
    CustomerSaleOrderStatus,
    DeliveryTrackPointIn,
    PatchOrderStatusBody,
    StatusGroup,
    WalkInSaleCreate,
)
from features.organization_articles.organization_articles_models import ArticleCategory, CurrencyCode
from features.organization_subscriptions.organization_subscriptions_service import (
    OrganizationSubscriptionFeatureDenied,
    OrganizationSubscriptionLimitExceeded,
    OrganizationSubscriptionService,
)


_logger = logging.getLogger(__name__)


def _qr_pepper() -> str:
    return (
        os.getenv("CUSTOMER_SALE_QR_PEPPER", "").strip()
        or "dev-customer-sale-qr-pepper-change-me"
    )


def hash_receipt_secret(secret: str) -> str:
    return hashlib.sha256(f"{secret}{_qr_pepper()}".encode()).hexdigest()


_STATUSES_FOR_GROUP: Dict[StatusGroup, List[str]] = {
    StatusGroup.in_progress: ["pending", "in_progress"],
    StatusGroup.in_delivery: ["in_delivery"],
    StatusGroup.cancelled: ["cancelled"],
    StatusGroup.completed: ["completed"],
}


class CustomerSalesService:
    def __init__(self) -> None:
        self.db: Client = supabase_admin
        self.analytics = CustomerAnalyticsService()
        self.subscriptions = OrganizationSubscriptionService()

    # --- helpers ---

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

    def _get_member(
        self, user_id: str, organization_id: str
    ) -> Dict[str, Any]:
        res = (
            self.db.table("members")
            .select("id,member_role,member_type,activity_status")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise PermissionError("Accès refusé : membre introuvable pour cette organisation")
        return rows[0]

    def _member_by_id(
        self, member_id: str, organization_id: str
    ) -> Dict[str, Any]:
        res = (
            self.db.table("members")
            .select("id,member_role,user_id,organization_id,activity_status")
            .eq("id", member_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Membre livreur introuvable")
        return rows[0]

    @staticmethod
    def _status_filter(status_group: Optional[StatusGroup]) -> Optional[List[str]]:
        if status_group is None:
            return None
        return _STATUSES_FOR_GROUP.get(status_group)

    # --- customer_params ---

    @staticmethod
    def _default_customer_extra() -> Dict[str, Any]:
        return {"country": None, "interests": []}

    @staticmethod
    def _clean_customer_extra(extra: Optional[dict]) -> Dict[str, Any]:
        cleaned = CustomerSalesService._default_customer_extra()
        if isinstance(extra, dict):
            cleaned.update(extra)

        country = cleaned.get("country")
        if isinstance(country, str) and country.strip():
            cleaned["country"] = country.strip()
        else:
            cleaned["country"] = None

        allowed = {category.value for category in ArticleCategory}
        raw_interests = cleaned.get("interests")
        if not isinstance(raw_interests, list):
            raw_interests = []
        cleaned["interests"] = [
            str(item).strip()
            for item in raw_interests
            if str(item).strip() in allowed
        ]
        return cleaned

    @classmethod
    def _customer_params_out(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        extra = cls._clean_customer_extra(out.get("extra"))
        out["extra"] = extra
        out["country"] = extra.get("country")
        out["interests"] = extra.get("interests") or []
        return out

    def get_customer_params(self, customer_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("customer_params")
            .select("*")
            .eq("customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return self._customer_params_out(rows[0]) if rows else None

    def get_or_create_customer_params(self, customer_id: str) -> Dict[str, Any]:
        existing = self.get_customer_params(customer_id)
        if existing:
            return existing
        return self.upsert_customer_params(
            customer_id,
            locale="fr",
            extra=self._default_customer_extra(),
        )

    def upsert_customer_params(
        self,
        customer_id: str,
        locale: Optional[str] = None,
        default_longitude: Optional[float] = None,
        default_latitude: Optional[float] = None,
        country: Optional[str] = None,
        interests: Optional[List[ArticleCategory]] = None,
        extra: Optional[dict] = None,
    ) -> Dict[str, Any]:
        existing = self.get_customer_params(customer_id)
        payload: Dict[str, Any] = {"customer_id": customer_id}
        if locale is not None:
            payload["locale"] = locale
        if default_longitude is not None:
            payload["default_longitude"] = default_longitude
        if default_latitude is not None:
            payload["default_latitude"] = default_latitude
        merged_extra = self._clean_customer_extra(
            existing.get("extra") if existing else None
        )
        if extra is not None:
            merged_extra.update(extra)
            merged_extra = self._clean_customer_extra(merged_extra)
        if country is not None:
            country_clean = country.strip()
            merged_extra["country"] = country_clean if country_clean else None
        if interests is not None:
            merged_extra["interests"] = [
                item.value if hasattr(item, "value") else str(item)
                for item in interests
            ]
        payload["extra"] = self._clean_customer_extra(merged_extra)

        if existing:
            upd = {k: v for k, v in payload.items() if k != "customer_id"}
            if not upd:
                return existing
            res = (
                self.db.table("customer_params")
                .update(upd)
                .eq("customer_id", customer_id)
                .execute()
            )
        else:
            res = self.db.table("customer_params").insert(payload).execute()
        rows = res.data or []
        if not rows:
            raise RuntimeError("Mise à jour customer_params refusée")
        return self._customer_params_out(rows[0])

    # --- vente client ---

    def _fetch_articles_for_order(
        self, organization_id: str, article_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        res = (
            self.db.table("organization_articles")
            .select(
                "id,organization_id,name,unit_sale_price,sale_currency,stock_quantity,reserved_quantity,active"
            )
            .eq("organization_id", organization_id)
            .in_("id", article_ids)
            .execute()
        )
        rows = res.data or []
        by_id = {str(r["id"]): r for r in rows}
        missing = set(article_ids) - set(by_id.keys())
        if missing:
            raise ValueError("Articles introuvables pour cette organisation")
        for aid, r in by_id.items():
            if not r.get("active"):
                raise ValueError(f"Article inactif : {aid}")
        return by_id

    def _organization_default_sale_currency(self, organization_id: str) -> str:
        res = (
            self.db.table("organizations")
            .select("default_currencies")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        defaults = rows[0].get("default_currencies") if rows else None
        sale = (
            str(defaults.get("sale") or CurrencyCode.xof.value).strip().lower()
            if isinstance(defaults, dict)
            else CurrencyCode.xof.value
        )
        allowed = {c.value for c in CurrencyCode}
        return sale if sale in allowed else CurrencyCode.xof.value

    def _org_has_active_delivery_member(self, organization_id: str) -> bool:
        """
        Au moins un livreur utilisable : membre actif dans l'org (members.activity_status)
        ET compte utilisateur actif (users.activity_status).
        """
        mres = (
            self.db.table("members")
            .select("user_id")
            .eq("organization_id", organization_id)
            .eq("member_role", "delivery_management")
            .eq("activity_status", True)
            .execute()
        )
        rows = mres.data or []
        if not rows:
            return False
        uids = [str(r["user_id"]) for r in rows]
        ures = (
            self.db.table("users")
            .select("id")
            .in_("id", uids)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        return bool(ures.data)

    def create_customer_sale_order(
        self, user_id: str, body: CustomerSaleOrderCreate
    ) -> Dict[str, Any]:
        cid = self.get_customer_id_for_user(user_id)
        if not cid:
            raise LookupError("Profil client introuvable")

        if body.fulfillment_type == CustomerSaleFulfillment.walk_in_offline:
            raise ValueError("Utiliser l'endpoint marchand walk-in pour ce type")

        oid = str(body.organization_id)
        if body.fulfillment_type in (
            CustomerSaleFulfillment.pickup,
            CustomerSaleFulfillment.delivery,
        ):
            try:
                self.subscriptions.assert_feature_enabled(oid, "pickup_delivery")
            except OrganizationSubscriptionFeatureDenied as exc:
                raise PermissionError(str(exc)) from exc
        lon = body.delivery_longitude
        lat = body.delivery_latitude
        if body.fulfillment_type == CustomerSaleFulfillment.delivery:
            if lon is None or lat is None:
                params = self.get_customer_params(cid)
                if params:
                    lon = lon if lon is not None else params.get("default_longitude")
                    lat = lat if lat is not None else params.get("default_latitude")
            if lon is None or lat is None:
                raise ValueError(
                    "Livraison : renseigner delivery_longitude et delivery_latitude "
                    "(ou les enregistrer dans les paramètres client)."
                )
            if not self._org_has_active_delivery_member(oid):
                raise ValueError(
                    "Aucun livreur actif n'est disponible pour cette organisation "
                    "(compte désactivé côté boutique ou utilisateur). "
                    "Passez votre commande en retrait sur place (pickup)."
                )

        article_ids = [str(l.article_id) for l in body.lines]
        arts = self._fetch_articles_for_order(oid, article_ids)
        default_currency = self._organization_default_sale_currency(oid)
        line_currencies = {
            str(arts[str(line.article_id)].get("sale_currency") or default_currency).lower()
            for line in body.lines
        }
        if len(line_currencies) > 1:
            raise ValueError("Une commande ne peut pas melanger plusieurs devises")
        order_currency = next(iter(line_currencies), default_currency)

        oins = (
            self.db.table("organization_customer_sale_orders")
            .insert(
                {
                    "organization_id": oid,
                    "fulfillment_type": body.fulfillment_type.value,
                    "customer_id": cid,
                    "status": CustomerSaleOrderStatus.pending.value,
                    "currency": order_currency,
                    "delivery_longitude": lon,
                    "delivery_latitude": lat,
                    "notes": body.notes.strip() if body.notes else None,
                }
            )
            .execute()
        )
        orows = oins.data or []
        if not orows:
            raise RuntimeError("Création de commande refusée")
        order_id = str(orows[0]["id"])

        line_rows = []
        for ln in body.lines:
            aid = str(ln.article_id)
            price = arts[aid]["unit_sale_price"]
            currency = str(arts[aid].get("sale_currency") or order_currency).lower()
            line_rows.append(
                {
                    "order_id": order_id,
                    "article_id": aid,
                    "quantity": ln.quantity,
                    "unit_price_snapshot": float(price),
                    "currency_snapshot": currency,
                }
            )

        lins = (
            self.db.table("organization_customer_sale_order_lines")
            .insert(line_rows)
            .execute()
        )
        if not (lins.data or []) and line_rows:
            self.db.table("organization_customer_sale_orders").delete().eq(
                "id", order_id
            ).execute()
            raise RuntimeError("Insertion des lignes refusée")

        self._insert_status_event(
            order_id,
            None,
            CustomerSaleOrderStatus.pending,
            note=None,
            created_by_user_id=user_id,
        )

        return self._select_order_with_lines(order_id)

    def _insert_status_event(
        self,
        order_id: str,
        from_status: Optional[CustomerSaleOrderStatus],
        to_status: CustomerSaleOrderStatus,
        note: Optional[str],
        created_by_user_id: Optional[str],
    ) -> None:
        payload = {
            "order_id": order_id,
            "from_status": from_status.value if from_status else None,
            "to_status": to_status.value,
            "note": note,
            "created_by_user_id": created_by_user_id,
        }
        self.db.table("organization_customer_sale_order_status_events").insert(
            payload
        ).execute()

    def _select_order_with_lines(self, order_id: str) -> Dict[str, Any]:
        res = (
            self.db.table("organization_customer_sale_orders")
            .select("*")
            .eq("id", order_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Commande introuvable")
        row = dict(rows[0])
        lres = (
            self.db.table("organization_customer_sale_order_lines")
            .select("*")
            .eq("order_id", order_id)
            .execute()
        )
        lines = list(lres.data or [])
        article_ids = [str(x["article_id"]) for x in lines if x.get("article_id")]
        article_name_by_id: Dict[str, str] = {}
        if article_ids:
            ares = (
                self.db.table("organization_articles")
                .select("id,name")
                .in_("id", article_ids)
                .execute()
            )
            for a in ares.data or []:
                article_name_by_id[str(a["id"])] = str(a.get("name") or "")
        for ln in lines:
            aid = str(ln.get("article_id"))
            ln["article_name"] = article_name_by_id.get(aid)
        row["organization_customer_sale_order_lines"] = lines
        self._attach_order_totals(row)
        return row

    def _attach_lines_to_orders(
        self,
        orders: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not orders:
            return []

        order_ids = [str(order["id"]) for order in orders if order.get("id")]
        if not order_ids:
            return orders

        lres = (
            self.db.table("organization_customer_sale_order_lines")
            .select("*")
            .in_("order_id", order_ids)
            .execute()
        )
        lines = list(lres.data or [])
        article_ids = list(
            {str(line["article_id"]) for line in lines if line.get("article_id")}
        )

        article_name_by_id: Dict[str, str] = {}
        if article_ids:
            ares = (
                self.db.table("organization_articles")
                .select("id,name")
                .in_("id", article_ids)
                .execute()
            )
            for article in ares.data or []:
                article_name_by_id[str(article["id"])] = str(article.get("name") or "")

        lines_by_order: Dict[str, List[Dict[str, Any]]] = {
            order_id: [] for order_id in order_ids
        }
        for line in lines:
            aid = str(line.get("article_id"))
            line["article_name"] = article_name_by_id.get(aid)
            lines_by_order.setdefault(str(line["order_id"]), []).append(line)

        out: List[Dict[str, Any]] = []
        for order in orders:
            row = dict(order)
            row["organization_customer_sale_order_lines"] = lines_by_order.get(
                str(order["id"]),
                [],
            )
            self._attach_order_totals(row)
            out.append(row)
        return out

    @staticmethod
    def _attach_order_totals(order_row: Dict[str, Any]) -> None:
        lines = list(order_row.get("organization_customer_sale_order_lines") or [])
        subtotal = Decimal("0")
        total_items = 0
        for line in lines:
            qty = int(line.get("quantity") or 0)
            unit = Decimal(str(line.get("unit_price_snapshot") or "0"))
            subtotal += unit * qty
            total_items += qty
        order_row["subtotal_amount"] = subtotal.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        order_row["total_items"] = total_items
        order_row["total_lines"] = len(lines)

    def list_customer_orders(
        self,
        user_id: str,
        status_group: Optional[StatusGroup] = None,
    ) -> List[Dict[str, Any]]:
        cid = self.get_customer_id_for_user(user_id)
        if not cid:
            raise LookupError("Profil client introuvable")
        q = (
            self.db.table("organization_customer_sale_orders")
            .select("*")
            .eq("customer_id", cid)
            .order("created_at", desc=True)
        )
        statuses = self._status_filter(status_group)
        if statuses is not None:
            q = q.in_("status", list(statuses))
        res = q.execute()
        rows = res.data or []
        return self._attach_lines_to_orders(list(rows))

    def get_customer_order(self, user_id: str, order_id: str) -> Dict[str, Any]:
        cid = self.get_customer_id_for_user(user_id)
        if not cid:
            raise LookupError("Profil client introuvable")
        row = self._select_order_with_lines(order_id)
        if str(row.get("customer_id")) != cid:
            raise LookupError("Commande introuvable")
        return row

    def list_order_history(self, user_id: str, order_id: str) -> List[Dict[str, Any]]:
        self.get_customer_order(user_id, order_id)
        res = (
            self.db.table("organization_customer_sale_order_status_events")
            .select("*")
            .eq("order_id", order_id)
            .order("created_at")
            .execute()
        )
        return list(res.data or [])

    def confirm_receipt(
        self, user_id: str, order_id: str, body: ConfirmReceiptBody
    ) -> Dict[str, Any]:
        cid = self.get_customer_id_for_user(user_id)
        if not cid:
            raise LookupError("Profil client introuvable")

        row = self._select_order_with_lines(order_id)
        if str(row.get("customer_id")) != cid:
            raise PermissionError("Commande inaccessible")

        if row["fulfillment_type"] == CustomerSaleFulfillment.walk_in_offline.value:
            raise ValueError("Flux non applicable")

        tok_res = (
            self.db.table("customer_sale_order_receipt_tokens")
            .select("secret_hash")
            .eq("order_id", order_id)
            .limit(1)
            .execute()
        )
        tok_rows = tok_res.data or []
        if not tok_rows:
            raise LookupError("Jeton de réception introuvable ; demander au marchand.")
        if hash_receipt_secret(body.secret) != tok_rows[0]["secret_hash"]:
            raise ValueError("Code de réception invalide")

        note = body.note.strip() if body.note and body.note.strip() else None
        try:
            self.db.rpc(
                "finalize_customer_sale_receipt",
                {"p_order_id": order_id, "p_note": note},
            ).execute()
        except Exception as exc:
            raise ValueError(str(exc)) from exc

        completed_order = self._select_order_with_lines(order_id)
        self._create_purchase_trend_events(completed_order)
        return completed_order

    # --- organisation ---

    def list_org_orders(
        self,
        user_id: str,
        organization_id: str,
        status_group: Optional[StatusGroup] = None,
    ) -> List[Dict[str, Any]]:
        self.assert_org_member(user_id, organization_id)
        q = (
            self.db.table("organization_customer_sale_orders")
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=True)
        )
        statuses = self._status_filter(status_group)
        if statuses is not None:
            q = q.in_("status", list(statuses))
        res = q.execute()
        rows = res.data or []
        return self._attach_lines_to_orders(list(rows))

    def get_org_order(
        self, user_id: str, organization_id: str, order_id: str
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        row = self._select_order_with_lines(order_id)
        if str(row.get("organization_id")) != organization_id:
            raise LookupError("Commande introuvable")
        return row

    def list_org_order_history(
        self, user_id: str, organization_id: str, order_id: str
    ) -> List[Dict[str, Any]]:
        self.get_org_order(user_id, organization_id, order_id)
        res = (
            self.db.table("organization_customer_sale_order_status_events")
            .select("*")
            .eq("order_id", order_id)
            .order("created_at")
            .execute()
        )
        return list(res.data or [])

    def walk_in_sale(
        self, user_id: str, organization_id: str, body: WalkInSaleCreate
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        try:
            self.subscriptions.assert_usage_below_limit(
                organization_id,
                "monthly_walk_in_sales",
                increment=1,
            )
        except OrganizationSubscriptionLimitExceeded as exc:
            raise ValueError(str(exc)) from exc

        article_ids = [str(l.article_id) for l in body.lines]
        arts = self._fetch_articles_for_order(organization_id, article_ids)
        default_currency = self._organization_default_sale_currency(organization_id)
        line_currencies = {
            str(arts[str(line.article_id)].get("sale_currency") or default_currency).lower()
            for line in body.lines
        }
        if len(line_currencies) > 1:
            raise ValueError("Une vente magasin ne peut pas melanger plusieurs devises")
        order_currency = next(iter(line_currencies), default_currency)
        for ln in body.lines:
            aid = str(ln.article_id)
            art = arts[aid]
            stock_qty = int(art.get("stock_quantity") or 0)
            reserved_qty = int(art.get("reserved_quantity") or 0)
            available_qty = stock_qty - reserved_qty
            if ln.quantity > available_qty:
                article_name = str(art.get("name") or aid)
                raise ValueError(
                    "Stock insuffisant pour l'article "
                    f"'{article_name}' (demandé: {ln.quantity}, disponible: {available_qty})."
                )

        oins = (
            self.db.table("organization_customer_sale_orders")
            .insert(
                {
                    "organization_id": organization_id,
                    "fulfillment_type": CustomerSaleFulfillment.walk_in_offline.value,
                    "customer_id": None,
                    "status": CustomerSaleOrderStatus.completed.value,
                    "currency": order_currency,
                    "notes": body.notes.strip() if body.notes else None,
                    "external_customer_label": body.external_customer_label.strip()
                    if body.external_customer_label
                    else None,
                }
            )
            .execute()
        )
        orows = oins.data or []
        if not orows:
            raise RuntimeError("Création refusée")
        order_id = str(orows[0]["id"])

        line_rows = []
        for ln in body.lines:
            aid = str(ln.article_id)
            price = arts[aid]["unit_sale_price"]
            currency = str(arts[aid].get("sale_currency") or order_currency).lower()
            line_rows.append(
                {
                    "order_id": order_id,
                    "article_id": aid,
                    "quantity": ln.quantity,
                    "unit_price_snapshot": float(price),
                    "currency_snapshot": currency,
                }
            )

        try:
            lins = (
                self.db.table("organization_customer_sale_order_lines")
                .insert(line_rows)
                .execute()
            )
        except APIError as exc:
            # Ex: check SQL 23514 "Stock insuffisant pour la vente magasin"
            msg = (
                str(exc.message)
                if getattr(exc, "message", None)
                else "Vente magasin refusée"
            )
            self.db.table("organization_customer_sale_orders").delete().eq(
                "id", order_id
            ).execute()
            raise ValueError(msg) from exc
        if not (lins.data or []) and line_rows:
            self.db.table("organization_customer_sale_orders").delete().eq(
                "id", order_id
            ).execute()
            raise RuntimeError("Insertion des lignes refusée")

        self._insert_status_event(
            order_id,
            None,
            CustomerSaleOrderStatus.completed,
            note=None,
            created_by_user_id=user_id,
        )

        completed_order = self._select_order_with_lines(order_id)
        self._create_purchase_trend_events(completed_order)
        return completed_order

    def _create_purchase_trend_events(self, order_row: Dict[str, Any]) -> None:
        try:
            self.analytics.create_purchase_events_for_order(order_row)
        except Exception:
            _logger.exception(
                "Failed to create purchase trend events for customer sale order %s",
                order_row.get("id"),
            )

    def patch_order_status(
        self,
        user_id: str,
        organization_id: str,
        order_id: str,
        body: PatchOrderStatusBody,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        row = self.get_org_order(user_id, organization_id, order_id)
        if row["fulfillment_type"] == CustomerSaleFulfillment.walk_in_offline.value:
            raise ValueError(
                "Les ventes magasin (walk-in) sont immédiatement terminées ; pas de changement de statut."
            )
        old = CustomerSaleOrderStatus(row["status"])
        new = body.status

        if row["fulfillment_type"] in (
            CustomerSaleFulfillment.pickup.value,
            CustomerSaleFulfillment.delivery.value,
        ):
            if new == CustomerSaleOrderStatus.completed:
                raise ValueError(
                    "Passage à « completed » uniquement via confirmation client (scan QR)."
                )

        self._validate_status_transition(
            row["fulfillment_type"],
            old,
            new,
        )

        upd = (
            self.db.table("organization_customer_sale_orders")
            .update({"status": new.value})
            .eq("id", order_id)
            .execute()
        )
        if not (upd.data or []):
            raise RuntimeError("Mise à jour refusée")

        note = body.note.strip() if body.note and body.note.strip() else None
        self._insert_status_event(
            order_id,
            old,
            new,
            note=note,
            created_by_user_id=user_id,
        )

        return self._select_order_with_lines(order_id)

    @staticmethod
    def _validate_status_transition(
        fulfillment_type: str,
        old: CustomerSaleOrderStatus,
        new: CustomerSaleOrderStatus,
    ) -> None:
        allowed: Dict[CustomerSaleOrderStatus, Set[CustomerSaleOrderStatus]] = {
            CustomerSaleOrderStatus.pending: {
                CustomerSaleOrderStatus.in_progress,
                CustomerSaleOrderStatus.cancelled,
            },
            CustomerSaleOrderStatus.in_progress: {
                CustomerSaleOrderStatus.in_delivery,
                CustomerSaleOrderStatus.cancelled,
            },
            CustomerSaleOrderStatus.in_delivery: {
                CustomerSaleOrderStatus.cancelled,
            },
            CustomerSaleOrderStatus.cancelled: set(),
            CustomerSaleOrderStatus.completed: set(),
        }
        if fulfillment_type == CustomerSaleFulfillment.pickup.value:
            allowed[CustomerSaleOrderStatus.in_progress].discard(
                CustomerSaleOrderStatus.in_delivery
            )
        if new == old:
            return
        ok = allowed.get(old, set())
        if new not in ok:
            raise ValueError(f"Transition de statut interdite : {old.value} → {new.value}")

    def _validate_order_row_for_token(self, row: Dict[str, Any]) -> None:
        if row["fulfillment_type"] == CustomerSaleFulfillment.walk_in_offline.value:
            raise ValueError("Pas de jeton QR pour une vente magasin hors appli")
        st = row["status"]
        if st in (
            CustomerSaleOrderStatus.completed.value,
            CustomerSaleOrderStatus.cancelled.value,
        ):
            raise ValueError("Commande déjà clôturée")

    def _mint_receipt_token(self, order_id: str, organization_id: str) -> Dict[str, Any]:
        secret = secrets.token_urlsafe(32)
        sec_hash = hash_receipt_secret(secret)

        self.db.table("customer_sale_order_receipt_tokens").delete().eq(
            "order_id", order_id
        ).execute()

        ins = (
            self.db.table("customer_sale_order_receipt_tokens")
            .insert(
                {
                    "order_id": order_id,
                    "secret_hash": sec_hash,
                }
            )
            .execute()
        )
        if not (ins.data or []):
            raise RuntimeError("Création du jeton refusée")

        qr_payload = f"emall:order:{order_id}:{secret}"
        return {
            "order_id": order_id,
            "organization_id": organization_id,
            "secret": secret,
            "qr_payload": qr_payload,
            "expires_at": None,
        }

    def upsert_receipt_token(
        self, user_id: str, organization_id: str, order_id: str
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        row = self.get_org_order(user_id, organization_id, order_id)
        self._validate_order_row_for_token(row)
        return self._mint_receipt_token(order_id, organization_id)

    def get_pickup_qr_payload(
        self, user_id: str, organization_id: str, order_id: str
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        row = self.get_org_order(user_id, organization_id, order_id)
        if row["fulfillment_type"] != CustomerSaleFulfillment.pickup.value:
            raise ValueError("Cette commande n'est pas en retrait sur place")
        self._validate_order_row_for_token(row)
        return self._mint_receipt_token(order_id, organization_id)

    def assign_delivery(
        self,
        user_id: str,
        organization_id: str,
        order_id: str,
        member_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        try:
            self.subscriptions.assert_feature_enabled(
                organization_id,
                "delivery_assignment",
            )
        except OrganizationSubscriptionFeatureDenied as exc:
            raise PermissionError(str(exc)) from exc
        row = self.get_org_order(user_id, organization_id, order_id)
        if row["fulfillment_type"] != CustomerSaleFulfillment.delivery.value:
            raise ValueError("Commande non livrable")
        if row["status"] in (
            CustomerSaleOrderStatus.completed.value,
            CustomerSaleOrderStatus.cancelled.value,
        ):
            raise ValueError("Impossible d'assigner sur une commande clôturée")

        assignee = self._member_by_id(member_id, organization_id)
        if assignee.get("member_role") != "delivery_management":
            raise ValueError("Le membre assigné doit avoir le rôle delivery_management")

        self.db.table("organization_customer_sale_orders").update(
            {
                "assigned_delivery_member_id": member_id,
                "status": CustomerSaleOrderStatus.in_delivery.value,
            }
        ).eq("id", order_id).execute()

        old = CustomerSaleOrderStatus(row["status"])
        self._insert_status_event(
            order_id,
            old,
            CustomerSaleOrderStatus.in_delivery,
            note="Assignation livreur",
            created_by_user_id=user_id,
        )

        return self._select_order_with_lines(order_id)

    def get_delivery_qr_payload(
        self, user_id: str, organization_id: str, order_id: str
    ) -> Dict[str, Any]:
        row = self.get_org_order(user_id, organization_id, order_id)
        if row["fulfillment_type"] != CustomerSaleFulfillment.delivery.value:
            raise ValueError("Commande non livrable")

        m = self._get_member(user_id, organization_id)
        if m.get("member_role") != "delivery_management":
            raise PermissionError("Rôle livreur requis")

        assigned = row.get("assigned_delivery_member_id")
        if not assigned or str(assigned) != str(m["id"]):
            raise PermissionError("Vous n'êtes pas le livreur assigné à cette commande")

        self._validate_order_row_for_token(row)
        return self._mint_receipt_token(order_id, organization_id)

    def list_delivery_assignments(self, user_id: str) -> List[Dict[str, Any]]:
        mres = (
            self.db.table("members")
            .select("id,organization_id")
            .eq("user_id", user_id)
            .eq("member_role", "delivery_management")
            .eq("activity_status", True)
            .execute()
        )
        member_rows = mres.data or []
        if not member_rows:
            return []

        mids = [str(m["id"]) for m in member_rows]
        res = (
            self.db.table("organization_customer_sale_orders")
            .select("*")
            .in_("assigned_delivery_member_id", mids)
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data or []
        return self._attach_lines_to_orders(list(rows))

    def _assert_user_activity(self, user_id: str) -> None:
        ures = (
            self.db.table("users")
            .select("activity_status")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        urows = ures.data or []
        if not urows or not urows[0].get("activity_status"):
            raise PermissionError("Compte utilisateur inactif")

    def _query_delivery_track_points(
        self,
        order_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        cap = max(1, min(limit, 500))
        q = (
            self.db.table("customer_sale_delivery_track_points")
            .select("id,order_id,latitude,longitude,accuracy_meters,recorded_at")
            .eq("order_id", order_id)
            .order("recorded_at", desc=False)
        )
        if since is not None:
            q = q.gte("recorded_at", since.isoformat())
        res = q.limit(cap).execute()
        return list(res.data or [])

    def post_delivery_track_point(
        self, user_id: str, order_id: str, body: DeliveryTrackPointIn
    ) -> Dict[str, Any]:
        self._assert_user_activity(user_id)
        ores = (
            self.db.table("organization_customer_sale_orders")
            .select(
                "organization_id,fulfillment_type,status,assigned_delivery_member_id"
            )
            .eq("id", order_id)
            .limit(1)
            .execute()
        )
        orows = ores.data or []
        if not orows:
            raise LookupError("Commande introuvable")
        o = orows[0]
        if o["fulfillment_type"] != CustomerSaleFulfillment.delivery.value:
            raise ValueError("Cette commande n'est pas une livraison")
        st = o["status"]
        if st in (
            CustomerSaleOrderStatus.cancelled.value,
            CustomerSaleOrderStatus.completed.value,
        ):
            raise ValueError("Commande terminée : envoi de position impossible")
        org_id = str(o["organization_id"])
        try:
            self.subscriptions.assert_feature_enabled(org_id, "realtime_gps")
        except OrganizationSubscriptionFeatureDenied as exc:
            raise PermissionError(str(exc)) from exc
        m = self._get_member(user_id, org_id)
        if m.get("member_role") != "delivery_management":
            raise PermissionError("Rôle livreur requis")
        assigned = o.get("assigned_delivery_member_id")
        if not assigned or str(assigned) != str(m["id"]):
            raise PermissionError("Vous n'êtes pas le livreur assigné à cette commande")

        payload: Dict[str, Any] = {
            "order_id": order_id,
            "latitude": float(body.latitude),
            "longitude": float(body.longitude),
        }
        if body.accuracy_meters is not None:
            payload["accuracy_meters"] = float(body.accuracy_meters)
        try:
            ins = (
                self.db.table("customer_sale_delivery_track_points")
                .insert(payload)
                .execute()
            )
        except APIError as exc:
            msg = (
                str(exc.message)
                if getattr(exc, "message", None)
                else "Enregistrement du point de suivi refusé"
            )
            raise ValueError(msg) from exc
        rows = ins.data or []
        if not rows:
            raise RuntimeError("Enregistrement du point de suivi refusé")
        return rows[0]

    def list_delivery_track_points_customer(
        self,
        user_id: str,
        order_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        row = self._select_order_with_lines(order_id)
        cid = self.get_customer_id_for_user(user_id)
        if not cid or str(row.get("customer_id")) != cid:
            raise LookupError("Commande introuvable")
        if row["fulfillment_type"] != CustomerSaleFulfillment.delivery.value:
            return []
        try:
            self.subscriptions.assert_feature_enabled(
                str(row.get("organization_id")),
                "realtime_gps",
            )
        except OrganizationSubscriptionFeatureDenied as exc:
            raise PermissionError(str(exc)) from exc
        return self._query_delivery_track_points(
            order_id, since=since, limit=limit
        )

    def list_delivery_track_points_org(
        self,
        user_id: str,
        organization_id: str,
        order_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        self.get_org_order(user_id, organization_id, order_id)
        row = self._select_order_with_lines(order_id)
        if row["fulfillment_type"] != CustomerSaleFulfillment.delivery.value:
            return []
        try:
            self.subscriptions.assert_feature_enabled(organization_id, "realtime_gps")
        except OrganizationSubscriptionFeatureDenied as exc:
            raise PermissionError(str(exc)) from exc
        return self._query_delivery_track_points(
            order_id, since=since, limit=limit
        )
