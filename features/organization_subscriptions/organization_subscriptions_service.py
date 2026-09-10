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
    KNOWN_FEATURE_KEYS = {
        "basic_catalog",
        "simple_stock",
        "walk_in_sales",
        "article_posts",
        "supplier_orders",
        "pickup_delivery",
        "delivery_assignment",
        "delivery_status_history",
        "ai_performance_agent",
        "team_customer_messaging",
        "advanced_roles",
        "realtime_gps",
        "priority_support",
        "multi_shops",
        "sales_shops",
        "delivery_shops",
        "repair_shops",
        "rental_shops",
        "repair_domain",
        "rental_domain",
        "rental_asset_posts",
        "delivery_realtime_ws",
        "sale_receipts",
        "repair_invoices",
        "subscription_invoices",
    }
    _plans_cache: Optional[tuple[datetime, List[Dict[str, Any]]]] = None
    _plan_cache_ttl = timedelta(minutes=5)
    _stripe_api_base = "https://api.stripe.com/v1"

    @staticmethod
    def ai_reports_enabled() -> bool:
        return os.getenv("AI_REPORTS_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

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
        plan_code = str(row.get("code") or "").upper()
        monthly_price_id = os.getenv(f"STRIPE_{plan_code}_MONTHLY_PRICE_ID", "").strip()
        yearly_price_id = os.getenv(f"STRIPE_{plan_code}_YEARLY_PRICE_ID", "").strip()
        if monthly_price_id:
            row["stripe_monthly_price_id"] = monthly_price_id
        if yearly_price_id:
            row["stripe_yearly_price_id"] = yearly_price_id
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

    @classmethod
    def _stripe_price_id_for_interval(
        cls,
        plan: Dict[str, Any],
        billing_interval: str,
    ) -> Optional[str]:
        plan_code = str(plan.get("code") or "").upper()
        interval_name = "YEARLY" if billing_interval == "yearly" else "MONTHLY"
        env_price_id = os.getenv(f"STRIPE_{plan_code}_{interval_name}_PRICE_ID", "").strip()
        if env_price_id:
            return env_price_id
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
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _effective_status(self, subscription: Dict[str, Any]) -> str:
        status = str(subscription.get("status") or "expired")
        if status not in self.ACTIVE_STATUSES:
            return status

        period_end = self._parse_datetime(subscription.get("current_period_end"))
        if period_end is not None and period_end < datetime.now(timezone.utc):
            return "expired"

        return status

    def _effective_plan_code(self, subscription: Dict[str, Any]) -> str:
        if self._effective_status(subscription) not in self.ACTIVE_STATUSES:
            return "freemium"
        plan_code = str(subscription.get("plan") or "freemium")
        return plan_code if self._get_plan(plan_code) is not None else "freemium"

    def _decorate_subscription(self, subscription: Dict[str, Any]) -> Dict[str, Any]:
        plan_code = str(subscription.get("plan") or "freemium")
        effective_plan = self._effective_plan_code(subscription)
        return {
            **subscription,
            "effective_plan": effective_plan,
            "effective_status": self._effective_status(subscription),
            "plan_details": self._get_plan(plan_code),
            "effective_plan_details": self._get_plan(effective_plan),
        }

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

    def _retrieve_price(self, price_id: str) -> Dict[str, Any]:
        return self._stripe_request("GET", f"/prices/{price_id}")

    @staticmethod
    def _checkout_success_url(success_url: str) -> str:
        if "{CHECKOUT_SESSION_ID}" in success_url:
            return success_url
        separator = "&" if "?" in success_url else "?"
        return f"{success_url}{separator}stripe_checkout_session_id={{CHECKOUT_SESSION_ID}}"

    def _stripe_price_currency(self, price_id: Optional[str]) -> Optional[str]:
        if not price_id:
            return None
        price = self._retrieve_price(str(price_id))
        currency = price.get("currency")
        return str(currency).lower() if currency else None

    def _expire_open_checkout_sessions(self, stripe_customer_id: str) -> None:
        query = urlencode({"customer": stripe_customer_id, "limit": 20})
        payload = self._stripe_request("GET", f"/checkout/sessions?{query}")
        for session in payload.get("data") or []:
            if (
                session.get("mode") == "subscription"
                and session.get("status") == "open"
                and session.get("id")
            ):
                self._stripe_request(
                    "POST",
                    f"/checkout/sessions/{session['id']}/expire",
                )

    def _current_stripe_subscription_price_id(
        self,
        subscription: Dict[str, Any],
    ) -> Optional[str]:
        price_id = subscription.get("stripe_price_id")
        if price_id:
            return str(price_id)
        stripe_subscription_id = subscription.get("stripe_subscription_id")
        if not stripe_subscription_id:
            return None
        remote_subscription = self._retrieve_subscription(str(stripe_subscription_id))
        item_rows = ((remote_subscription.get("items") or {}).get("data") or [])
        if not item_rows:
            return None
        price = item_rows[0].get("price") or {}
        return str(price.get("id")) if price.get("id") else None

    def _retrieve_checkout_session(self, checkout_session_id: str) -> Dict[str, Any]:
        query = urlencode({"expand[]": "subscription"})
        return self._stripe_request(
            "GET",
            f"/checkout/sessions/{checkout_session_id}?{query}",
        )

    def _list_customer_subscriptions(
        self,
        stripe_customer_id: str,
    ) -> List[Dict[str, Any]]:
        query = urlencode(
            {
                "customer": stripe_customer_id,
                "status": "all",
                "limit": 20,
                "expand[]": "data.items.data.price",
            }
        )
        payload = self._stripe_request("GET", f"/subscriptions?{query}")
        return list(payload.get("data") or [])

    @staticmethod
    def _stripe_subscription_sort_key(subscription: Dict[str, Any]) -> int:
        for key in ("current_period_end", "created"):
            try:
                return int(subscription.get(key) or 0)
            except (TypeError, ValueError):
                continue
        return 0

    def _latest_customer_subscription_for_org(
        self,
        stripe_customer_id: str,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        rows = [
            row
            for row in self._list_customer_subscriptions(stripe_customer_id)
            if str((row.get("metadata") or {}).get("organization_id") or "")
            == organization_id
        ]
        if not rows:
            return None

        active_rows = [
            row
            for row in rows
            if self._stripe_status_to_internal(str(row.get("status") or ""))
            in self.ACTIVE_STATUSES
        ]
        candidates = active_rows or rows
        return sorted(
            candidates,
            key=self._stripe_subscription_sort_key,
            reverse=True,
        )[0]

    def sync_checkout_session(
        self,
        organization_id: str,
        checkout_session_id: str,
    ) -> Optional[Dict[str, Any]]:
        session = self._retrieve_checkout_session(checkout_session_id)
        session_org_id = str(
            session.get("client_reference_id")
            or (session.get("metadata") or {}).get("organization_id")
            or ""
        )
        if session_org_id != organization_id:
            raise OrganizationSubscriptionPaymentError(
                "Session Stripe invalide pour cette organisation"
            )
        if session.get("mode") != "subscription":
            raise OrganizationSubscriptionPaymentError(
                "Session Stripe non liee a un abonnement"
            )
        if session.get("status") != "complete":
            raise OrganizationSubscriptionPaymentError(
                "Paiement Stripe non finalise"
            )

        stripe_subscription = session.get("subscription")
        if isinstance(stripe_subscription, dict):
            subscription_id = stripe_subscription.get("id")
        else:
            subscription_id = stripe_subscription
        if not subscription_id:
            raise OrganizationSubscriptionPaymentError(
                "Abonnement Stripe introuvable pour cette session"
            )
        return self.sync_stripe_subscription(
            self._retrieve_subscription(str(subscription_id))
        )

    def _refresh_stripe_subscription_if_needed(
        self,
        organization_id: str,
        subscription: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not (
            subscription.get("stripe_subscription_id")
            or subscription.get("stripe_customer_id")
        ):
            return subscription

        should_refresh = (
            subscription.get("source") == "stripe"
            and (
                subscription.get("status") not in self.ACTIVE_STATUSES
                or self._effective_status(subscription) not in self.ACTIVE_STATUSES
                or not subscription.get("current_period_end")
            )
        )
        if not should_refresh:
            return subscription

        synced: Optional[Dict[str, Any]] = None
        stripe_subscription_id = subscription.get("stripe_subscription_id")
        if stripe_subscription_id:
            synced = self.sync_stripe_subscription(
                self._retrieve_subscription(str(stripe_subscription_id))
            )

        if synced and synced.get("effective_status") in self.ACTIVE_STATUSES:
            return synced

        stripe_customer_id = subscription.get("stripe_customer_id")
        if stripe_customer_id:
            latest = self._latest_customer_subscription_for_org(
                str(stripe_customer_id),
                organization_id,
            )
            if latest is not None:
                synced = self.sync_stripe_subscription(latest)
                if synced:
                    return synced

        return subscription

    def _assert_checkout_currency_compatible(
        self,
        subscription: Dict[str, Any],
        target_price_id: str,
    ) -> None:
        stripe_customer_id = subscription.get("stripe_customer_id")
        if not stripe_customer_id:
            return

        self._expire_open_checkout_sessions(str(stripe_customer_id))
        if subscription.get("status") not in {"active", "trialing", "past_due"}:
            return

        current_price_id = self._current_stripe_subscription_price_id(subscription)
        current_currency = self._stripe_price_currency(current_price_id)
        target_currency = self._stripe_price_currency(target_price_id)
        if current_currency and target_currency and current_currency != target_currency:
            raise OrganizationSubscriptionPaymentError(
                "Stripe refuse de melanger plusieurs devises sur un meme customer. "
                f"L'abonnement actif est en {current_currency}, le nouveau price est en "
                f"{target_currency}. Configure les prices Standard/Premium mensuel/annuel "
                "dans la meme devise, ou annule l'abonnement actif avant de changer de devise."
            )

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
            if self._stripe_price_id_for_interval(plan, "monthly") == price_id:
                return {"plan": str(plan.get("code")), "billing_interval": "monthly"}
            if self._stripe_price_id_for_interval(plan, "yearly") == price_id:
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
        self._assert_checkout_currency_compatible(subscription, str(price_id))
        success_url = os.getenv("STRIPE_SUCCESS_URL", "").strip()
        cancel_url = os.getenv("STRIPE_CANCEL_URL", "").strip()
        if not success_url or not cancel_url:
            raise OrganizationSubscriptionPaymentError(
                "STRIPE_SUCCESS_URL et STRIPE_CANCEL_URL sont requis"
            )

        data: Dict[str, Any] = {
            "mode": "subscription",
            "success_url": self._checkout_success_url(success_url),
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
        return self._decorate_subscription(rows[0])

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
        *,
        checkout_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        if checkout_session_id:
            synced = self.sync_checkout_session(organization_id, checkout_session_id)
            if synced:
                return synced
        subscription = self._ensure_subscription(organization_id)
        subscription = self._refresh_stripe_subscription_if_needed(
            organization_id,
            subscription,
        )
        return self._decorate_subscription(subscription)

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
        return self._decorate_subscription(rows[0])

    def _count_active_articles(self, organization_id: str) -> int:
        res = (
            self.db.table("organization_articles")
            .select("id", count="exact")
            .eq("organization_id", organization_id)
            .eq("active", True)
            .eq("resource_scope", "sales_item")
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
        *,
        checkout_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        subscription = self.get_subscription(
            user_id,
            organization_id,
            checkout_session_id=checkout_session_id,
        )
        return self._build_entitlements(organization_id, subscription)

    def get_entitlements_for_org(self, organization_id: str) -> Dict[str, Any]:
        subscription = self._ensure_subscription(organization_id)
        subscription = self._refresh_stripe_subscription_if_needed(
            organization_id,
            subscription,
        )
        return self._build_entitlements(
            organization_id,
            self._decorate_subscription(subscription),
        )

    def _build_entitlements(
        self,
        organization_id: str,
        subscription: Dict[str, Any],
    ) -> Dict[str, Any]:
        subscription = self._decorate_subscription(subscription)
        plan = subscription.get("effective_plan_details") or {}
        plan_code = str(subscription.get("effective_plan") or plan.get("code") or "")
        features = dict(plan.get("features") or {})
        if plan_code == "premium":
            for key in self.KNOWN_FEATURE_KEYS:
                features[key] = True
            features["sales_dashboard"] = "advanced"
        features["advanced_reports"] = True
        if not self.ai_reports_enabled():
            features["ai_performance_agent"] = False
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
            "effective_plan": subscription.get("effective_plan"),
            "status": subscription.get("status"),
            "effective_status": subscription.get("effective_status"),
            "is_active": subscription.get("effective_status") in self.ACTIVE_STATUSES,
            "features": features,
            "limits": limits,
            "usage": usage,
            "exceeded_limits": exceeded_limits,
            "subscription": subscription,
        }

    def assert_feature_enabled(self, organization_id: str, feature: str) -> None:
        subscription = self._refresh_stripe_subscription_if_needed(
            organization_id,
            self._ensure_subscription(organization_id),
        )
        subscription = self._decorate_subscription(subscription)
        if subscription.get("effective_status") not in self.ACTIVE_STATUSES:
            raise OrganizationSubscriptionFeatureDenied(
                "Abonnement inactif pour cette organisation"
            )
        if feature == "ai_performance_agent" and not self.ai_reports_enabled():
            raise OrganizationSubscriptionFeatureDenied(
                "Rapport IA indisponible en V1"
            )
        plan = subscription.get("effective_plan_details") or {}
        if str(subscription.get("effective_plan")) == "premium":
            return
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
        subscription = self._refresh_stripe_subscription_if_needed(
            organization_id,
            self._ensure_subscription(organization_id),
        )
        subscription = self._decorate_subscription(subscription)
        if subscription.get("effective_status") not in self.ACTIVE_STATUSES:
            raise OrganizationSubscriptionLimitExceeded(
                "Abonnement inactif pour cette organisation"
            )
        plan = subscription.get("effective_plan_details") or {}
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
