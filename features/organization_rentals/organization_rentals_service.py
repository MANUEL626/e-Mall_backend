from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_rentals.organization_rentals_models import (
    RentalActionRequest,
    RentalOrderCreate,
    RentalReservationCreate,
    RentalReservationStatus,
    RentalReservationUpdate,
)


class OrganizationRentalsService:
    RESERVED_STATUSES = {"reserved", "rented", "late", "maintenance"}
    TERMINAL_STATUSES = {"returned", "cancelled"}
    RESERVATION_SELECT = (
        "id,organization_id,shop_id,rental_asset_id,customer_name,customer_phone,"
        "starts_at,ends_at,quantity,daily_rate,deposit_amount,total_amount,currency,"
        "status,assigned_member_id,notes,created_by_user_id,returned_at,created_at,updated_at"
    )
    ORDER_SELECT = (
        "id,organization_id,shop_id,customer_name,customer_phone,starts_at,ends_at,"
        "deposit_amount,subtotal_amount,discount_amount,discount_label,total_amount,"
        "currency,status,assigned_member_id,notes,created_by_user_id,returned_at,"
        "created_at,updated_at,source_proforma_id"
    )
    ORDER_LINE_SELECT = (
        "id,rental_order_id,rental_asset_id,quantity,daily_rate,line_subtotal,"
        "currency,created_at"
    )
    ASSET_SELECT = (
        "id,name,category,description,unit_purchase_price,unit_sale_price,"
        "sale_currency,wholesale_prices,primary_image_storage_path,"
        "additional_image_storage_paths,active"
    )

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    def _member_row(self, user_id: str, organization_id: str) -> Dict[str, Any]:
        res = (
            self.db.table("members")
            .select("id, member_type, activity_status")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise PermissionError("Membre actif requis pour cette organisation")
        return rows[0]

    def _assert_rental_shop_access(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
    ) -> Dict[str, Any]:
        member = self._member_row(user_id, organization_id)
        shop = (
            self.db.table("organization_shops")
            .select("id, organization_id, shop_type, status")
            .eq("id", shop_id)
            .eq("organization_id", organization_id)
            .eq("shop_type", "rental")
            .neq("status", "archived")
            .limit(1)
            .execute()
        )
        if not (shop.data or []):
            raise ValueError("Boutique de location introuvable pour cette organisation")
        if member.get("member_type") in ("admin", "supervisor"):
            return member
        access = (
            self.db.table("organization_shop_members")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("member_id", str(member["id"]))
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        if not (access.data or []):
            raise PermissionError("Affectation boutique rental requise")
        return member

    def _assert_assigned_member(
        self,
        organization_id: str,
        shop_id: str,
        member_id: Optional[str],
    ) -> None:
        if not member_id:
            return
        member = (
            self.db.table("members")
            .select("id, member_type, activity_status")
            .eq("id", member_id)
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        rows = member.data or []
        if not rows:
            raise ValueError("Membre assigne introuvable dans cette organisation")
        if rows[0].get("member_type") in ("admin", "supervisor"):
            return
        access = (
            self.db.table("organization_shop_members")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("member_id", member_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        if not (access.data or []):
            raise ValueError("Le membre assigne doit etre affecte a cette boutique")

    def _get_stock_row(
        self,
        organization_id: str,
        shop_id: str,
        rental_asset_id: str,
    ) -> Dict[str, Any]:
        res = (
            self.db.table("organization_shop_article_stocks")
            .select("id, stock_quantity, reserved_quantity, active")
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("article_id", rental_asset_id)
            .eq("stock_scope", "rental_asset")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows or rows[0].get("active") is not True:
            raise ValueError("Bien louable indisponible dans cette boutique")
        return rows[0]

    def _assert_asset(self, organization_id: str, rental_asset_id: str) -> None:
        res = (
            self.db.table("organization_articles")
            .select("id")
            .eq("id", rental_asset_id)
            .eq("organization_id", organization_id)
            .eq("resource_scope", "rental_asset")
            .eq("active", True)
            .limit(1)
            .execute()
        )
        if not (res.data or []):
            raise ValueError("Bien louable introuvable ou inactif")

    def _asset_pricing(
        self, organization_id: str, rental_asset_id: str
    ) -> Dict[str, Any]:
        res = (
            self.db.table("organization_articles")
            .select("id, unit_sale_price, sale_currency")
            .eq("id", rental_asset_id)
            .eq("organization_id", organization_id)
            .eq("resource_scope", "rental_asset")
            .eq("active", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise ValueError("Bien louable introuvable ou inactif")
        return rows[0]

    def _change_reserved_quantity(
        self,
        organization_id: str,
        shop_id: str,
        rental_asset_id: str,
        delta: int,
    ) -> None:
        if delta == 0:
            return
        stock = self._get_stock_row(organization_id, shop_id, rental_asset_id)
        current_reserved = int(stock.get("reserved_quantity") or 0)
        stock_quantity = int(stock.get("stock_quantity") or 0)
        new_reserved = current_reserved + delta
        if new_reserved < 0:
            new_reserved = 0
        if new_reserved > stock_quantity:
            raise ValueError("Stock de location insuffisant pour cette reservation")
        self.db.table("organization_shop_article_stocks").update(
            {"reserved_quantity": new_reserved}
        ).eq("id", str(stock["id"])).execute()

    @staticmethod
    def _decimal(value: Optional[Decimal]) -> Optional[str]:
        return str(value) if value is not None else None

    @staticmethod
    def _money(value: Any) -> Decimal:
        return Decimal(str(value or "0")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value)
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _total(body: RentalReservationCreate, daily_rate: Optional[Decimal]) -> Decimal:
        if body.total_amount is not None:
            return body.total_amount
        if daily_rate is None:
            return Decimal("0")
        seconds = (body.ends_at - body.starts_at).total_seconds()
        days = Decimal(str(max(seconds / 86400, 1)))
        return (daily_rate * days * Decimal(body.quantity)).quantize(Decimal("0.01"))

    @staticmethod
    def _rental_days(starts_at: datetime, ends_at: datetime) -> Decimal:
        seconds = (ends_at - starts_at).total_seconds()
        return Decimal(str(max(seconds / 86400, 1)))

    def _get_row(
        self,
        organization_id: str,
        shop_id: str,
        reservation_id: str,
    ) -> Dict[str, Any]:
        res = (
            self.db.table("organization_rental_reservations")
            .select("*")
            .eq("id", reservation_id)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Reservation de location introuvable")
        return rows[0]

    def _get_order_row(
        self,
        organization_id: str,
        shop_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        res = (
            self.db.table("organization_rental_orders")
            .select("*")
            .eq("id", order_id)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Lot de location introuvable")
        return rows[0]

    @staticmethod
    def _asset_snapshot(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        return {
            "id": row.get("id"),
            "name": row.get("name"),
            "category": row.get("category"),
            "description": row.get("description"),
            "unit_purchase_price": row.get("unit_purchase_price"),
            "unit_rental_price": row.get("unit_sale_price"),
            "rental_currency": "xof",
            "rental_bulk_prices": row.get("wholesale_prices"),
            "primary_image_storage_path": row.get("primary_image_storage_path"),
            "additional_image_storage_paths": row.get("additional_image_storage_paths")
            or [],
            "active": row.get("active"),
        }

    def _assets_by_ids(
        self,
        organization_id: str,
        asset_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        if not asset_ids:
            return {}
        rows = (
            self.db.table("organization_articles")
            .select(self.ASSET_SELECT)
            .eq("organization_id", organization_id)
            .eq("resource_scope", "rental_asset")
            .in_("id", sorted(set(asset_ids)))
            .execute()
            .data
            or []
        )
        return {str(row["id"]): row for row in rows if row.get("id")}

    def _lines_for_order(
        self,
        order_id: str,
        organization_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = (
            self.db.table("organization_rental_order_lines")
            .select("*")
            .eq("rental_order_id", order_id)
            .order("created_at", desc=False)
            .execute()
            .data
            or []
        )
        lines = [dict(row) for row in rows]
        if organization_id:
            assets = self._assets_by_ids(
                organization_id,
                [
                    str(line["rental_asset_id"])
                    for line in lines
                    if line.get("rental_asset_id")
                ],
            )
            for line in lines:
                line["asset"] = self._asset_snapshot(
                    assets.get(str(line.get("rental_asset_id")))
                )
        return lines

    def _lines_for_orders(
        self,
        order_ids: List[str],
        organization_id: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        unique_order_ids = sorted({order_id for order_id in order_ids if order_id})
        if not unique_order_ids:
            return {}
        rows = (
            self.db.table("organization_rental_order_lines")
            .select(self.ORDER_LINE_SELECT)
            .in_("rental_order_id", unique_order_ids)
            .order("created_at", desc=False)
            .execute()
            .data
            or []
        )
        asset_ids = [
            str(row["rental_asset_id"])
            for row in rows
            if row.get("rental_asset_id")
        ]
        assets = self._assets_by_ids(organization_id, asset_ids)
        grouped: Dict[str, List[Dict[str, Any]]] = {
            order_id: [] for order_id in unique_order_ids
        }
        for row in rows:
            item = dict(row)
            item["asset"] = self._asset_snapshot(
                assets.get(str(row.get("rental_asset_id")))
            )
            grouped.setdefault(str(row.get("rental_order_id")), []).append(item)
        return grouped

    def _attach_order_lines(self, order: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(order)
        row["lines"] = self._lines_for_order(
            str(order["id"]),
            str(order.get("organization_id") or ""),
        )
        return row

    def _attach_orders_lines(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not orders:
            return []
        organization_id = str(orders[0].get("organization_id") or "")
        grouped_lines = self._lines_for_orders(
            [str(order["id"]) for order in orders if order.get("id")],
            organization_id,
        )
        enriched: List[Dict[str, Any]] = []
        for order in orders:
            item = dict(order)
            item["lines"] = grouped_lines.get(str(order.get("id")), [])
            enriched.append(item)
        return enriched

    def _attach_reservation_assets(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        organization_id = str(rows[0].get("organization_id") or "")
        assets = self._assets_by_ids(
            organization_id,
            [
                str(row["rental_asset_id"])
                for row in rows
                if row.get("rental_asset_id")
            ],
        )
        enriched: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["asset"] = self._asset_snapshot(
                assets.get(str(row.get("rental_asset_id")))
            )
            enriched.append(item)
        return enriched

    def _attach_reservation_asset(self, row: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._attach_reservation_assets([row])
        return rows[0] if rows else row

    @staticmethod
    def _invoice_number(order_row: Dict[str, Any]) -> str:
        created_at = str(order_row.get("created_at") or "")
        compact_date = created_at[:10].replace("-", "") if created_at else "nodate"
        return f"RNTINV-{compact_date}-{str(order_row['id'])[:8].upper()}"

    @staticmethod
    def _public_org_snapshot(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not row:
            return {}
        keys = (
            "id",
            "name",
            "org_type",
            "profile_picture",
            "default_currencies",
        )
        return {key: row.get(key) for key in keys if key in row}

    @staticmethod
    def _public_shop_snapshot(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not row:
            return {}
        keys = ("id", "name", "code", "shop_type", "status", "is_default")
        return {key: row.get(key) for key in keys if key in row}

    def _select_invoice_by_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("organization_rental_invoices")
            .select("*")
            .eq("rental_order_id", order_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def _build_invoice_payload(self, order_row: Dict[str, Any]) -> Dict[str, Any]:
        if order_row.get("status") != RentalReservationStatus.returned.value:
            raise ValueError(
                "La facture est disponible uniquement pour une location retournee"
            )

        organization_id = str(order_row["organization_id"])
        shop_id = str(order_row["shop_id"])
        org_res = (
            self.db.table("organizations")
            .select("*")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        shop_res = (
            self.db.table("organization_shops")
            .select("*")
            .eq("id", shop_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        lines = self._lines_for_order(str(order_row["id"]), organization_id)

        lines_snapshot: List[Dict[str, Any]] = []
        total_items = 0
        for line in lines:
            quantity = int(line.get("quantity") or 0)
            asset = line.get("asset") or {}
            line_subtotal = self._money(line.get("line_subtotal"))
            total_items += quantity
            lines_snapshot.append(
                {
                    "line_id": line.get("id"),
                    "rental_asset_id": line.get("rental_asset_id"),
                    "asset_name": asset.get("name"),
                    "asset_category": asset.get("category"),
                    "asset_description": asset.get("description"),
                    "primary_image_storage_path": asset.get(
                        "primary_image_storage_path"
                    ),
                    "additional_image_storage_paths": asset.get(
                        "additional_image_storage_paths"
                    )
                    or [],
                    "quantity": quantity,
                    "daily_rate": str(self._money(line.get("daily_rate"))),
                    "currency": "xof",
                    "line_subtotal": str(line_subtotal),
                }
            )

        subtotal = self._money(order_row.get("subtotal_amount"))
        discount = self._money(order_row.get("discount_amount"))
        deposit = self._money(order_row.get("deposit_amount"))
        total = self._money(order_row.get("total_amount"))
        customer_label = order_row.get("customer_name") or order_row.get("customer_phone")
        return {
            "rental_order_id": str(order_row["id"]),
            "organization_id": organization_id,
            "shop_id": shop_id,
            "invoice_number": self._invoice_number(order_row),
            "currency": "xof",
            "subtotal_amount": float(subtotal),
            "discount_amount": float(discount),
            "deposit_amount": float(deposit),
            "total_amount": float(total),
            "total_items": total_items,
            "total_lines": len(lines_snapshot),
            "status": "issued",
            "customer_label": customer_label,
            "organization_snapshot": self._public_org_snapshot(
                dict((org_res.data or [{}])[0]) if org_res.data else None
            ),
            "shop_snapshot": self._public_shop_snapshot(
                dict((shop_res.data or [{}])[0]) if shop_res.data else None
            ),
            "rental_snapshot": {
                "id": order_row.get("id"),
                "customer_name": order_row.get("customer_name"),
                "customer_phone": order_row.get("customer_phone"),
                "starts_at": order_row.get("starts_at"),
                "ends_at": order_row.get("ends_at"),
                "status": order_row.get("status"),
                "currency": "xof",
                "subtotal_amount": str(subtotal),
                "discount_amount": str(discount),
                "discount_label": order_row.get("discount_label"),
                "deposit_amount": str(deposit),
                "total_amount": str(total),
                "assigned_member_id": order_row.get("assigned_member_id"),
                "returned_at": order_row.get("returned_at"),
            },
            "lines_snapshot": lines_snapshot,
        }

    def _ensure_invoice_for_returned_order(
        self,
        order_row: Dict[str, Any],
    ) -> Dict[str, Any]:
        order_id = str(order_row["id"])
        existing = self._select_invoice_by_order_id(order_id)
        if existing:
            return existing

        payload = self._build_invoice_payload(order_row)
        try:
            inserted = self.db.table("organization_rental_invoices").insert(payload).execute()
        except Exception:
            existing = self._select_invoice_by_order_id(order_id)
            if existing:
                return existing
            raise
        rows = inserted.data or []
        if not rows:
            raise RuntimeError("Creation de la facture location refusee")
        return rows[0]

    @staticmethod
    def _append_note(updates: Dict[str, Any], row: Dict[str, Any], note: Optional[str]) -> None:
        if not note:
            return
        current = row.get("notes") or ""
        updates["notes"] = f"{current}\n{note}".strip() if current else note

    def _mark_late_if_due(
        self,
        table_name: str,
        row: Dict[str, Any],
    ) -> Dict[str, Any]:
        if row.get("status") != RentalReservationStatus.rented.value:
            return row
        ends_at = self._parse_datetime(row["ends_at"])
        if ends_at >= datetime.now(timezone.utc):
            return row
        rows = (
            self.db.table(table_name)
            .update({"status": RentalReservationStatus.late.value})
            .eq("id", str(row["id"]))
            .execute()
            .data
            or []
        )
        return rows[0] if rows else row

    def _refresh_reservation_status(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return self._mark_late_if_due("organization_rental_reservations", row)

    def _refresh_order_status(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return self._mark_late_if_due("organization_rental_orders", row)

    def _assert_can_start(self, row: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        starts_at = self._parse_datetime(row["starts_at"])
        ends_at = self._parse_datetime(row["ends_at"])
        if row.get("status") != RentalReservationStatus.reserved.value:
            raise ValueError("Seule une location reservee peut etre debitee")
        if now < starts_at:
            raise ValueError("La location ne peut pas demarrer avant sa date de debut")
        if now >= ends_at:
            raise ValueError("La periode de location est deja terminee; annulez ou recréez la location")

    def _transition_rental_row(
        self,
        table_name: str,
        row: Dict[str, Any],
        status: RentalReservationStatus,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        row = self._mark_late_if_due(table_name, row)
        current = str(row.get("status"))
        target = status.value

        if target == RentalReservationStatus.rented.value:
            self._assert_can_start(row)
        elif target == RentalReservationStatus.cancelled.value:
            if current != RentalReservationStatus.reserved.value:
                raise ValueError("Une location ne peut etre annulee qu'avant son demarrage")
        elif target == RentalReservationStatus.returned.value:
            if current not in {
                RentalReservationStatus.rented.value,
                RentalReservationStatus.late.value,
            }:
                raise ValueError("Seule une location en cours ou en retard peut etre terminee")
        elif target == RentalReservationStatus.late.value:
            if current != RentalReservationStatus.rented.value:
                raise ValueError("Seule une location en cours peut passer en retard")
            if self._parse_datetime(row["ends_at"]) >= datetime.now(timezone.utc):
                raise ValueError("La location n'est pas encore en retard")
        else:
            raise ValueError("Transition de location non autorisee")

        updates: Dict[str, Any] = {"status": target}
        if status == RentalReservationStatus.returned:
            updates["returned_at"] = datetime.now(timezone.utc).isoformat()
        self._append_note(updates, row, note)
        rows = (
            self.db.table(table_name)
            .update(updates)
            .eq("id", str(row["id"]))
            .execute()
            .data
            or []
        )
        if not rows:
            raise LookupError("Location introuvable")
        return rows[0]

    def _overlapping_rental_quantity(
        self,
        organization_id: str,
        shop_id: str,
        rental_asset_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> int:
        legacy_rows = (
            self.db.table("organization_rental_reservations")
            .select("quantity")
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("rental_asset_id", rental_asset_id)
            .in_("status", list(self.RESERVED_STATUSES))
            .lt("starts_at", ends_at.isoformat())
            .gt("ends_at", starts_at.isoformat())
            .execute()
            .data
            or []
        )
        order_rows = (
            self.db.table("organization_rental_orders")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .in_("status", list(self.RESERVED_STATUSES))
            .lt("starts_at", ends_at.isoformat())
            .gt("ends_at", starts_at.isoformat())
            .execute()
            .data
            or []
        )
        order_ids = [str(row["id"]) for row in order_rows if row.get("id")]
        order_line_rows: List[Dict[str, Any]] = []
        if order_ids:
            order_line_rows = list(
                self.db.table("organization_rental_order_lines")
                .select("quantity")
                .eq("organization_id", organization_id)
                .eq("shop_id", shop_id)
                .eq("rental_asset_id", rental_asset_id)
                .in_("rental_order_id", order_ids)
                .execute()
                .data
                or []
            )
        return sum(int(row.get("quantity") or 0) for row in legacy_rows) + sum(
            int(row.get("quantity") or 0) for row in order_line_rows
        )

    def list_reservations(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        status: Optional[RentalReservationStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        page_limit = max(1, min(int(limit or 50), 200))
        page_offset = max(0, int(offset or 0))
        q = (
            self.db.table("organization_rental_reservations")
            .select(self.RESERVATION_SELECT)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
        )
        if status is not None and status != RentalReservationStatus.late:
            q = q.eq("status", status.value)
        q = q.order("starts_at", desc=True).range(
            page_offset,
            page_offset + page_limit - 1,
        )
        rows = [self._refresh_reservation_status(row) for row in list(q.execute().data or [])]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status.value]
        return self._attach_reservation_assets(rows)

    def get_availability(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        rental_asset_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        if ends_at <= starts_at:
            raise ValueError("La date de fin doit etre apres la date de debut")
        self._assert_asset(organization_id, rental_asset_id)
        stock = self._get_stock_row(organization_id, shop_id, rental_asset_id)
        overlapping = self._overlapping_rental_quantity(
            organization_id,
            shop_id,
            rental_asset_id,
            starts_at,
            ends_at,
        )
        stock_quantity = int(stock.get("stock_quantity") or 0)
        return {
            "organization_id": organization_id,
            "shop_id": shop_id,
            "rental_asset_id": rental_asset_id,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "stock_quantity": stock_quantity,
            "reserved_quantity_now": int(stock.get("reserved_quantity") or 0),
            "overlapping_reserved_quantity": overlapping,
            "available_quantity": max(stock_quantity - overlapping, 0),
        }

    def list_orders(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        status: Optional[RentalReservationStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        page_limit = max(1, min(int(limit or 50), 200))
        page_offset = max(0, int(offset or 0))
        q = (
            self.db.table("organization_rental_orders")
            .select(self.ORDER_SELECT)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
        )
        if status is not None and status != RentalReservationStatus.late:
            q = q.eq("status", status.value)
        q = q.order("starts_at", desc=True).range(
            page_offset,
            page_offset + page_limit - 1,
        )
        rows = [self._refresh_order_status(row) for row in list(q.execute().data or [])]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status.value]
        return self._attach_orders_lines(rows)

    def create_order(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        body: RentalOrderCreate,
        source_proforma_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        assigned = str(body.assigned_member_id) if body.assigned_member_id else None
        self._assert_assigned_member(organization_id, shop_id, assigned)

        days = self._rental_days(body.starts_at, body.ends_at)
        line_payloads: List[Dict[str, Any]] = []
        subtotal = Decimal("0")
        order_currency = "xof"

        for line in body.lines:
            asset_id = str(line.rental_asset_id)
            asset_pricing = self._asset_pricing(organization_id, asset_id)
            stock = self._get_stock_row(organization_id, shop_id, asset_id)
            overlapping = self._overlapping_rental_quantity(
                organization_id,
                shop_id,
                asset_id,
                body.starts_at,
                body.ends_at,
            )
            available = int(stock.get("stock_quantity") or 0) - overlapping
            if line.quantity > available:
                raise ValueError(
                    f"Stock de location insuffisant pour l'actif {asset_id}: "
                    f"{available} disponible(s), {line.quantity} demande(s)"
                )

            daily_rate = (
                line.daily_rate
                if line.daily_rate is not None
                else Decimal(str(asset_pricing.get("unit_sale_price") or "0"))
            )
            line_subtotal = (
                line.total_amount
                if line.total_amount is not None
                else daily_rate * days * Decimal(line.quantity)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            subtotal += line_subtotal
            line_payloads.append(
                {
                    "organization_id": organization_id,
                    "shop_id": shop_id,
                    "rental_asset_id": asset_id,
                    "quantity": line.quantity,
                    "daily_rate": self._decimal(daily_rate),
                    "line_subtotal": self._decimal(line_subtotal),
                    "currency": "xof",
                }
            )

        subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if body.discount_percent is not None:
            discount = (subtotal * body.discount_percent / Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        else:
            discount = self._money(body.discount_amount)
        if discount > subtotal:
            raise ValueError("La remise ne peut pas depasser le sous-total du lot")
        total = (subtotal - discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        payload = {
            "organization_id": organization_id,
            "shop_id": shop_id,
            "customer_name": body.customer_name,
            "customer_phone": body.customer_phone,
            "starts_at": body.starts_at.isoformat(),
            "ends_at": body.ends_at.isoformat(),
            "deposit_amount": self._decimal(body.deposit_amount),
            "subtotal_amount": self._decimal(subtotal),
            "discount_amount": self._decimal(discount),
            "discount_label": body.discount_label,
            "total_amount": self._decimal(total),
            "currency": order_currency,
            "assigned_member_id": assigned,
            "notes": body.notes,
            "created_by_user_id": user_id,
        }
        if source_proforma_id:
            payload["source_proforma_id"] = source_proforma_id
        order_rows = (
            self.db.table("organization_rental_orders")
            .insert(payload)
            .execute()
            .data
            or []
        )
        if not order_rows:
            raise RuntimeError("Creation du lot de location impossible")
        order = order_rows[0]
        try:
            for line_payload in line_payloads:
                line_payload["rental_order_id"] = str(order["id"])
            if line_payloads:
                self.db.table("organization_rental_order_lines").insert(line_payloads).execute()
        except Exception:
            self.db.table("organization_rental_orders").delete().eq(
                "id",
                str(order["id"]),
            ).execute()
            raise
        return self._attach_order_lines(order)

    def get_order(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._refresh_order_status(
            self._get_order_row(organization_id, shop_id, order_id)
        )
        return self._attach_order_lines(row)

    def update_order_status(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        order_id: str,
        status: RentalReservationStatus,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._get_order_row(organization_id, shop_id, order_id)
        updated = self._transition_rental_row(
            "organization_rental_orders",
            row,
            status,
            note=note,
        )
        if status == RentalReservationStatus.returned:
            self._ensure_invoice_for_returned_order(updated)
        return self._attach_order_lines(updated)

    def get_order_invoice(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._refresh_order_status(
            self._get_order_row(organization_id, shop_id, order_id)
        )
        return self._ensure_invoice_for_returned_order(row)

    def start_order(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        order_id: str,
        body: RentalActionRequest,
    ) -> Dict[str, Any]:
        return self.update_order_status(
            user_id,
            organization_id,
            shop_id,
            order_id,
            RentalReservationStatus.rented,
            note=body.note,
        )

    def return_order(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        order_id: str,
        body: RentalActionRequest,
    ) -> Dict[str, Any]:
        return self.update_order_status(
            user_id,
            organization_id,
            shop_id,
            order_id,
            RentalReservationStatus.returned,
            note=body.note,
        )

    def cancel_order(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        order_id: str,
        body: RentalActionRequest,
    ) -> Dict[str, Any]:
        return self.update_order_status(
            user_id,
            organization_id,
            shop_id,
            order_id,
            RentalReservationStatus.cancelled,
            note=body.note,
        )

    def create_reservation(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        body: RentalReservationCreate,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        asset_id = str(body.rental_asset_id)
        asset_pricing = self._asset_pricing(organization_id, asset_id)
        default_daily_rate = Decimal(str(asset_pricing.get("unit_sale_price") or "0"))
        effective_daily_rate = body.daily_rate or default_daily_rate
        effective_currency = "xof"
        self._change_reserved_quantity(organization_id, shop_id, asset_id, body.quantity)
        assigned = str(body.assigned_member_id) if body.assigned_member_id else None
        self._assert_assigned_member(organization_id, shop_id, assigned)
        payload = {
            "organization_id": organization_id,
            "shop_id": shop_id,
            "rental_asset_id": asset_id,
            "customer_name": body.customer_name,
            "customer_phone": body.customer_phone,
            "starts_at": body.starts_at.isoformat(),
            "ends_at": body.ends_at.isoformat(),
            "quantity": body.quantity,
            "daily_rate": self._decimal(effective_daily_rate),
            "deposit_amount": self._decimal(body.deposit_amount),
            "total_amount": self._decimal(self._total(body, effective_daily_rate)),
            "currency": effective_currency,
            "assigned_member_id": assigned,
            "notes": body.notes,
            "created_by_user_id": user_id,
        }
        try:
            rows = (
                self.db.table("organization_rental_reservations")
                .insert(payload)
                .execute()
                .data
                or []
            )
        except Exception:
            self._change_reserved_quantity(
                organization_id,
                shop_id,
                asset_id,
                -body.quantity,
            )
            raise
        if not rows:
            self._change_reserved_quantity(organization_id, shop_id, asset_id, -body.quantity)
            raise RuntimeError("Creation de la reservation impossible")
        return self._attach_reservation_asset(rows[0])

    def get_reservation(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        reservation_id: str,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        return self._attach_reservation_asset(
            self._refresh_reservation_status(
                self._get_row(organization_id, shop_id, reservation_id)
            )
        )

    def update_reservation(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        reservation_id: str,
        body: RentalReservationUpdate,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._refresh_reservation_status(
            self._get_row(organization_id, shop_id, reservation_id)
        )
        if row.get("status") != RentalReservationStatus.reserved.value:
            raise ValueError("Seules les locations reservees peuvent etre modifiees")
        updates: Dict[str, Any] = {}
        for field in ("customer_name", "customer_phone", "notes"):
            value = getattr(body, field)
            if value is not None:
                updates[field] = value
        starts_at = body.starts_at or self._parse_datetime(row["starts_at"])
        ends_at = body.ends_at or self._parse_datetime(row["ends_at"])
        if body.starts_at is not None:
            updates["starts_at"] = body.starts_at.isoformat()
        if body.ends_at is not None:
            updates["ends_at"] = body.ends_at.isoformat()
        if updates.get("starts_at") or updates.get("ends_at"):
            if ends_at <= starts_at:
                raise ValueError("La date de fin doit etre apres la date de debut")
        if body.quantity is not None:
            delta = body.quantity - int(row["quantity"])
            self._change_reserved_quantity(
                organization_id,
                shop_id,
                str(row["rental_asset_id"]),
                delta,
            )
            updates["quantity"] = body.quantity
        if body.daily_rate is not None:
            updates["daily_rate"] = self._decimal(body.daily_rate)
        if body.deposit_amount is not None:
            updates["deposit_amount"] = self._decimal(body.deposit_amount)
        if body.total_amount is not None:
            updates["total_amount"] = self._decimal(body.total_amount)
        if body.currency is not None:
            updates["currency"] = "xof"
        if body.assigned_member_id is not None:
            assigned = str(body.assigned_member_id)
            self._assert_assigned_member(organization_id, shop_id, assigned)
            updates["assigned_member_id"] = assigned
        if not updates:
            raise ValueError("Aucune mise a jour fournie")
        rows = (
            self.db.table("organization_rental_reservations")
            .update(updates)
            .eq("id", reservation_id)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .execute()
            .data
            or []
        )
        if not rows:
            raise LookupError("Reservation de location introuvable")
        return self._attach_reservation_asset(rows[0])

    def update_status(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        reservation_id: str,
        status: RentalReservationStatus,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._get_row(organization_id, shop_id, reservation_id)
        updated = self._transition_rental_row(
            "organization_rental_reservations",
            row,
            status,
            note=note,
        )
        old_reserved = str(row.get("status")) in self.RESERVED_STATUSES
        new_reserved = str(updated.get("status")) in self.RESERVED_STATUSES
        if old_reserved and not new_reserved:
            self._change_reserved_quantity(
                organization_id,
                shop_id,
                str(row["rental_asset_id"]),
                -int(row["quantity"]),
            )
        elif new_reserved and not old_reserved:
            self._change_reserved_quantity(
                organization_id,
                shop_id,
                str(row["rental_asset_id"]),
                int(row["quantity"]),
            )
        return self._attach_reservation_asset(updated)

    def start_reservation(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        reservation_id: str,
        body: RentalActionRequest,
    ) -> Dict[str, Any]:
        return self.update_status(
            user_id,
            organization_id,
            shop_id,
            reservation_id,
            RentalReservationStatus.rented,
            note=body.note,
        )

    def return_reservation(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        reservation_id: str,
        body: RentalActionRequest,
    ) -> Dict[str, Any]:
        return self.update_status(
            user_id,
            organization_id,
            shop_id,
            reservation_id,
            RentalReservationStatus.returned,
            note=body.note,
        )

    def cancel_reservation(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        reservation_id: str,
        body: RentalActionRequest,
    ) -> Dict[str, Any]:
        return self.update_status(
            user_id,
            organization_id,
            shop_id,
            reservation_id,
            RentalReservationStatus.cancelled,
            note=body.note,
        )
