"""
Internal subscription engine for organizations.

Stripe will later update `organization_subscriptions`; product code should keep
reading entitlements from this service.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from supabase import Client

from config.supabase_client import supabase_admin


class OrganizationSubscriptionNotFound(Exception):
    """No organization exists for the requested id."""


class OrganizationSubscriptionForbidden(Exception):
    """The user is not allowed to read or update this subscription."""


class OrganizationSubscriptionFeatureDenied(Exception):
    """The current plan does not allow the requested feature."""


class OrganizationSubscriptionLimitExceeded(Exception):
    """The current plan limit is reached."""


class OrganizationSubscriptionPaymentError(Exception):
    """Stripe payment or billing action failed."""


class OrganizationSubscriptionService:
    ACTIVE_STATUSES = {"active", "trialing"}
    _plans_cache: Optional[tuple[datetime, List[Dict[str, Any]]]] = None
    _plan_cache_ttl = timedelta(minutes=5)
    _stripe_api_base = "https://api.stripe.com/v1"

    def __init__(self) -> None:
        self.db: Client = supabase_admin

    def _membership(
        self,
        user_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        res = (
            self.db.table("members")
            .select("member_type,activity_status")
            .eq("user_id", user_id)
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def assert_org_member(self, user_id: str, organization_id: str) -> Dict[str, Any]:
        membership = self._membership(user_id, organization_id)
        if not membership or membership.get("activity_status") is not True:
            raise OrganizationSubscriptionForbidden(
                "Acces refuse pour cette organisation"
            )
        return membership

    def assert_org_admin(self, user_id: str, organization_id: str) -> Dict[str, Any]:
        membership = self.assert_org_member(user_id, organization_id)
        if membership.get("member_type") != "admin":
            raise OrganizationSubscriptionForbidden(
                "Seul un administrateur peut modifier l'abonnement"
            )
        return membership

    @staticmethod
    def _decimal_or_none(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @classmethod
    def _enrich_plan_pricing(cls, plan: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(plan)
        monthly = cls._decimal_or_none(row.get("monthly_price_amount"))
        yearly = cls._decimal_or_none(row.get("yearly_price_amount"))
        yearly_full_price = monthly * Decimal("12") if monthly is not None else None

        row.setdefault("price_currency", "xof")
        row["yearly_savings_amount"] = None
        row["yearly_savings_percent"] = None
        if (
            yearly_full_price is not None
            and yearly is not None
            and yearly_full_price > 0
            and yearly <= yearly_full_price
        ):
            savings = yearly_full_price - yearly
            percent = (savings / yearly_full_price) * Decimal("100")
            row["yearly_savings_amount"] = savings.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            row["yearly_savings_percent"] = percent.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        return row

    def list_plans(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        if self._plans_cache is not None:
            cached_at, rows = self._plans_cache
            if now - cached_at < self._plan_cache_ttl:
                return [self._enrich_plan_pricing(row) for row in rows]

        res = (
            self.db.table("organization_subscription_plans")
            .select("*")
            .eq("active", True)
            .order("sort_order", desc=False)
            .execute()
        )
        rows = list(res.data or [])
        self.__class__._plans_cache = (now, rows)
        return [self._enrich_plan_pricing(row) for row in rows]

    def _get_plan(self, plan_code: str) -> Optional[Dict[str, Any]]:
        for row in self.list_plans():
            if str(row.get("code")) == plan_code:
                return row
        return None

    @staticmethod
    def _stripe_price_id_for_interval(
        plan: Dict[str, Any],
        billing_interval: str,
    ) -> Optional[str]:
        if billing_interval == "yearly":
            return plan.get("stripe_yearly_price_id")
        return plan.get("stripe_monthly_price_id")

    @staticmethod
    def _timestamp_from_unix(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _stripe_status_to_internal(status: str) -> str:
        if status in {"active", "trialing", "past_due"}:
            return status
        if status in {"canceled", "cancelled"}:
            return "canceled"
        if status in {"incomplete_expired"}:
            return "expired"
        if status in {"unpaid", "incomplete", "paused"}:
            return "past_due"
        return "past_due"

    def _stripe_secret_key(self) -> str:
        key = os.getenv("STRIPE_SECRET_KEY", "").strip()
        if not key:
            raise OrganizationSubscriptionPaymentError("STRIPE_SECRET_KEY manquant")
        return key

    def _stripe_webhook_secret(self) -> str:
        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise OrganizationSubscriptionPaymentError("STRIPE_WEBHOOK_SECRET manquant")
        return secret

    def _stripe_request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self._stripe_api_base}{path}"
        try:
            response = requests.request(
                method,
                url,
                auth=(self._stripe_secret_key(), ""),
                data=data,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise OrganizationSubscriptionPaymentError(
                "Stripe indisponible pour le moment"
            ) from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
                message = payload.get("error", {}).get("message")
            except ValueError:
                message = response.text
            raise OrganizationSubscriptionPaymentError(
                message or "Erreur Stripe"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise OrganizationSubscriptionPaymentError(
                "Reponse Stripe invalide"
            ) from exc

    def _get_user_email(self, user_id: str) -> Optional[str]:
        res = (
            self.db.table("users")
            .select("email")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        email = rows[0].get("email")
        return str(email) if email else None

    def _plan_for_price_id(self, price_id: str) -> Optional[Dict[str, str]]:
        for plan in self.list_plans():
            if plan.get("stripe_monthly_price_id") == price_id:
                return {"plan": str(plan.get("code")), "billing_interval": "monthly"}
            if plan.get("stripe_yearly_price_id") == price_id:
                return {"plan": str(plan.get("code")), "billing_interval": "yearly"}
        return None

    def create_checkout_session(
        self,
        user_id: str,
        organization_id: str,
        plan_code: str,
        billing_interval: str,
    ) -> Dict[str, Any]:
        self.assert_org_admin(user_id, organization_id)
        if plan_code == "freemium":
            raise ValueError("Le plan freemium ne necessite pas de paiement Stripe")
        if billing_interval not in {"monthly", "yearly"}:
            raise ValueError("billing_interval doit etre monthly ou yearly")

        plan = self._get_plan(plan_code)
        if plan is None:
            raise ValueError("Plan d'abonnement introuvable ou inactif")

        price_id = self._stripe_price_id_for_interval(plan, billing_interval)
        if not price_id:
            raise ValueError("Price Stripe non configure pour ce plan et ce cycle")

        subscription = self._ensure_subscription(organization_id)
        success_url = os.getenv("STRIPE_SUCCESS_URL", "").strip()
        cancel_url = os.getenv("STRIPE_CANCEL_URL", "").strip()
        if not success_url or not cancel_url:
            raise OrganizationSubscriptionPaymentError(
                "STRIPE_SUCCESS_URL et STRIPE_CANCEL_URL sont requis"
            )

        data: Dict[str, Any] = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": organization_id,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": 1,
            "metadata[organization_id]": organization_id,
            "metadata[plan]": plan_code,
            "metadata[billing_interval]": billing_interval,
            "subscription_data[metadata][organization_id]": organization_id,
            "subscription_data[metadata][plan]": plan_code,
            "subscription_data[metadata][billing_interval]": billing_interval,
        }

        stripe_customer_id = subscription.get("stripe_customer_id")
        if stripe_customer_id:
            data["customer"] = stripe_customer_id
        else:
            email = self._get_user_email(user_id)
            if email:
                data["customer_email"] = email

        session = self._stripe_request("POST", "/checkout/sessions", data=data)
        return {
            "checkout_session_id": session["id"],
            "checkout_url": session["url"],
        }

    def create_billing_portal_session(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_admin(user_id, organization_id)
        subscription = self._ensure_subscription(organization_id)
        stripe_customer_id = subscription.get("stripe_customer_id")
        if not stripe_customer_id:
            raise ValueError("Aucun customer Stripe n'est lie a cette organisation")

        return_url = (
            os.getenv("STRIPE_PORTAL_RETURN_URL", "").strip()
            or os.getenv("STRIPE_SUCCESS_URL", "").strip()
        )
        if not return_url:
            raise OrganizationSubscriptionPaymentError(
                "STRIPE_PORTAL_RETURN_URL ou STRIPE_SUCCESS_URL est requis"
            )

        session = self._stripe_request(
            "POST",
            "/billing_portal/sessions",
            data={"customer": stripe_customer_id, "return_url": return_url},
        )
        return {"portal_url": session["url"]}

    def _format_stripe_invoice(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(invoice.get("id") or ""),
            "number": invoice.get("number"),
            "status": invoice.get("status"),
            "currency": invoice.get("currency"),
            "amount_due": int(invoice.get("amount_due") or 0),
            "amount_paid": int(invoice.get("amount_paid") or 0),
            "amount_remaining": int(invoice.get("amount_remaining") or 0),
            "created": self._timestamp_from_unix(invoice.get("created")),
            "due_date": self._timestamp_from_unix(invoice.get("due_date")),
            "period_start": self._timestamp_from_unix(invoice.get("period_start")),
            "period_end": self._timestamp_from_unix(invoice.get("period_end")),
            "hosted_invoice_url": invoice.get("hosted_invoice_url"),
            "invoice_pdf": invoice.get("invoice_pdf"),
            "subscription_id": invoice.get("subscription"),
        }

    def list_invoices(
        self,
        user_id: str,
        organization_id: str,
        *,
        limit: int = 20,
    ) -> Dict[str, Any]:
        self.assert_org_admin(user_id, organization_id)
        subscription = self._ensure_subscription(organization_id)
        stripe_customer_id = subscription.get("stripe_customer_id")
        if not stripe_customer_id:
            return {"invoices": []}

        clean_limit = max(1, min(int(limit), 100))
        query = urlencode(
            {
                "customer": str(stripe_customer_id),
                "limit": clean_limit,
            }
        )
        payload = self._stripe_request("GET", f"/invoices?{query}")
        rows = payload.get("data") or []
        return {
            "invoices": [
                self._format_stripe_invoice(invoice)
                for invoice in rows
                if invoice.get("id")
            ]
        }

    def _retrieve_subscription(self, subscription_id: str) -> Dict[str, Any]:
        query = urlencode({"expand[]": "items.data.price"})
        return self._stripe_request("GET", f"/subscriptions/{subscription_id}?{query}")

    def _retrieve_invoice(self, invoice_id: str) -> Dict[str, Any]:
        return self._stripe_request("GET", f"/invoices/{invoice_id}")

    def _organization_id_for_subscription(
        self,
        stripe_subscription_id: str,
    ) -> Optional[str]:
        res = (
            self.db.table("organization_subscriptions")
            .select("organization_id")
            .eq("stripe_subscription_id", stripe_subscription_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return str(rows[0].get("organization_id"))
        return None

    def sync_stripe_subscription(self, subscription: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        metadata = subscription.get("metadata") or {}
        organization_id = metadata.get("organization_id")
        if not organization_id:
            organization_id = self._organization_id_for_subscription(str(subscription.get("id")))
        if not organization_id:
            return None

        item_rows = ((subscription.get("items") or {}).get("data") or [])
        price = (item_rows[0].get("price") if item_rows else {}) or {}
        price_id = price.get("id")
        plan_interval = self._plan_for_price_id(str(price_id)) if price_id else None

        plan_code = str(metadata.get("plan") or (plan_interval or {}).get("plan") or "freemium")
        billing_interval = str(
            metadata.get("billing_interval")
            or (plan_interval or {}).get("billing_interval")
            or ((price.get("recurring") or {}).get("interval"))
            or "monthly"
        )
        if billing_interval == "year":
            billing_interval = "yearly"
        if billing_interval not in {"monthly", "yearly"}:
            billing_interval = "monthly"

        payload = {
            "plan": plan_code,
            "status": self._stripe_status_to_internal(str(subscription.get("status") or "")),
            "source": "stripe",
            "billing_interval": billing_interval,
            "stripe_customer_id": subscription.get("customer"),
            "stripe_subscription_id": subscription.get("id"),
            "stripe_price_id": price_id,
            "current_period_start": self._timestamp_from_unix(
                subscription.get("current_period_start")
            ),
            "current_period_end": self._timestamp_from_unix(
                subscription.get("current_period_end")
            ),
            "trial_end": self._timestamp_from_unix(subscription.get("trial_end")),
            "cancel_at_period_end": bool(subscription.get("cancel_at_period_end")),
            "metadata": {
                "stripe_latest_event_sync": datetime.now(timezone.utc).isoformat(),
            },
        }
        clean_payload = {key: value for key, value in payload.items() if value is not None}
        res = (
            self.db.table("organization_subscriptions")
            .update(clean_payload)
            .eq("organization_id", str(organization_id))
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        plan = self._get_plan(str(rows[0].get("plan")))
        return {**rows[0], "plan_details": plan}

    def verify_stripe_signature(self, payload: bytes, signature_header: str) -> None:
        secret = self._stripe_webhook_secret()
        parts: Dict[str, str] = {}
        for item in signature_header.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                parts[key] = value

        timestamp = parts.get("t")
        expected_signature = parts.get("v1")
        if not timestamp or not expected_signature:
            raise OrganizationSubscriptionPaymentError("Signature Stripe invalide")

        try:
            event_time = int(timestamp)
        except ValueError as exc:
            raise OrganizationSubscriptionPaymentError("Timestamp Stripe invalide") from exc

        now = int(datetime.now(timezone.utc).timestamp())
        if abs(now - event_time) > 300:
            raise OrganizationSubscriptionPaymentError("Signature Stripe expiree")

        signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, expected_signature):
            raise OrganizationSubscriptionPaymentError("Signature Stripe invalide")

    def handle_stripe_webhook(
        self,
        payload: bytes,
        signature_header: str,
    ) -> Dict[str, Any]:
        self.verify_stripe_signature(payload, signature_header)
        try:
            event = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OrganizationSubscriptionPaymentError("Payload Stripe invalide") from exc

        event_type = str(event.get("type") or "")
        obj = ((event.get("data") or {}).get("object") or {})
        synced: Optional[Dict[str, Any]] = None

        if event_type == "checkout.session.completed":
            subscription_id = obj.get("subscription")
            if subscription_id:
                synced = self.sync_stripe_subscription(
                    self._retrieve_subscription(str(subscription_id))
                )
        elif event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            synced = self.sync_stripe_subscription(obj)
        elif event_type in {"invoice.payment_succeeded", "invoice.payment_failed"}:
            subscription_id = obj.get("subscription")
            if not subscription_id and obj.get("id"):
                invoice = self._retrieve_invoice(str(obj["id"]))
                subscription_id = invoice.get("subscription")
            if subscription_id:
                synced = self.sync_stripe_subscription(
                    self._retrieve_subscription(str(subscription_id))
                )

        return {
            "received": True,
            "event_type": event_type,
            "synced": synced is not None,
        }

    def _organization_exists(self, organization_id: str) -> bool:
        res = (
            self.db.table("organizations")
            .select("id")
            .eq("id", organization_id)
            .limit(1)
            .execute()
        )
        return bool(res.data)

    def _ensure_subscription(self, organization_id: str) -> Dict[str, Any]:
        res = (
            self.db.table("organization_subscriptions")
            .select("*")
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]

        if not self._organization_exists(organization_id):
            raise OrganizationSubscriptionNotFound()

        created = (
            self.db.table("organization_subscriptions")
            .insert(
                {
                    "organization_id": organization_id,
                    "plan": "freemium",
                    "status": "active",
                    "source": "internal",
                    "metadata": {"created_by_api": True},
                }
            )
            .execute()
        )
        created_rows = created.data or []
        if not created_rows:
            raise OrganizationSubscriptionNotFound()
        return created_rows[0]

    def get_subscription(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        subscription = self._ensure_subscription(organization_id)
        plan = self._get_plan(str(subscription.get("plan")))
        return {**subscription, "plan_details": plan}

    def update_subscription(
        self,
        user_id: str,
        organization_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.assert_org_admin(user_id, organization_id)
        current = self._ensure_subscription(organization_id)

        payload = {k: v for k, v in updates.items() if v is not None}
        if payload.get("source") is None:
            payload.pop("source", None)
        if "metadata" in payload and payload["metadata"] is None:
            payload.pop("metadata", None)
        if not payload:
            raise ValueError("Aucune donnee d'abonnement a mettre a jour")

        plan_code = str(payload.get("plan") or current.get("plan") or "freemium")
        plan = self._get_plan(plan_code)
        if plan is None:
            raise ValueError("Plan d'abonnement introuvable ou inactif")

        billing_interval = str(
            payload.get("billing_interval")
            or current.get("billing_interval")
            or "monthly"
        )
        if billing_interval not in {"monthly", "yearly"}:
            raise ValueError("billing_interval doit etre monthly ou yearly")

        if "stripe_price_id" not in payload and (
            "plan" in payload or "billing_interval" in payload
        ):
            price_id = self._stripe_price_id_for_interval(plan, billing_interval)
            payload["stripe_price_id"] = price_id

        res = (
            self.db.table("organization_subscriptions")
            .update(payload)
            .eq("organization_id", organization_id)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise OrganizationSubscriptionNotFound()
        plan = self._get_plan(str(rows[0].get("plan")))
        return {**rows[0], "plan_details": plan}

    def _count_active_articles(self, organization_id: str) -> int:
        res = (
            self.db.table("organization_articles")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        return int(getattr(res, "count", None) or len(res.data or []))

    def _count_team_members(self, organization_id: str) -> int:
        res = (
            self.db.table("members")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        return int(getattr(res, "count", None) or len(res.data or []))

    def _count_monthly_walk_in_sales(self, organization_id: str) -> int:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        res = (
            self.db.table("organization_customer_sale_orders")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("fulfillment_type", "walk_in_offline")
            .gte("created_at", month_start.isoformat())
            .limit(1)
            .execute()
        )
        return int(getattr(res, "count", None) or len(res.data or []))

    def _usage_count_for_limit(self, organization_id: str, limit_key: str) -> int:
        if limit_key == "active_articles":
            return self._count_active_articles(organization_id)
        if limit_key == "team_members":
            return self._count_team_members(organization_id)
        if limit_key == "monthly_walk_in_sales":
            return self._count_monthly_walk_in_sales(organization_id)
        return 0

    @staticmethod
    def _limit_exceeded(limit_value: Any, usage_value: int) -> bool:
        if limit_value is None:
            return False
        try:
            return usage_value > int(limit_value)
        except (TypeError, ValueError):
            return False

    def get_entitlements(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        subscription = self.get_subscription(user_id, organization_id)
        return self._build_entitlements(organization_id, subscription)

    def get_entitlements_for_org(self, organization_id: str) -> Dict[str, Any]:
        subscription = self._ensure_subscription(organization_id)
        plan = self._get_plan(str(subscription.get("plan")))
        return self._build_entitlements(
            organization_id,
            {**subscription, "plan_details": plan},
        )

    def _build_entitlements(
        self,
        organization_id: str,
        subscription: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan = subscription.get("plan_details") or {}
        features = plan.get("features") or {}
        limits = plan.get("limits") or {}
        usage = {
            "active_articles": self._count_active_articles(organization_id),
            "team_members": self._count_team_members(organization_id),
            "monthly_walk_in_sales": self._count_monthly_walk_in_sales(organization_id),
        }
        exceeded_limits = {
            key: self._limit_exceeded(limits.get(key), value)
            for key, value in usage.items()
        }
        return {
            "organization_id": organization_id,
            "plan": subscription.get("plan"),
            "status": subscription.get("status"),
            "is_active": subscription.get("status") in self.ACTIVE_STATUSES,
            "features": features,
            "limits": limits,
            "usage": usage,
            "exceeded_limits": exceeded_limits,
            "subscription": subscription,
        }

    def assert_feature_enabled(self, organization_id: str, feature: str) -> None:
        subscription = self._ensure_subscription(organization_id)
        if subscription.get("status") not in self.ACTIVE_STATUSES:
            raise OrganizationSubscriptionFeatureDenied(
                "Abonnement inactif pour cette organisation"
            )
        plan = self._get_plan(str(subscription.get("plan"))) or {}
        value = (plan.get("features") or {}).get(feature)
        if value is not True:
            raise OrganizationSubscriptionFeatureDenied(
                f"Fonctionnalite non incluse dans l'abonnement: {feature}"
            )

    def assert_usage_below_limit(
        self,
        organization_id: str,
        limit_key: str,
        *,
        increment: int = 1,
    ) -> None:
        subscription = self._ensure_subscription(organization_id)
        if subscription.get("status") not in self.ACTIVE_STATUSES:
            raise OrganizationSubscriptionLimitExceeded(
                "Abonnement inactif pour cette organisation"
            )
        plan = self._get_plan(str(subscription.get("plan"))) or {}
        limits = plan.get("limits") or {}
        limit_value = limits.get(limit_key)
        if limit_value is None:
            return
        current = self._usage_count_for_limit(organization_id, limit_key)
        try:
            maximum = int(limit_value)
        except (TypeError, ValueError):
            return
        if current + increment > maximum:
            raise OrganizationSubscriptionLimitExceeded(
                f"Limite d'abonnement atteinte pour {limit_key}: {current}/{maximum}"
            )
