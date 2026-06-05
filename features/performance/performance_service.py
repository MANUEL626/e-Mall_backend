"""
Service de calcul des rapports Performance.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Tuple
from zoneinfo import ZoneInfo

from supabase import Client

from config.supabase_client import supabase_admin
from features.organization_articles.organization_articles_models import CurrencyCode
from features.organization_subscriptions.organization_subscriptions_service import (
    OrganizationSubscriptionFeatureDenied,
    OrganizationSubscriptionService,
)
from features.performance.performance_models import FinancialPeriod, PerformancePeriod


class PerformanceService:
    DEFAULT_TIMEZONE = "Africa/Lome"
    PAGE_SIZE = 1000
    ID_CHUNK_SIZE = 200
    SALE_STATUSES = ("pending", "in_progress", "in_delivery", "cancelled", "completed")
    SALE_PIPELINE_STATUSES = ("pending", "in_progress", "in_delivery")
    SALE_FULFILLMENT_TYPES = ("pickup", "delivery", "walk_in_offline")
    TREND_EVENT_TYPES = (
        "search",
        "view",
        "post_view",
        "wishlist_add",
        "cart_add",
        "purchase",
        "cart_abandon",
    )

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

    def assert_feature_enabled(self, organization_id: str, feature: str) -> None:
        try:
            self.subscriptions.assert_feature_enabled(organization_id, feature)
        except OrganizationSubscriptionFeatureDenied as exc:
            raise PermissionError(str(exc)) from exc

    def get_monthly_summary(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        return self._monthly_summary_payload(organization_id)

    def _monthly_summary_payload(self, organization_id: str) -> Dict[str, Any]:
        tz_name = self.DEFAULT_TIMEZONE
        current_start, current_end, previous_start, previous_end = self._month_windows(
            tz_name
        )

        current_sales = self._sales_metrics(
            organization_id,
            current_start,
            current_end,
        )
        previous_sales = self._sales_metrics(
            organization_id,
            previous_start,
            previous_end,
        )
        current_supplier = self._supplier_order_metrics(
            organization_id,
            current_start,
            current_end,
        )
        previous_supplier = self._supplier_order_metrics(
            organization_id,
            previous_start,
            previous_end,
        )

        return {
            "period": self._period_payload(current_start, current_end, tz_name),
            "previous_period": self._period_payload(
                previous_start,
                previous_end,
                tz_name,
            ),
            "sales": {
                "count": self._compare_int(
                    current_sales["count"],
                    previous_sales["count"],
                ),
                "revenue": self._compare_money_maps(
                    current_sales["amounts"],
                    previous_sales["amounts"],
                ),
            },
            "supplier_orders": {
                "count": self._compare_int(
                    current_supplier["count"],
                    previous_supplier["count"],
                ),
                "cost": self._compare_money_maps(
                    current_supplier["amounts"],
                    previous_supplier["amounts"],
                ),
            },
            "catalog": self._catalog_metrics(organization_id),
        }

    def get_weekly_sales(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        return self._weekly_sales_payload(organization_id)

    def _weekly_sales_payload(self, organization_id: str) -> Dict[str, Any]:
        tz_name = self.DEFAULT_TIMEZONE
        week_start, week_end = self._week_window(tz_name)
        metrics = self._weekly_sales_metrics(organization_id, week_start, week_end)
        return {
            "period": self._date_range_payload(week_start, week_end, tz_name),
            "summary": {
                "sales_count": metrics["sales_count"],
                "items_sold": metrics["items_sold"],
                "revenue": self._money_amounts(metrics["revenue"]),
            },
            "by_product": metrics["by_product"],
        }

    def get_top_products(
        self,
        user_id: str,
        organization_id: str,
        period: PerformancePeriod = PerformancePeriod.d30,
        limit: int = 20,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        return self._top_products_payload(organization_id, period, limit)

    def _top_products_payload(
        self,
        organization_id: str,
        period: PerformancePeriod,
        limit: int,
    ) -> Dict[str, Any]:
        tz_name = self.DEFAULT_TIMEZONE
        start, end = self._period_window(period, tz_name)
        metrics = self._product_sales_metrics(organization_id, start, end)
        return {
            "period": self._date_range_payload(start, end, tz_name),
            "period_key": period.value,
            "limit": limit,
            "items": metrics["by_product"][:limit],
        }

    def get_trending_products(
        self,
        user_id: str,
        organization_id: str,
        period: PerformancePeriod = PerformancePeriod.d30,
        limit: int = 20,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        self.assert_feature_enabled(organization_id, "advanced_reports")
        return self._trending_products_payload(organization_id, period, limit)

    def _trending_products_payload(
        self,
        organization_id: str,
        period: PerformancePeriod,
        limit: int,
    ) -> Dict[str, Any]:
        tz_name = self.DEFAULT_TIMEZONE
        start, end = self._period_window(period, tz_name)
        items = self._trending_product_metrics(organization_id, start, end)
        return {
            "period": self._date_range_payload(start, end, tz_name),
            "period_key": period.value,
            "limit": limit,
            "items": items[:limit],
        }

    def get_yearly_summary(
        self,
        user_id: str,
        organization_id: str,
        year: int | None = None,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        self.assert_feature_enabled(organization_id, "advanced_reports")
        tz_name = self.DEFAULT_TIMEZONE
        selected_year = year or datetime.now(ZoneInfo(tz_name)).year
        months = []
        total_sales_count = 0
        total_revenue: Dict[str, Decimal] = {}
        total_supplier_orders_count = 0
        total_supplier_cost: Dict[str, Decimal] = {}

        for month in range(1, 13):
            start, end = self._year_month_window(selected_year, month, tz_name)
            sales = self._sales_metrics(organization_id, start, end)
            supplier = self._supplier_order_metrics(organization_id, start, end)
            total_sales_count += int(sales["count"])
            total_supplier_orders_count += int(supplier["count"])
            self._merge_money_map(total_revenue, sales["amounts"])
            self._merge_money_map(total_supplier_cost, supplier["amounts"])
            months.append(
                {
                    "month": start.strftime("%Y-%m"),
                    "sales_count": sales["count"],
                    "revenue": self._money_amounts(sales["amounts"]),
                    "supplier_orders_count": supplier["count"],
                    "supplier_cost": self._money_amounts(supplier["amounts"]),
                }
            )

        return {
            "year": selected_year,
            "timezone": tz_name,
            "months": months,
            "totals": {
                "sales_count": total_sales_count,
                "revenue": self._money_amounts(total_revenue),
                "supplier_orders_count": total_supplier_orders_count,
                "supplier_cost": self._money_amounts(total_supplier_cost),
            },
        }

    def get_inventory_summary(
        self,
        user_id: str,
        organization_id: str,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        return self._inventory_summary_payload(organization_id)

    def _inventory_summary_payload(self, organization_id: str) -> Dict[str, Any]:
        tz_name = self.DEFAULT_TIMEZONE
        return self._inventory_summary(organization_id, tz_name)

    def get_financial_summary(
        self,
        user_id: str,
        organization_id: str,
        period: FinancialPeriod = FinancialPeriod.month,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        self.assert_feature_enabled(organization_id, "advanced_reports")
        return self._financial_summary_payload(organization_id, period)

    def _financial_summary_payload(
        self,
        organization_id: str,
        period: FinancialPeriod,
    ) -> Dict[str, Any]:
        tz_name = self.DEFAULT_TIMEZONE
        start, end = self._financial_period_window(period, tz_name)
        sales = self._sales_metrics(organization_id, start, end)
        supplier = self._supplier_order_metrics(organization_id, start, end)
        margin, notes = self._gross_margin_estimate(
            sales["amounts"],
            supplier["amounts"],
        )
        return {
            "period": self._date_range_payload(start, end, tz_name),
            "period_key": period.value,
            "sales_count": sales["count"],
            "supplier_orders_count": supplier["count"],
            "revenue": self._money_amounts(sales["amounts"]),
            "supplier_cost": self._money_amounts(supplier["amounts"]),
            "gross_margin_estimate": self._money_amounts(margin),
            "average_order_value": self._average_order_value(
                sales["amounts"],
                sales["count_by_currency"],
            ),
            "notes": notes,
        }

    def get_sales_status(
        self,
        user_id: str,
        organization_id: str,
        period: FinancialPeriod = FinancialPeriod.month,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        self.assert_feature_enabled(organization_id, "advanced_reports")
        return self._sales_status_payload(organization_id, period)

    def _sales_status_payload(
        self,
        organization_id: str,
        period: FinancialPeriod,
    ) -> Dict[str, Any]:
        tz_name = self.DEFAULT_TIMEZONE
        start, end = self._financial_period_window(period, tz_name)
        orders = self._select_rows_between(
            table="organization_customer_sale_orders",
            columns="id,status,fulfillment_type",
            organization_id=organization_id,
            start=start,
            end=end,
        )
        status_counts = {status: 0 for status in self.SALE_STATUSES}
        fulfillment_counts = {
            fulfillment_type: 0 for fulfillment_type in self.SALE_FULFILLMENT_TYPES
        }
        for order in orders:
            status = str(order.get("status") or "")
            fulfillment_type = str(order.get("fulfillment_type") or "")
            if status in status_counts:
                status_counts[status] += 1
            if fulfillment_type in fulfillment_counts:
                fulfillment_counts[fulfillment_type] += 1
        total_orders = len(orders)
        cancelled_orders = status_counts["cancelled"]
        completed_orders = status_counts["completed"]
        pipeline_orders = sum(
            status_counts[status] for status in self.SALE_PIPELINE_STATUSES
        )
        cancellation_rate = Decimal("0")
        if total_orders > 0:
            cancellation_rate = (
                Decimal(cancelled_orders) / Decimal(total_orders) * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        completed_sales = self._sales_metrics(organization_id, start, end)
        return {
            "period": self._date_range_payload(start, end, tz_name),
            "period_key": period.value,
            "total_orders": total_orders,
            "pipeline_orders": pipeline_orders,
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
            "cancellation_rate_percent": cancellation_rate,
            "by_status": [
                {"status": status, "count": status_counts[status]}
                for status in self.SALE_STATUSES
            ],
            "by_fulfillment_type": [
                {
                    "fulfillment_type": fulfillment_type,
                    "count": fulfillment_counts[fulfillment_type],
                }
                for fulfillment_type in self.SALE_FULFILLMENT_TYPES
            ],
            "completed_revenue": self._money_amounts(completed_sales["amounts"]),
        }

    def get_ai_context(
        self,
        user_id: str,
        organization_id: str,
        period: FinancialPeriod = FinancialPeriod.month,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        self.assert_feature_enabled(organization_id, "ai_performance_agent")
        tz_name = self.DEFAULT_TIMEZONE
        trend_period = self._trend_period_for_financial_period(period)
        monthly = self._monthly_summary_payload(organization_id)
        weekly = self._weekly_sales_payload(organization_id)
        inventory = self._inventory_summary_payload(organization_id)
        financial = self._financial_summary_payload(organization_id, period)
        sales_status = self._sales_status_payload(organization_id, period)
        top_products = self._top_products_payload(organization_id, trend_period, 10)
        trending_products = self._trending_products_payload(
            organization_id,
            trend_period,
            10,
        )
        anomalies = self._ai_anomalies(
            monthly=monthly,
            inventory=inventory,
            financial=financial,
            sales_status=sales_status,
            trending_products=trending_products,
        )
        return {
            "generated_at": datetime.now(ZoneInfo(tz_name)).isoformat(),
            "timezone": tz_name,
            "organization_id": organization_id,
            "period_key": period.value,
            "instructions": [
                "Utiliser uniquement les chiffres fournis dans data.",
                "Ne pas inventer de montants, de devises, de ventes ou de tendances absentes.",
                "Signaler clairement les limites lorsque les données sont vides ou insuffisantes.",
                "Les montants sont déjà séparés par devise; ne pas convertir automatiquement.",
                "Formuler des recommandations opérationnelles courtes et vérifiables.",
            ],
            "anomalies": anomalies,
            "data": {
                "monthly_summary": monthly,
                "weekly_sales": weekly,
                "inventory_summary": inventory,
                "financial_summary": financial,
                "sales_status": sales_status,
                "top_products": top_products,
                "trending_products": trending_products,
            },
        }

    def get_dashboard_summary(
        self,
        user_id: str,
        organization_id: str,
        period: FinancialPeriod = FinancialPeriod.month,
        limit: int = 10,
    ) -> Dict[str, Any]:
        self.assert_org_member(user_id, organization_id)
        self.assert_feature_enabled(organization_id, "advanced_reports")
        tz_name = self.DEFAULT_TIMEZONE
        trend_period = self._trend_period_for_financial_period(period)
        return {
            "generated_at": datetime.now(ZoneInfo(tz_name)).isoformat(),
            "timezone": tz_name,
            "organization_id": organization_id,
            "period_key": period.value,
            "monthly_summary": self._monthly_summary_payload(organization_id),
            "weekly_sales": self._weekly_sales_payload(organization_id),
            "inventory_summary": self._inventory_summary_payload(organization_id),
            "financial_summary": self._financial_summary_payload(
                organization_id,
                period,
            ),
            "sales_status": self._sales_status_payload(organization_id, period),
            "top_products": self._top_products_payload(
                organization_id,
                trend_period,
                limit,
            ),
            "trending_products": self._trending_products_payload(
                organization_id,
                trend_period,
                limit,
            ),
        }

    def _week_window(self, timezone_name: str) -> Tuple[datetime, datetime]:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        week_end = week_start + timedelta(days=7)
        return week_start, week_end

    def _period_window(
        self,
        period: PerformancePeriod,
        timezone_name: str,
    ) -> Tuple[datetime, datetime]:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        end = now
        if period == PerformancePeriod.d7:
            return end - timedelta(days=7), end
        if period == PerformancePeriod.d30:
            return end - timedelta(days=30), end
        if period == PerformancePeriod.d90:
            return end - timedelta(days=90), end
        year_start = datetime(now.year, 1, 1, tzinfo=tz)
        return year_start, end

    def _financial_period_window(
        self,
        period: FinancialPeriod,
        timezone_name: str,
    ) -> Tuple[datetime, datetime]:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        end = now
        if period == FinancialPeriod.month:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return month_start, end
        if period == FinancialPeriod.d7:
            return end - timedelta(days=7), end
        if period == FinancialPeriod.d30:
            return end - timedelta(days=30), end
        if period == FinancialPeriod.d90:
            return end - timedelta(days=90), end
        year_start = datetime(now.year, 1, 1, tzinfo=tz)
        return year_start, end

    @staticmethod
    def _trend_period_for_financial_period(period: FinancialPeriod) -> PerformancePeriod:
        if period == FinancialPeriod.d7:
            return PerformancePeriod.d7
        if period == FinancialPeriod.d90:
            return PerformancePeriod.d90
        if period == FinancialPeriod.year:
            return PerformancePeriod.year
        return PerformancePeriod.d30

    def _year_month_window(
        self,
        year: int,
        month: int,
        timezone_name: str,
    ) -> Tuple[datetime, datetime]:
        tz = ZoneInfo(timezone_name)
        start = datetime(year, month, 1, tzinfo=tz)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=tz)
        else:
            end = datetime(year, month + 1, 1, tzinfo=tz)
        return start, end

    def _month_windows(
        self,
        timezone_name: str,
    ) -> Tuple[datetime, datetime, datetime, datetime]:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if current_start.month == 12:
            current_end = current_start.replace(
                year=current_start.year + 1,
                month=1,
            )
        else:
            current_end = current_start.replace(month=current_start.month + 1)

        if current_start.month == 1:
            previous_start = current_start.replace(
                year=current_start.year - 1,
                month=12,
            )
        else:
            previous_start = current_start.replace(month=current_start.month - 1)
        previous_end = current_start
        return current_start, current_end, previous_start, previous_end

    def _period_payload(
        self,
        start: datetime,
        end: datetime,
        timezone_name: str,
    ) -> Dict[str, Any]:
        return {
            "month": start.strftime("%Y-%m"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone_name,
        }

    def _date_range_payload(
        self,
        start: datetime,
        end: datetime,
        timezone_name: str,
    ) -> Dict[str, Any]:
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": timezone_name,
        }

    def _weekly_sales_metrics(
        self,
        organization_id: str,
        start: datetime,
        end: datetime,
    ) -> Dict[str, Any]:
        product_metrics = self._product_sales_metrics(organization_id, start, end)
        return {
            "sales_count": product_metrics["sales_count"],
            "items_sold": product_metrics["items_sold"],
            "revenue": product_metrics["revenue"],
            "by_product": product_metrics["by_product"],
        }

    def _product_sales_metrics(
        self,
        organization_id: str,
        start: datetime,
        end: datetime,
    ) -> Dict[str, Any]:
        rows = self._select_rows_between(
            table="organization_completed_sale_lines",
            columns=(
                "order_id,article_id,article_name,article_category,quantity,"
                "unit_price_snapshot,currency_snapshot,line_total"
            ),
            organization_id=organization_id,
            start=start,
            end=end,
        )
        order_ids = {str(row["order_id"]) for row in rows if row.get("order_id")}
        revenue: Dict[str, Decimal] = {}
        items_sold = 0
        product_metrics: Dict[str, Dict[str, Any]] = {}

        for line in rows:
            article_id = str(line.get("article_id"))
            currency = self._normalize_currency(line.get("currency_snapshot"))
            qty = int(line.get("quantity") or 0)
            line_total = Decimal(str(line.get("line_total") or "0"))
            items_sold += qty
            revenue[currency] = revenue.get(currency, Decimal("0")) + line_total

            product = product_metrics.setdefault(
                article_id,
                {
                    "article_id": article_id,
                    "name": line.get("article_name"),
                    "category": line.get("article_category"),
                    "sales_count": 0,
                    "quantity_sold": 0,
                    "revenue": {},
                },
            )
            product["sales_count"] += 1
            product["quantity_sold"] += qty
            product["revenue"][currency] = (
                product["revenue"].get(currency, Decimal("0")) + line_total
            )

        by_product = sorted(
            (
                {
                    "article_id": data["article_id"],
                    "name": data.get("name"),
                    "category": data.get("category"),
                    "sales_count": data["sales_count"],
                    "quantity_sold": data["quantity_sold"],
                    "revenue": self._money_amounts(data["revenue"]),
                }
                for data in product_metrics.values()
            ),
            key=lambda item: (item["quantity_sold"], item["sales_count"]),
            reverse=True,
        )
        return {
            "sales_count": len(order_ids),
            "items_sold": items_sold,
            "revenue": self._quantize_money_map(revenue),
            "by_product": by_product,
        }

    def _trending_product_metrics(
        self,
        organization_id: str,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        query = (
            self.db.table("customer_article_trend_events")
            .select("article_id,event_type,weight")
            .eq("organization_id", organization_id)
            .gte("occurred_at", start.isoformat())
            .lt("occurred_at", end.isoformat())
        )
        product_metrics: Dict[str, Dict[str, Any]] = {}
        for event in self._execute_paged(query):
            article_id = event.get("article_id")
            if not article_id:
                continue
            article_key = str(article_id)
            event_type = str(event.get("event_type") or "")
            if event_type not in self.TREND_EVENT_TYPES:
                continue
            metric = product_metrics.setdefault(
                article_key,
                {
                    "article_id": article_key,
                    "trend_score": Decimal("0"),
                    "events": {key: 0 for key in self.TREND_EVENT_TYPES},
                    "quantity_sold": 0,
                    "revenue": {},
                    "stock_quantity": 0,
                    "reserved_quantity": 0,
                    "available_quantity": 0,
                    "stock_status": None,
                },
            )
            metric["events"][event_type] += 1
            metric["trend_score"] += Decimal(str(event.get("weight") or "0"))

        if not product_metrics:
            return []

        sales = self._product_sales_metrics(organization_id, start, end)
        sales_by_article = {
            str(item["article_id"]): item for item in sales.get("by_product", [])
        }
        for article_id, metric in product_metrics.items():
            sale = sales_by_article.get(article_id)
            if not sale:
                continue
            metric["quantity_sold"] = int(sale.get("quantity_sold") or 0)
            metric["revenue"] = {
                str(money["currency"]): Decimal(str(money["amount"]))
                for money in sale.get("revenue", [])
            }

        self._attach_trending_article_context(product_metrics, organization_id)
        return sorted(
            (
                {
                    "article_id": data["article_id"],
                    "name": data.get("name"),
                    "category": data.get("category"),
                    "trend_score": data["trend_score"].quantize(
                        Decimal("0.01"),
                        rounding=ROUND_HALF_UP,
                    ),
                    "events": data["events"],
                    "quantity_sold": data["quantity_sold"],
                    "revenue": self._money_amounts(data["revenue"]),
                    "stock_quantity": data["stock_quantity"],
                    "reserved_quantity": data["reserved_quantity"],
                    "available_quantity": data["available_quantity"],
                    "stock_status": data.get("stock_status"),
                }
                for data in product_metrics.values()
            ),
            key=lambda item: (
                item["trend_score"],
                item["quantity_sold"],
                item["events"]["purchase"],
            ),
            reverse=True,
        )

    def _attach_article_context(
        self,
        product_metrics: Dict[str, Dict[str, Any]],
        organization_id: str,
    ) -> None:
        article_ids = list(product_metrics.keys())
        for chunk in self._chunks(article_ids, self.ID_CHUNK_SIZE):
            query = (
                self.db.table("organization_articles")
                .select("id,name,category")
                .eq("organization_id", organization_id)
                .in_("id", chunk)
            )
            for article in self._execute_paged(query):
                article_id = str(article.get("id"))
                if article_id not in product_metrics:
                    continue
                product_metrics[article_id]["name"] = article.get("name")
                product_metrics[article_id]["category"] = article.get("category")

    def _attach_trending_article_context(
        self,
        product_metrics: Dict[str, Dict[str, Any]],
        organization_id: str,
    ) -> None:
        article_ids = list(product_metrics.keys())
        for chunk in self._chunks(article_ids, self.ID_CHUNK_SIZE):
            query = (
                self.db.table("organization_articles")
                .select("id,name,category,stock_quantity,reserved_quantity,stock_status")
                .eq("organization_id", organization_id)
                .in_("id", chunk)
            )
            for article in self._execute_paged(query):
                article_id = str(article.get("id"))
                if article_id not in product_metrics:
                    continue
                stock_quantity = int(article.get("stock_quantity") or 0)
                reserved_quantity = int(article.get("reserved_quantity") or 0)
                product_metrics[article_id]["name"] = article.get("name")
                product_metrics[article_id]["category"] = article.get("category")
                product_metrics[article_id]["stock_quantity"] = stock_quantity
                product_metrics[article_id]["reserved_quantity"] = reserved_quantity
                product_metrics[article_id]["available_quantity"] = max(
                    stock_quantity - reserved_quantity,
                    0,
                )
                product_metrics[article_id]["stock_status"] = article.get("stock_status")

    def _sales_metrics(
        self,
        organization_id: str,
        start: datetime,
        end: datetime,
    ) -> Dict[str, Any]:
        rows = self._select_rows_between(
            table="organization_completed_sale_lines",
            columns="order_id,order_currency,currency_snapshot,line_total",
            organization_id=organization_id,
            start=start,
            end=end,
        )
        currency_by_order: Dict[str, str] = {}
        for row in rows:
            order_id = str(row.get("order_id"))
            if order_id and order_id not in currency_by_order:
                currency_by_order[order_id] = self._normalize_currency(
                    row.get("order_currency")
                )
        count_by_currency: Dict[str, int] = {}
        for currency in currency_by_order.values():
            count_by_currency[currency] = count_by_currency.get(currency, 0) + 1
        amounts: Dict[str, Decimal] = {}
        for line in rows:
            currency = self._normalize_currency(line.get("currency_snapshot"))
            amounts[currency] = amounts.get(currency, Decimal("0")) + Decimal(
                str(line.get("line_total") or "0")
            )
        return {
            "count": len(currency_by_order),
            "amounts": self._quantize_money_map(amounts),
            "count_by_currency": count_by_currency,
        }

    def _supplier_order_metrics(
        self,
        organization_id: str,
        start: datetime,
        end: datetime,
    ) -> Dict[str, Any]:
        rows = self._select_rows_between(
            table="organization_supplier_order_line_totals",
            columns="order_id,currency,total_price",
            organization_id=organization_id,
            start=start,
            end=end,
        )
        order_ids = {str(row["order_id"]) for row in rows if row.get("order_id")}
        amounts: Dict[str, Decimal] = {}
        for line in rows:
            currency = self._normalize_currency(line.get("currency"), "eur")
            total = Decimal(str(line.get("total_price") or "0"))
            amounts[currency] = amounts.get(currency, Decimal("0")) + total
        return {"count": len(order_ids), "amounts": self._quantize_money_map(amounts)}

    def _select_rows_between(
        self,
        table: str,
        columns: str,
        organization_id: str,
        start: datetime,
        end: datetime,
        extra_filters: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        query = (
            self.db.table(table)
            .select(columns)
            .eq("organization_id", organization_id)
            .gte("created_at", start.isoformat())
            .lt("created_at", end.isoformat())
        )
        for key, value in (extra_filters or {}).items():
            query = query.eq(key, value)
        return self._execute_paged(query)

    def _catalog_metrics(self, organization_id: str) -> Dict[str, int]:
        query = (
            self.db.table("organization_articles")
            .select("active,stock_status")
            .eq("organization_id", organization_id)
        )
        rows = self._execute_paged(query)
        active_rows = [row for row in rows if row.get("active") is True]
        return {
            "active_products": len(active_rows),
            "in_stock_products": self._count_stock_status(active_rows, "in_stock"),
            "low_stock_products": self._count_stock_status(active_rows, "low_stock"),
            "out_of_stock_products": self._count_stock_status(active_rows, "out_of_stock"),
        }

    def _inventory_summary(
        self,
        organization_id: str,
        timezone_name: str,
    ) -> Dict[str, Any]:
        query = (
            self.db.table("organization_articles")
            .select("active,stock_status,stock_quantity,reserved_quantity")
            .eq("organization_id", organization_id)
        )
        rows = self._execute_paged(query)
        active_rows = [row for row in rows if row.get("active") is True]
        inactive_rows = [row for row in rows if row.get("active") is not True]
        stock_quantity = sum(int(row.get("stock_quantity") or 0) for row in rows)
        reserved_quantity = sum(int(row.get("reserved_quantity") or 0) for row in rows)
        available_quantity = max(stock_quantity - reserved_quantity, 0)
        active_reserved = sum(
            1
            for row in active_rows
            if int(row.get("reserved_quantity") or 0) > 0
        )
        return {
            "generated_at": datetime.now(ZoneInfo(timezone_name)).isoformat(),
            "timezone": timezone_name,
            "products": {
                "total_products": len(rows),
                "active_products": len(active_rows),
                "inactive_products": len(inactive_rows),
            },
            "stock_status": {
                "in_stock_products": self._count_stock_status(rows, "in_stock"),
                "low_stock_products": self._count_stock_status(rows, "low_stock"),
                "out_of_stock_products": self._count_stock_status(rows, "out_of_stock"),
                "active_in_stock_products": self._count_stock_status(
                    active_rows,
                    "in_stock",
                ),
                "active_low_stock_products": self._count_stock_status(
                    active_rows,
                    "low_stock",
                ),
                "active_out_of_stock_products": self._count_stock_status(
                    active_rows,
                    "out_of_stock",
                ),
            },
            "quantities": {
                "stock_quantity": stock_quantity,
                "reserved_quantity": reserved_quantity,
                "available_quantity": available_quantity,
            },
            "alerts": {
                "active_products_out_of_stock": self._count_stock_status(
                    active_rows,
                    "out_of_stock",
                ),
                "active_products_low_stock": self._count_stock_status(
                    active_rows,
                    "low_stock",
                ),
                "active_products_with_reserved_stock": active_reserved,
            },
        }

    @staticmethod
    def _count_stock_status(rows: Iterable[Dict[str, Any]], status: str) -> int:
        return sum(1 for row in rows if row.get("stock_status") == status)

    def _compare_int(self, current: int, previous: int) -> Dict[str, Any]:
        variation, trend = self._variation(Decimal(current), Decimal(previous))
        return {
            "current": current,
            "previous": previous,
            "variation_percent": variation,
            "trend": trend,
        }

    def _compare_money_maps(
        self,
        current: Dict[str, Decimal],
        previous: Dict[str, Decimal],
    ) -> List[Dict[str, Any]]:
        currencies = sorted(set(current.keys()) | set(previous.keys()))
        comparisons = []
        for currency in currencies:
            current_amount = current.get(currency, Decimal("0"))
            previous_amount = previous.get(currency, Decimal("0"))
            variation, trend = self._variation(current_amount, previous_amount)
            comparisons.append(
                {
                    "currency": currency,
                    "current": current_amount,
                    "previous": previous_amount,
                    "variation_percent": variation,
                    "trend": trend,
                }
            )
        return comparisons

    def _money_amounts(self, amounts: Dict[str, Decimal]) -> List[Dict[str, Any]]:
        return [
            {
                "currency": currency,
                "amount": amount,
            }
            for currency, amount in sorted(self._quantize_money_map(amounts).items())
        ]

    def _average_order_value(
        self,
        revenue_by_currency: Dict[str, Decimal],
        count_by_currency: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        averages: Dict[str, Decimal] = {}
        for currency, amount in revenue_by_currency.items():
            count = count_by_currency.get(currency, 0)
            if count <= 0:
                continue
            averages[currency] = (amount / Decimal(count)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        return self._money_amounts(averages)

    def _gross_margin_estimate(
        self,
        revenue_by_currency: Dict[str, Decimal],
        supplier_cost_by_currency: Dict[str, Decimal],
    ) -> Tuple[Dict[str, Decimal], List[str]]:
        notes: List[str] = []
        margin: Dict[str, Decimal] = {}
        shared_currencies = set(revenue_by_currency) & set(supplier_cost_by_currency)
        for currency in shared_currencies:
            margin[currency] = revenue_by_currency[currency] - supplier_cost_by_currency[currency]
        if not shared_currencies and (revenue_by_currency or supplier_cost_by_currency):
            notes.append(
                "Marge non calculée : les revenus et coûts fournisseur ne partagent aucune devise."
            )
        revenue_only = sorted(set(revenue_by_currency) - set(supplier_cost_by_currency))
        cost_only = sorted(set(supplier_cost_by_currency) - set(revenue_by_currency))
        if revenue_only:
            notes.append(
                "Aucun coût fournisseur dans les devises de vente : "
                + ", ".join(revenue_only)
            )
        if cost_only:
            notes.append(
                "Aucun revenu de vente dans les devises fournisseur : "
                + ", ".join(cost_only)
            )
        return self._quantize_money_map(margin), notes

    def _ai_anomalies(
        self,
        *,
        monthly: Dict[str, Any],
        inventory: Dict[str, Any],
        financial: Dict[str, Any],
        sales_status: Dict[str, Any],
        trending_products: Dict[str, Any],
    ) -> List[str]:
        anomalies: List[str] = []
        sales_count = (
            monthly.get("sales", {})
            .get("count", {})
            .get("trend")
        )
        if sales_count == "down":
            anomalies.append("Les ventes du mois courant sont en baisse face au mois précédent.")
        if sales_status.get("cancellation_rate_percent", Decimal("0")) > Decimal("10"):
            anomalies.append("Le taux d'annulation dépasse 10% sur la période.")
        alerts = inventory.get("alerts", {})
        if int(alerts.get("active_products_out_of_stock") or 0) > 0:
            anomalies.append("Des produits actifs sont en rupture de stock.")
        if int(alerts.get("active_products_low_stock") or 0) > 0:
            anomalies.append("Des produits actifs sont sous le seuil d'alerte stock.")
        if financial.get("notes"):
            anomalies.extend(str(note) for note in financial.get("notes", []))
        for item in trending_products.get("items", [])[:5]:
            if item.get("stock_status") in ("low_stock", "out_of_stock"):
                name = item.get("name") or item.get("article_id")
                anomalies.append(
                    f"Produit tendance avec stock à surveiller : {name} ({item.get('stock_status')})."
                )
        return anomalies

    @staticmethod
    def _merge_money_map(
        target: Dict[str, Decimal],
        source: Dict[str, Decimal],
    ) -> None:
        for currency, amount in source.items():
            target[currency] = target.get(currency, Decimal("0")) + amount

    def _execute_paged(self, query: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            res = query.range(offset, offset + self.PAGE_SIZE - 1).execute()
            batch = list(res.data or [])
            rows.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                break
            offset += self.PAGE_SIZE
        return rows

    @staticmethod
    def _chunks(values: List[str], size: int) -> Iterable[List[str]]:
        for index in range(0, len(values), size):
            yield values[index : index + size]

    @staticmethod
    def _variation(current: Decimal, previous: Decimal) -> Tuple[Decimal | None, str]:
        if previous == 0 and current == 0:
            return Decimal("0"), "stable"
        if previous == 0 and current > 0:
            return None, "new_activity"
        percent = ((current - previous) / previous * Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if percent > 0:
            return percent, "up"
        if percent < 0:
            return percent, "down"
        return percent, "stable"

    @staticmethod
    def _normalize_currency(value: Any, fallback: str = "xof") -> str:
        raw = str(value or fallback).strip().lower()
        allowed = {currency.value for currency in CurrencyCode}
        return raw if raw in allowed else fallback

    @staticmethod
    def _quantize_money_map(amounts: Dict[str, Decimal]) -> Dict[str, Decimal]:
        return {
            currency: amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for currency, amount in amounts.items()
        }
