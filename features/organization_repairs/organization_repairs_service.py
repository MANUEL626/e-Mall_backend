from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_repairs.organization_repairs_models import (
    RepairActionRequest,
    RepairPartCreate,
    RepairRequestCreate,
    RepairRequestStatus,
    RepairRequestUpdate,
    RepairSendQuoteRequest,
)

_ALLOWED_STATUS_TRANSITIONS = {
    RepairRequestStatus.requested: {
        RepairRequestStatus.received,
        RepairRequestStatus.cancelled,
    },
    RepairRequestStatus.received: {
        RepairRequestStatus.diagnosing,
        RepairRequestStatus.cancelled,
    },
    RepairRequestStatus.diagnosing: {
        RepairRequestStatus.quote_sent,
        RepairRequestStatus.cancelled,
    },
    RepairRequestStatus.quote_sent: {
        RepairRequestStatus.approved,
        RepairRequestStatus.cancelled,
    },
    RepairRequestStatus.approved: {
        RepairRequestStatus.repairing,
        RepairRequestStatus.cancelled,
    },
    RepairRequestStatus.repairing: {
        RepairRequestStatus.ready_for_pickup,
        RepairRequestStatus.cancelled,
    },
    RepairRequestStatus.ready_for_pickup: {
        RepairRequestStatus.delivered,
        RepairRequestStatus.cancelled,
    },
    RepairRequestStatus.delivered: set(),
    RepairRequestStatus.cancelled: set(),
}


class OrganizationRepairsService:
    REPAIR_SELECT = (
        "id,organization_id,shop_id,customer_name,customer_phone,item_label,"
        "issue_description,diagnostic,quote_amount,currency,status,assigned_member_id,"
        "notes,created_by_user_id,received_at,completed_at,created_at,updated_at"
    )
    REPAIR_PART_SELECT = (
        "id,organization_id,shop_id,repair_request_id,resource_id,quantity,"
        "unit_cost,total_cost,currency,note,created_by_user_id,created_at"
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

    def _assert_repair_shop_access(
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
            .eq("shop_type", "repair")
            .neq("status", "archived")
            .limit(1)
            .execute()
        )
        if not (shop.data or []):
            raise ValueError("Boutique de reparation introuvable pour cette organisation")
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
            raise PermissionError("Affectation boutique repair requise")
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
            raise ValueError("Technicien introuvable dans cette organisation")
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
            raise ValueError("Le technicien doit etre affecte a cette boutique")

    def _get_row(self, organization_id: str, shop_id: str, repair_id: str) -> Dict[str, Any]:
        res = (
            self.db.table("organization_repair_requests")
            .select("*")
            .eq("id", repair_id)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise LookupError("Demande de reparation introuvable")
        return rows[0]

    def _get_repair_supply_stock(
        self,
        organization_id: str,
        shop_id: str,
        resource_id: str,
    ) -> Dict[str, Any]:
        stock = (
            self.db.table("organization_shop_article_stocks")
            .select("id,stock_quantity,reserved_quantity,active")
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("article_id", resource_id)
            .eq("stock_scope", "repair_supply")
            .limit(1)
            .execute()
        )
        rows = stock.data or []
        if not rows or rows[0].get("active") is not True:
            raise ValueError("Consommable de reparation indisponible dans cette boutique")
        article = (
            self.db.table("organization_articles")
            .select("id")
            .eq("id", resource_id)
            .eq("organization_id", organization_id)
            .eq("resource_scope", "repair_supply")
            .eq("active", True)
            .limit(1)
            .execute()
        )
        if not (article.data or []):
            raise ValueError("Consommable de reparation introuvable ou inactif")
        return rows[0]

    def _change_repair_supply_stock(
        self,
        organization_id: str,
        shop_id: str,
        resource_id: str,
        delta: int,
    ) -> None:
        stock = self._get_repair_supply_stock(organization_id, shop_id, resource_id)
        current_stock = int(stock.get("stock_quantity") or 0)
        reserved = int(stock.get("reserved_quantity") or 0)
        new_stock = current_stock + delta
        if new_stock < reserved:
            raise ValueError("Stock consommable insuffisant pour cette reparation")
        self.db.table("organization_shop_article_stocks").update(
            {"stock_quantity": new_stock}
        ).eq("id", str(stock["id"])).execute()

    def _decrement_repair_supply(
        self,
        organization_id: str,
        shop_id: str,
        resource_id: str,
        quantity: int,
    ) -> None:
        self._change_repair_supply_stock(
            organization_id,
            shop_id,
            resource_id,
            -quantity,
        )

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
    def _status(value: Any) -> RepairRequestStatus:
        try:
            return RepairRequestStatus(value)
        except ValueError as exc:
            raise ValueError("Statut de reparation invalide") from exc

    @staticmethod
    def _append_note(updates: Dict[str, Any], row: Dict[str, Any], note: Optional[str]) -> None:
        if not note:
            return
        current = row.get("notes") or ""
        updates["notes"] = f"{current}\n{note}".strip() if current else note

    def _transition_status(
        self,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        target_status: RepairRequestStatus,
        *,
        row: Optional[Dict[str, Any]] = None,
        note: Optional[str] = None,
        extra_updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current_row = row or self._get_row(organization_id, shop_id, repair_id)
        current_status = self._status(current_row.get("status"))
        if current_status == target_status:
            updates = dict(extra_updates or {})
            if not updates:
                return current_row
        else:
            allowed = _ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
            if target_status not in allowed:
                raise ValueError(
                    "Transition reparation invalide: "
                    f"{current_status.value} -> {target_status.value}"
                )
            updates = {"status": target_status.value, **(extra_updates or {})}

        now = datetime.now(timezone.utc).isoformat()
        if target_status == RepairRequestStatus.received and not current_row.get("received_at"):
            updates["received_at"] = now
        if target_status in (RepairRequestStatus.delivered, RepairRequestStatus.cancelled):
            updates["completed_at"] = now
        self._append_note(updates, current_row, note)

        rows = (
            self.db.table("organization_repair_requests")
            .update(updates)
            .eq("id", repair_id)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .execute()
            .data
            or []
        )
        if not rows:
            raise LookupError("Demande de reparation introuvable")
        return rows[0]

    @staticmethod
    def _invoice_number(repair_row: Dict[str, Any]) -> str:
        created_at = str(repair_row.get("created_at") or "")
        compact_date = created_at[:10].replace("-", "") if created_at else "nodate"
        return f"RINV-{compact_date}-{str(repair_row['id'])[:8].upper()}"

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

    def _select_invoice_by_repair_id(self, repair_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("organization_repair_invoices")
            .select("*")
            .eq("repair_request_id", repair_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def _build_invoice_payload(self, repair_row: Dict[str, Any]) -> Dict[str, Any]:
        if repair_row.get("status") != RepairRequestStatus.delivered.value:
            raise ValueError(
                "La facture est disponible uniquement pour une reparation livree"
            )

        organization_id = str(repair_row["organization_id"])
        shop_id = str(repair_row["shop_id"])
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
        part_rows = (
            self.db.table("organization_repair_request_parts")
            .select("*")
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("repair_request_id", str(repair_row["id"]))
            .order("created_at", desc=False)
            .execute()
            .data
            or []
        )

        resource_ids = sorted(
            {
                str(part.get("resource_id"))
                for part in part_rows
                if part.get("resource_id")
            }
        )
        resources_by_id: Dict[str, Dict[str, Any]] = {}
        if resource_ids:
            resources = (
                self.db.table("organization_articles")
                .select("id,name,category,resource_scope")
                .in_("id", resource_ids)
                .execute()
                .data
                or []
            )
            resources_by_id = {str(row["id"]): row for row in resources}

        parts_snapshot: List[Dict[str, Any]] = []
        parts_amount = Decimal("0")
        total_parts = 0
        for part in part_rows:
            quantity = int(part.get("quantity") or 0)
            unit_cost = self._money(part.get("unit_cost"))
            line_total = self._money(part.get("total_cost"))
            parts_amount += line_total
            total_parts += quantity
            resource = resources_by_id.get(str(part.get("resource_id"))) or {}
            parts_snapshot.append(
                {
                    "part_id": part.get("id"),
                    "resource_id": part.get("resource_id"),
                    "resource_name": resource.get("name"),
                    "resource_category": resource.get("category"),
                    "quantity": quantity,
                    "unit_cost": str(unit_cost),
                    "currency": "xof",
                    "line_total": str(line_total),
                    "note": part.get("note"),
                }
            )

        labor_amount = self._money(repair_row.get("quote_amount"))
        total_amount = (labor_amount + parts_amount).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        customer_label = repair_row.get("customer_name") or repair_row.get("customer_phone")
        return {
            "repair_request_id": str(repair_row["id"]),
            "organization_id": organization_id,
            "shop_id": shop_id,
            "invoice_number": self._invoice_number(repair_row),
            "currency": "xof",
            "labor_amount": float(labor_amount),
            "parts_amount": float(parts_amount),
            "total_amount": float(total_amount),
            "total_parts": total_parts,
            "total_lines": len(parts_snapshot),
            "status": "issued",
            "customer_label": customer_label,
            "organization_snapshot": self._public_org_snapshot(
                dict((org_res.data or [{}])[0]) if org_res.data else None
            ),
            "shop_snapshot": self._public_shop_snapshot(
                dict((shop_res.data or [{}])[0]) if shop_res.data else None
            ),
            "repair_snapshot": {
                "id": repair_row.get("id"),
                "customer_name": repair_row.get("customer_name"),
                "customer_phone": repair_row.get("customer_phone"),
                "item_label": repair_row.get("item_label"),
                "issue_description": repair_row.get("issue_description"),
                "diagnostic": repair_row.get("diagnostic"),
                "quote_amount": str(labor_amount),
                "currency": "xof",
                "assigned_member_id": repair_row.get("assigned_member_id"),
                "received_at": repair_row.get("received_at"),
                "completed_at": repair_row.get("completed_at"),
            },
            "parts_snapshot": parts_snapshot,
        }

    def _ensure_invoice_for_delivered_repair(
        self,
        repair_row: Dict[str, Any],
    ) -> Dict[str, Any]:
        repair_id = str(repair_row["id"])
        existing = self._select_invoice_by_repair_id(repair_id)
        if existing:
            return existing

        payload = self._build_invoice_payload(repair_row)
        try:
            inserted = self.db.table("organization_repair_invoices").insert(payload).execute()
        except Exception:
            existing = self._select_invoice_by_repair_id(repair_id)
            if existing:
                return existing
            raise
        rows = inserted.data or []
        if not rows:
            raise RuntimeError("Creation de la facture reparation refusee")
        return rows[0]

    def list_repairs(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        status: Optional[RepairRequestStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        page_limit = max(1, min(int(limit or 50), 200))
        page_offset = max(0, int(offset or 0))
        q = (
            self.db.table("organization_repair_requests")
            .select(self.REPAIR_SELECT)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .order("created_at", desc=True)
            .range(page_offset, page_offset + page_limit - 1)
        )
        if status is not None:
            q = q.eq("status", status.value)
        return list(q.execute().data or [])

    def create_repair(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        body: RepairRequestCreate,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        assigned = str(body.assigned_member_id) if body.assigned_member_id else None
        self._assert_assigned_member(organization_id, shop_id, assigned)
        payload = {
            "organization_id": organization_id,
            "shop_id": shop_id,
            "customer_name": body.customer_name,
            "customer_phone": body.customer_phone,
            "item_label": body.item_label,
            "issue_description": body.issue_description,
            "diagnostic": body.diagnostic,
            "quote_amount": self._decimal(body.quote_amount),
            "currency": "xof",
            "assigned_member_id": assigned,
            "notes": body.notes,
            "status": RepairRequestStatus.requested.value,
            "created_by_user_id": user_id,
        }
        rows = (
            self.db.table("organization_repair_requests")
            .insert(payload)
            .execute()
            .data
            or []
        )
        if not rows:
            raise RuntimeError("Creation de la demande de reparation impossible")
        return rows[0]

    def get_repair(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._get_row(organization_id, shop_id, repair_id)

    def update_repair(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairRequestUpdate,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        _ = self._get_row(organization_id, shop_id, repair_id)
        updates: Dict[str, Any] = {}
        for field in (
            "customer_name",
            "customer_phone",
            "item_label",
            "issue_description",
            "diagnostic",
            "notes",
        ):
            value = getattr(body, field)
            if value is not None:
                updates[field] = value
        if body.quote_amount is not None:
            updates["quote_amount"] = self._decimal(body.quote_amount)
        if body.currency is not None:
            updates["currency"] = "xof"
        if body.assigned_member_id is not None:
            assigned = str(body.assigned_member_id)
            self._assert_assigned_member(organization_id, shop_id, assigned)
            updates["assigned_member_id"] = assigned
        if not updates:
            raise ValueError("Aucune mise a jour fournie")
        rows = (
            self.db.table("organization_repair_requests")
            .update(updates)
            .eq("id", repair_id)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .execute()
            .data
            or []
        )
        if not rows:
            raise LookupError("Demande de reparation introuvable")
        return rows[0]

    def update_status(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        status: RepairRequestStatus,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            status,
            note=note,
        )

    def receive_repair(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairActionRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.received,
            note=body.note,
        )

    def start_diagnosis(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairActionRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.diagnosing,
            note=body.note,
        )

    def send_quote(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairSendQuoteRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        row = self._get_row(organization_id, shop_id, repair_id)
        updates: Dict[str, Any] = {}
        if body.diagnostic is not None:
            updates["diagnostic"] = body.diagnostic
        if body.quote_amount is not None:
            updates["quote_amount"] = self._decimal(body.quote_amount)
        if body.currency is not None:
            updates["currency"] = "xof"
        quote_amount = updates.get("quote_amount") or row.get("quote_amount")
        if quote_amount in (None, ""):
            raise ValueError("Un montant de devis est requis avant d'envoyer le devis")
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.quote_sent,
            row=row,
            note=body.note,
            extra_updates=updates,
        )

    def approve_quote(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairActionRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.approved,
            note=body.note,
        )

    def start_repair(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairActionRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.repairing,
            note=body.note,
        )

    def mark_ready(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairActionRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.ready_for_pickup,
            note=body.note,
        )

    def deliver_repair(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairActionRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        row = self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.delivered,
            note=body.note,
        )
        self._ensure_invoice_for_delivered_repair(row)
        return row

    def cancel_repair(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairActionRequest,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        return self._transition_status(
            organization_id,
            shop_id,
            repair_id,
            RepairRequestStatus.cancelled,
            note=body.note,
        )

    def get_invoice(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        repair = self._get_row(organization_id, shop_id, repair_id)
        return self._ensure_invoice_for_delivered_repair(repair)

    def list_parts(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
    ) -> List[Dict[str, Any]]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        _ = self._get_row(organization_id, shop_id, repair_id)
        rows = (
            self.db.table("organization_repair_request_parts")
            .select(self.REPAIR_PART_SELECT)
            .eq("organization_id", organization_id)
            .eq("shop_id", shop_id)
            .eq("repair_request_id", repair_id)
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
        return list(rows)

    def add_part(
        self,
        user_id: str,
        organization_id: str,
        shop_id: str,
        repair_id: str,
        body: RepairPartCreate,
    ) -> Dict[str, Any]:
        self._assert_repair_shop_access(user_id, organization_id, shop_id)
        repair = self._get_row(organization_id, shop_id, repair_id)
        repair_status = self._status(repair.get("status"))
        if repair_status not in (RepairRequestStatus.approved, RepairRequestStatus.repairing):
            raise ValueError(
                "Les consommables ne peuvent etre ajoutes qu'apres validation du devis "
                "ou pendant la reparation"
            )
        resource_id = str(body.resource_id)
        total = (
            body.total_cost
            if body.total_cost is not None
            else (
                (body.unit_cost or Decimal("0")) * Decimal(body.quantity)
            )
        )
        self._decrement_repair_supply(
            organization_id,
            shop_id,
            resource_id,
            body.quantity,
        )
        payload = {
            "organization_id": organization_id,
            "shop_id": shop_id,
            "repair_request_id": repair_id,
            "resource_id": resource_id,
            "quantity": body.quantity,
            "unit_cost": self._decimal(body.unit_cost),
            "total_cost": self._decimal(total) or "0",
            "currency": "xof",
            "note": body.note,
            "created_by_user_id": user_id,
        }
        try:
            rows = (
                self.db.table("organization_repair_request_parts")
                .insert(payload)
                .execute()
                .data
                or []
            )
        except Exception:
            self._change_repair_supply_stock(
                organization_id,
                shop_id,
                resource_id,
                body.quantity,
            )
            raise
        if not rows:
            self._change_repair_supply_stock(
                organization_id,
                shop_id,
                resource_id,
                body.quantity,
            )
            raise RuntimeError("Ajout de piece impossible")
        if repair_status == RepairRequestStatus.approved:
            self._transition_status(
                organization_id,
                shop_id,
                repair_id,
                RepairRequestStatus.repairing,
                row=repair,
                note="Reparation demarree automatiquement apres ajout de consommable",
            )
        return rows[0]
