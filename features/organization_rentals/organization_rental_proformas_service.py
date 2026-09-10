from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from features.organization_rentals.organization_rentals_models import (
    RentalOrderCreate,
    RentalOrderLineCreate,
    RentalProformaCreate,
    RentalProformaPaymentCreate,
    RentalProformaStatus,
    RentalProformaUpdate,
)
from features.organization_rentals.organization_rentals_service import (
    OrganizationRentalsService,
)


class OrganizationRentalProformasService(OrganizationRentalsService):
    PROFORMA_SELECT = (
        "id,organization_id,shop_id,proforma_number,customer_name,customer_phone,"
        "customer_email,customer_address,starts_at,ends_at,subtotal_amount,"
        "discount_amount,discount_label,security_deposit_amount,total_amount,"
        "total_payable_amount,advance_required_amount,amount_paid,currency,status,"
        "payment_status,assigned_member_id,expires_at,issued_at,accepted_at,"
        "converted_at,cancelled_at,converted_rental_order_id,notes,terms,"
        "organization_snapshot,shop_snapshot,created_by_user_id,created_at,updated_at"
    )
    PROFORMA_LINE_SELECT = (
        "id,rental_proforma_id,rental_asset_id,quantity,daily_rate,line_subtotal,"
        "currency,asset_snapshot,created_at"
    )
    PROFORMA_PAYMENT_SELECT = (
        "id,rental_proforma_id,organization_id,shop_id,amount,currency,"
        "payment_method,payment_reference,status,paid_at,note,created_by_user_id,created_at"
    )

    def _get_proforma_row(
        self,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
    ) -> Dict[str, Any]:
        rows = (
            self.db.table("organization_rental_proformas")
            .select("*")
            .eq("id", proforma_id)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            raise LookupError("Facture proforma de location introuvable")
        return rows[0]

    def _proforma_lines(self, proforma_id: str) -> List[Dict[str, Any]]:
        return list(
            self.db.table("organization_rental_proforma_lines")
            .select(self.PROFORMA_LINE_SELECT)
            .eq("rental_proforma_id", proforma_id)
            .order("created_at", desc=False)
            .execute()
            .data
            or []
        )

    def _proforma_payments(self, proforma_id: str) -> List[Dict[str, Any]]:
        return list(
            self.db.table("organization_rental_proforma_payments")
            .select(self.PROFORMA_PAYMENT_SELECT)
            .eq("rental_proforma_id", proforma_id)
            .order("paid_at", desc=False)
            .execute()
            .data
            or []
        )

    def _attach_proforma_details(self, row: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(row)
        proforma_id = str(row["id"])
        result["lines"] = self._proforma_lines(proforma_id)
        result["payments"] = self._proforma_payments(proforma_id)
        return result

    def _attach_proformas_details(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        proforma_ids = sorted({str(row["id"]) for row in rows if row.get("id")})
        line_rows = (
            self.db.table("organization_rental_proforma_lines")
            .select(self.PROFORMA_LINE_SELECT)
            .in_("rental_proforma_id", proforma_ids)
            .order("created_at", desc=False)
            .execute()
            .data
            or []
        )
        payment_rows = (
            self.db.table("organization_rental_proforma_payments")
            .select(self.PROFORMA_PAYMENT_SELECT)
            .in_("rental_proforma_id", proforma_ids)
            .order("paid_at", desc=False)
            .execute()
            .data
            or []
        )
        lines_by_proforma: Dict[str, List[Dict[str, Any]]] = {
            proforma_id: [] for proforma_id in proforma_ids
        }
        for line in line_rows:
            lines_by_proforma.setdefault(str(line.get("rental_proforma_id")), []).append(
                dict(line)
            )
        payments_by_proforma: Dict[str, List[Dict[str, Any]]] = {
            proforma_id: [] for proforma_id in proforma_ids
        }
        for payment in payment_rows:
            payments_by_proforma.setdefault(
                str(payment.get("rental_proforma_id")),
                [],
            ).append(dict(payment))

        enriched: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            proforma_id = str(row.get("id"))
            item["lines"] = lines_by_proforma.get(proforma_id, [])
            item["payments"] = payments_by_proforma.get(proforma_id, [])
            enriched.append(item)
        return enriched

    def _expire_if_due(self, row: Dict[str, Any]) -> Dict[str, Any]:
        if row.get("status") not in {
            RentalProformaStatus.issued.value,
            RentalProformaStatus.accepted.value,
        }:
            return row
        expires_at = row.get("expires_at")
        if not expires_at or self._parse_datetime(expires_at) >= datetime.now(timezone.utc):
            return row
        rows = (
            self.db.table("organization_rental_proformas")
            .update({"status": RentalProformaStatus.expired.value})
            .eq("id", str(row["id"]))
            .execute()
            .data
            or []
        )
        return rows[0] if rows else row

    def _price_proforma_lines(
        self,
        organization_id: str,
        shop_id: str,
        body: RentalProformaCreate,
    ) -> Tuple[List[Dict[str, Any]], Decimal, str]:
        days = self._rental_days(body.starts_at, body.ends_at)
        line_payloads: List[Dict[str, Any]] = []
        subtotal = Decimal("0")
        proforma_currency = "xof"
        asset_snapshots = self._assets_by_ids(
            organization_id,
            [str(line.rental_asset_id) for line in body.lines],
        )

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
                    f"Stock indicatif insuffisant pour l'actif {asset_id}: "
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
            asset_snapshot = self._asset_snapshot(asset_snapshots.get(asset_id)) or {
                "id": asset_id
            }
            line_payloads.append(
                {
                    "organization_id": organization_id,
                    "shop_id": shop_id,
                    "rental_asset_id": asset_id,
                    "quantity": line.quantity,
                    "daily_rate": self._decimal(daily_rate),
                    "line_subtotal": self._decimal(line_subtotal),
                    "currency": "xof",
                    "asset_snapshot": asset_snapshot,
                }
            )
        return (
            line_payloads,
            subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            proforma_currency,
        )

    def _proforma_payload(
        self,
        organization_id: str,
        shop_id: str,
        user_id: str,
        body: RentalProformaCreate,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        assigned = str(body.assigned_member_id) if body.assigned_member_id else None
        self._assert_assigned_member(organization_id, shop_id, assigned)
        lines, subtotal, currency = self._price_proforma_lines(
            organization_id,
            shop_id,
            body,
        )
        if body.discount_percent is not None:
            discount = (subtotal * body.discount_percent / Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        else:
            discount = self._money(body.discount_amount)
        if discount > subtotal:
            raise ValueError("La remise ne peut pas depasser le sous-total")

        total = (subtotal - discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        security_deposit = self._money(body.security_deposit_amount)
        total_payable = (total + security_deposit).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        advance_required = (
            self._money(body.advance_required_amount)
            if body.advance_required_amount is not None
            else total_payable
        )
        if advance_required > total_payable:
            raise ValueError("L'acompte requis ne peut pas depasser le total a payer")

        proforma_id = str(uuid4())
        compact_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        payload = {
            "id": proforma_id,
            "organization_id": organization_id,
            "shop_id": shop_id,
            "proforma_number": f"RPF-{compact_date}-{proforma_id[:8].upper()}",
            "customer_name": body.customer_name,
            "customer_phone": body.customer_phone,
            "customer_email": body.customer_email,
            "customer_address": body.customer_address,
            "starts_at": body.starts_at.isoformat(),
            "ends_at": body.ends_at.isoformat(),
            "subtotal_amount": self._decimal(subtotal),
            "discount_amount": self._decimal(discount),
            "discount_label": body.discount_label,
            "security_deposit_amount": self._decimal(security_deposit),
            "total_amount": self._decimal(total),
            "total_payable_amount": self._decimal(total_payable),
            "advance_required_amount": self._decimal(advance_required),
            "currency": currency,
            "assigned_member_id": assigned,
            "expires_at": body.expires_at.isoformat() if body.expires_at else None,
            "notes": body.notes,
            "terms": body.terms,
            "created_by_user_id": user_id,
        }
        for line in lines:
            line["rental_proforma_id"] = proforma_id
        return payload, lines

    def create_proforma(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        body: RentalProformaCreate,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        payload, lines = self._proforma_payload(
            organization_id,
            shop_id,
            user_id,
            body,
        )
        rows = (
            self.db.table("organization_rental_proformas")
            .insert(payload)
            .execute()
            .data
            or []
        )
        if not rows:
            raise RuntimeError("Creation de la facture proforma impossible")
        try:
            self.db.table("organization_rental_proforma_lines").insert(lines).execute()
        except Exception:
            self.db.table("organization_rental_proformas").delete().eq(
                "id", payload["id"]
            ).execute()
            raise
        return self._attach_proforma_details(rows[0])

    def list_proformas(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_status: Optional[RentalProformaStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        page_limit = max(1, min(int(limit or 50), 200))
        page_offset = max(0, int(offset or 0))
        query = (
            self.db.table("organization_rental_proformas")
            .select(self.PROFORMA_SELECT)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
        )
        if proforma_status is not None and proforma_status != RentalProformaStatus.expired:
            query = query.eq("status", proforma_status.value)
        query = query.order("created_at", desc=True).range(
            page_offset,
            page_offset + page_limit - 1,
        )
        rows = [self._expire_if_due(row) for row in list(query.execute().data or [])]
        if proforma_status is not None:
            rows = [row for row in rows if row.get("status") == proforma_status.value]
        return self._attach_proformas_details(rows)

    def update_proforma(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
        body: RentalProformaUpdate,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._get_proforma_row(organization_id, shop_id, proforma_id)
        if row.get("status") != RentalProformaStatus.draft.value:
            raise ValueError("Seule une proforma en brouillon peut etre modifiee")
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise ValueError("Aucune modification fournie")

        old_lines = self._proforma_lines(proforma_id)
        current_required = self._money(row.get("advance_required_amount"))
        current_total_payable = self._money(row.get("total_payable_amount"))
        preserved_required: Optional[Decimal] = current_required
        if current_required == current_total_payable and "advance_required_amount" not in changes:
            preserved_required = None

        merged: Dict[str, Any] = {
            "customer_name": row.get("customer_name"),
            "customer_phone": row.get("customer_phone"),
            "customer_email": row.get("customer_email"),
            "customer_address": row.get("customer_address"),
            "starts_at": self._parse_datetime(row["starts_at"]),
            "ends_at": self._parse_datetime(row["ends_at"]),
            "lines": [
                {
                    "rental_asset_id": line["rental_asset_id"],
                    "quantity": int(line.get("quantity") or 0),
                    "daily_rate": line.get("daily_rate"),
                    "currency": line.get("currency"),
                }
                for line in old_lines
            ],
            "security_deposit_amount": row.get("security_deposit_amount") or 0,
            "discount_amount": row.get("discount_amount") or 0,
            "discount_percent": None,
            "discount_label": row.get("discount_label"),
            "advance_required_amount": preserved_required,
            "currency": row.get("currency"),
            "assigned_member_id": row.get("assigned_member_id"),
            "expires_at": (
                self._parse_datetime(row["expires_at"])
                if row.get("expires_at")
                else None
            ),
            "notes": row.get("notes"),
            "terms": row.get("terms"),
        }
        merged.update(changes)
        if "discount_percent" in changes and changes.get("discount_percent") is not None:
            merged["discount_amount"] = Decimal("0")
        if "discount_amount" in changes:
            merged["discount_percent"] = None
        validated = RentalProformaCreate.model_validate(merged)
        new_payload, new_lines = self._proforma_payload(
            organization_id,
            shop_id,
            user_id,
            validated,
        )
        mutable_fields = {
            key: value
            for key, value in new_payload.items()
            if key
            not in {
                "id",
                "organization_id",
                "shop_id",
                "proforma_number",
                "created_by_user_id",
            }
        }
        for line in new_lines:
            line["rental_proforma_id"] = proforma_id

        self.db.table("organization_rental_proforma_lines").delete().eq(
            "rental_proforma_id", proforma_id
        ).execute()
        try:
            self.db.table("organization_rental_proforma_lines").insert(new_lines).execute()
            updated = (
                self.db.table("organization_rental_proformas")
                .update(mutable_fields)
                .eq("id", proforma_id)
                .execute()
                .data
                or []
            )
            if not updated:
                raise RuntimeError("Mise a jour de la facture proforma impossible")
        except Exception:
            self.db.table("organization_rental_proforma_lines").delete().eq(
                "rental_proforma_id", proforma_id
            ).execute()
            if old_lines:
                restore_lines = [
                    {
                        key: value
                        for key, value in old_line.items()
                        if key != "created_at"
                    }
                    for old_line in old_lines
                ]
                self.db.table("organization_rental_proforma_lines").insert(
                    restore_lines
                ).execute()
            raise
        return self._attach_proforma_details(updated[0])

    def get_proforma(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._expire_if_due(
            self._get_proforma_row(organization_id, shop_id, proforma_id)
        )
        return self._attach_proforma_details(row)

    def issue_proforma(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._get_proforma_row(organization_id, shop_id, proforma_id)
        if row.get("status") != RentalProformaStatus.draft.value:
            raise ValueError("Seule une proforma en brouillon peut etre emise")
        if row.get("expires_at") and self._parse_datetime(row["expires_at"]) <= datetime.now(
            timezone.utc
        ):
            raise ValueError("La date d'expiration doit etre dans le futur")

        org_rows = (
            self.db.table("organizations")
            .select("*")
            .eq("id", organization_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        shop_rows = (
            self.db.table("organization_shops")
            .select("*")
            .eq("id", shop_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        now = datetime.now(timezone.utc).isoformat()
        updated = (
            self.db.table("organization_rental_proformas")
            .update(
                {
                    "status": RentalProformaStatus.issued.value,
                    "issued_at": now,
                    "organization_snapshot": self._public_org_snapshot(
                        org_rows[0] if org_rows else None
                    ),
                    "shop_snapshot": self._public_shop_snapshot(
                        shop_rows[0] if shop_rows else None
                    ),
                }
            )
            .eq("id", proforma_id)
            .execute()
            .data
            or []
        )
        if not updated:
            raise RuntimeError("Emission de la facture proforma impossible")
        return self._attach_proforma_details(updated[0])

    def cancel_proforma(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._expire_if_due(
            self._get_proforma_row(organization_id, shop_id, proforma_id)
        )
        if row.get("status") not in {
            RentalProformaStatus.draft.value,
            RentalProformaStatus.issued.value,
            RentalProformaStatus.accepted.value,
        }:
            raise ValueError("Cette proforma ne peut plus etre annulee")
        updates: Dict[str, Any] = {
            "status": RentalProformaStatus.cancelled.value,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }
        self._append_note(updates, row, note)
        rows = (
            self.db.table("organization_rental_proformas")
            .update(updates)
            .eq("id", proforma_id)
            .execute()
            .data
            or []
        )
        if not rows:
            raise RuntimeError("Annulation de la facture proforma impossible")
        return self._attach_proforma_details(rows[0])

    def _existing_converted_order(self, proforma_id: str) -> Optional[Dict[str, Any]]:
        rows = (
            self.db.table("organization_rental_orders")
            .select("*")
            .eq("source_proforma_id", proforma_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    def convert_proforma(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._expire_if_due(
            self._get_proforma_row(organization_id, shop_id, proforma_id)
        )
        existing_order = self._existing_converted_order(proforma_id)
        if existing_order:
            if row.get("status") != RentalProformaStatus.converted.value:
                self.db.table("organization_rental_proformas").update(
                    {
                        "status": RentalProformaStatus.converted.value,
                        "converted_rental_order_id": str(existing_order["id"]),
                        "converted_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", proforma_id).execute()
            return {
                "proforma": self.get_proforma(
                    user_id, organization_id, shop_id, proforma_id
                ),
                "rental_order": self._attach_order_lines(existing_order),
            }

        if row.get("status") not in {
            RentalProformaStatus.issued.value,
            RentalProformaStatus.accepted.value,
        }:
            raise ValueError("Seule une proforma emise et valide peut etre convertie")
        confirmed_paid = sum(
            (
                self._money(payment.get("amount"))
                for payment in self._proforma_payments(proforma_id)
                if payment.get("status") == "confirmed"
            ),
            Decimal("0"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if confirmed_paid < self._money(row.get("advance_required_amount")):
            raise ValueError("Le montant requis doit etre paye avant la conversion")

        lines = self._proforma_lines(proforma_id)
        if not lines:
            raise ValueError("La proforma ne contient aucun actif louable")
        order_body = RentalOrderCreate(
            customer_name=row.get("customer_name"),
            customer_phone=row.get("customer_phone"),
            starts_at=self._parse_datetime(row["starts_at"]),
            ends_at=self._parse_datetime(row["ends_at"]),
            lines=[
                RentalOrderLineCreate(
                    rental_asset_id=line["rental_asset_id"],
                    quantity=int(line.get("quantity") or 0),
                    daily_rate=line.get("daily_rate"),
                    total_amount=line.get("line_subtotal"),
                    currency=line.get("currency"),
                )
                for line in lines
            ],
            deposit_amount=row.get("security_deposit_amount") or 0,
            discount_amount=row.get("discount_amount") or 0,
            discount_label=row.get("discount_label"),
            currency=row.get("currency"),
            assigned_member_id=row.get("assigned_member_id"),
            notes=row.get("notes"),
        )
        try:
            order = self.create_order(
                user_id,
                organization_id,
                shop_id,
                order_body,
                source_proforma_id=proforma_id,
            )
        except Exception:
            concurrent_order = self._existing_converted_order(proforma_id)
            if not concurrent_order:
                raise
            order = self._attach_order_lines(concurrent_order)
        now = datetime.now(timezone.utc).isoformat()
        updated = (
            self.db.table("organization_rental_proformas")
            .update(
                {
                    "status": RentalProformaStatus.converted.value,
                    "converted_rental_order_id": str(order["id"]),
                    "converted_at": now,
                    "accepted_at": row.get("accepted_at") or now,
                    "amount_paid": self._decimal(confirmed_paid),
                    "payment_status": (
                        "unpaid"
                        if confirmed_paid == 0
                        else (
                            "paid"
                            if confirmed_paid
                            >= self._money(row.get("total_payable_amount"))
                            else "partially_paid"
                        )
                    ),
                }
            )
            .eq("id", proforma_id)
            .execute()
            .data
            or []
        )
        if not updated:
            raise RuntimeError("La location a ete creee mais la proforma n'a pas ete finalisee")
        return {
            "proforma": self._attach_proforma_details(updated[0]),
            "rental_order": order,
        }

    def record_payment(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
        body: RentalProformaPaymentCreate,
    ) -> Dict[str, Any]:
        self._assert_rental_shop_access(user_id, organization_id, shop_id)
        row = self._expire_if_due(
            self._get_proforma_row(organization_id, shop_id, proforma_id)
        )
        if row.get("status") == RentalProformaStatus.converted.value:
            if body.idempotency_key:
                existing_retry = (
                    self.db.table("organization_rental_proforma_payments")
                    .select("id")
                    .eq("organization_id", organization_id)
                    .eq("rental_proforma_id", proforma_id)
                    .eq("idempotency_key", body.idempotency_key)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if existing_retry:
                    order = self._existing_converted_order(proforma_id)
                    return {
                        "proforma": self._attach_proforma_details(row),
                        "rental_order": self._attach_order_lines(order) if order else None,
                        "conversion_error": None,
                    }
            raise ValueError("Cette proforma a deja ete convertie en location")
        if row.get("status") not in {
            RentalProformaStatus.issued.value,
            RentalProformaStatus.accepted.value,
        }:
            raise ValueError("Le paiement exige une proforma emise et valide")
        currency = "xof"

        existing_payment = False
        if body.idempotency_key:
            existing = (
                self.db.table("organization_rental_proforma_payments")
                .select("*")
                .eq("organization_id", organization_id)
                .eq("idempotency_key", body.idempotency_key)
                .limit(1)
                .execute()
                .data
                or []
            )
            if existing and str(existing[0].get("rental_proforma_id")) != proforma_id:
                raise ValueError("Cette cle d'idempotence appartient a une autre proforma")
            existing_payment = bool(existing)

        current_payments = self._proforma_payments(proforma_id)
        current_paid = sum(
            (
                self._money(payment.get("amount"))
                for payment in current_payments
                if payment.get("status") == "confirmed"
            ),
            Decimal("0"),
        )
        total_payable = self._money(row.get("total_payable_amount"))
        if not existing_payment and current_paid + self._money(body.amount) > total_payable:
            raise ValueError("Le paiement depasse le solde restant de la proforma")

        if not existing_payment:
            try:
                self._insert_payment(
                    user_id, organization_id, shop_id, proforma_id, currency, body
                )
            except Exception:
                if not body.idempotency_key:
                    raise
                concurrent = (
                    self.db.table("organization_rental_proforma_payments")
                    .select("rental_proforma_id")
                    .eq("organization_id", organization_id)
                    .eq("idempotency_key", body.idempotency_key)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if not concurrent or str(concurrent[0].get("rental_proforma_id")) != proforma_id:
                    raise

        payments = self._proforma_payments(proforma_id)
        amount_paid = sum(
            (
                self._money(payment.get("amount"))
                for payment in payments
                if payment.get("status") == "confirmed"
            ),
            Decimal("0"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        required = self._money(row.get("advance_required_amount"))
        payment_status = "paid" if amount_paid >= total_payable else "partially_paid"
        now = datetime.now(timezone.utc).isoformat()
        updates: Dict[str, Any] = {
            "amount_paid": self._decimal(amount_paid),
            "payment_status": payment_status,
        }
        if amount_paid >= required:
            updates["status"] = RentalProformaStatus.accepted.value
            updates["accepted_at"] = row.get("accepted_at") or now
        updated = (
            self.db.table("organization_rental_proformas")
            .update(updates)
            .eq("id", proforma_id)
            .execute()
            .data
            or []
        )
        if not updated:
            raise RuntimeError("Mise a jour du paiement de la proforma impossible")

        if body.auto_convert and amount_paid >= required:
            try:
                return self.convert_proforma(
                    user_id,
                    organization_id,
                    shop_id,
                    proforma_id,
                )
            except ValueError as exc:
                return {
                    "proforma": self.get_proforma(
                        user_id, organization_id, shop_id, proforma_id
                    ),
                    "rental_order": None,
                    "conversion_error": str(exc),
                }
        return {
            "proforma": self._attach_proforma_details(updated[0]),
            "rental_order": None,
            "conversion_error": None,
        }

    def _insert_payment(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        proforma_id: str,
        currency: str,
        body: RentalProformaPaymentCreate,
    ) -> None:
        paid_at = body.paid_at or datetime.now(timezone.utc)
        self.db.table("organization_rental_proforma_payments").insert(
            {
                "rental_proforma_id": proforma_id,
                "organization_id": organization_id,
                "shop_id": shop_id,
                "amount": self._decimal(body.amount),
                "currency": currency,
                "payment_method": body.payment_method.strip().lower(),
                "payment_reference": body.payment_reference,
                "idempotency_key": body.idempotency_key,
                "status": "confirmed",
                "paid_at": paid_at.isoformat(),
                "note": body.note,
                "created_by_user_id": user_id,
            }
        ).execute()
