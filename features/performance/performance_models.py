"""
Modeles Pydantic pour les rapports de performance.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel

from features.organization_articles.organization_articles_models import (
    ArticleCategory,
    ArticleStockStatus,
    CurrencyCode,
)


class MetricTrend(str, Enum):
    up = "up"
    down = "down"
    stable = "stable"
    new_activity = "new_activity"
    no_data = "no_data"


class PerformancePeriod(str, Enum):
    d7 = "7d"
    d30 = "30d"
    d90 = "90d"
    year = "year"


class FinancialPeriod(str, Enum):
    month = "month"
    d7 = "7d"
    d30 = "30d"
    d90 = "90d"
    year = "year"


class PeriodInfo(BaseModel):
    month: str
    start: datetime
    end: datetime
    timezone: str


class DateRangeInfo(BaseModel):
    start: datetime
    end: datetime
    timezone: str


class MetricComparison(BaseModel):
    current: int
    previous: int
    variation_percent: Optional[Decimal] = None
    trend: MetricTrend


class MoneyComparison(BaseModel):
    currency: CurrencyCode
    current: Decimal
    previous: Decimal
    variation_percent: Optional[Decimal] = None
    trend: MetricTrend


class MoneyAmount(BaseModel):
    currency: CurrencyCode
    amount: Decimal


class SalesMonthlyMetrics(BaseModel):
    count: MetricComparison
    revenue: List[MoneyComparison]


class SupplierOrdersMonthlyMetrics(BaseModel):
    count: MetricComparison
    cost: List[MoneyComparison]


class CatalogMonthlyMetrics(BaseModel):
    active_products: int
    in_stock_products: int
    low_stock_products: int
    out_of_stock_products: int


class MonthlyPerformanceSummary(BaseModel):
    period: PeriodInfo
    previous_period: PeriodInfo
    sales: SalesMonthlyMetrics
    supplier_orders: SupplierOrdersMonthlyMetrics
    catalog: CatalogMonthlyMetrics


class WeeklySalesTotals(BaseModel):
    sales_count: int
    items_sold: int
    revenue: List[MoneyAmount]


class WeeklyProductSales(BaseModel):
    article_id: UUID
    name: Optional[str] = None
    category: Optional[ArticleCategory] = None
    sales_count: int
    quantity_sold: int
    revenue: List[MoneyAmount]


class WeeklySalesSummary(BaseModel):
    period: DateRangeInfo
    summary: WeeklySalesTotals
    by_product: List[WeeklyProductSales]


class TopProductSales(BaseModel):
    article_id: UUID
    name: Optional[str] = None
    category: Optional[ArticleCategory] = None
    sales_count: int
    quantity_sold: int
    revenue: List[MoneyAmount]


class TopProductsSummary(BaseModel):
    period: DateRangeInfo
    period_key: PerformancePeriod
    limit: int
    items: List[TopProductSales]


class TrendEventCounts(BaseModel):
    search: int = 0
    view: int = 0
    post_view: int = 0
    wishlist_add: int = 0
    cart_add: int = 0
    purchase: int = 0
    cart_abandon: int = 0


class TrendingProductMetric(BaseModel):
    article_id: UUID
    name: Optional[str] = None
    category: Optional[ArticleCategory] = None
    trend_score: Decimal
    events: TrendEventCounts
    quantity_sold: int
    revenue: List[MoneyAmount]
    stock_quantity: int
    reserved_quantity: int
    available_quantity: int
    stock_status: Optional[ArticleStockStatus] = None


class TrendingProductsSummary(BaseModel):
    period: DateRangeInfo
    period_key: PerformancePeriod
    limit: int
    items: List[TrendingProductMetric]


class YearlyPerformanceMonth(BaseModel):
    month: str
    sales_count: int
    revenue: List[MoneyAmount]
    supplier_orders_count: int
    supplier_cost: List[MoneyAmount]


class YearlyPerformanceTotals(BaseModel):
    sales_count: int
    revenue: List[MoneyAmount]
    supplier_orders_count: int
    supplier_cost: List[MoneyAmount]


class YearlyPerformanceSummary(BaseModel):
    year: int
    timezone: str
    months: List[YearlyPerformanceMonth]
    totals: YearlyPerformanceTotals


class InventoryProductCounts(BaseModel):
    total_products: int
    active_products: int
    inactive_products: int


class InventoryStockCounts(BaseModel):
    in_stock_products: int
    low_stock_products: int
    out_of_stock_products: int
    active_in_stock_products: int
    active_low_stock_products: int
    active_out_of_stock_products: int


class InventoryQuantityTotals(BaseModel):
    stock_quantity: int
    reserved_quantity: int
    available_quantity: int


class InventoryAlerts(BaseModel):
    active_products_out_of_stock: int
    active_products_low_stock: int
    active_products_with_reserved_stock: int


class InventorySummary(BaseModel):
    generated_at: datetime
    timezone: str
    products: InventoryProductCounts
    stock_status: InventoryStockCounts
    quantities: InventoryQuantityTotals
    alerts: InventoryAlerts


class FinancialSummary(BaseModel):
    period: DateRangeInfo
    period_key: FinancialPeriod
    sales_count: int
    supplier_orders_count: int
    revenue: List[MoneyAmount]
    supplier_cost: List[MoneyAmount]
    gross_margin_estimate: List[MoneyAmount]
    average_order_value: List[MoneyAmount]
    notes: List[str] = []


class SalesStatusCount(BaseModel):
    status: str
    count: int


class SalesFulfillmentCount(BaseModel):
    fulfillment_type: str
    count: int


class SalesStatusSummary(BaseModel):
    period: DateRangeInfo
    period_key: FinancialPeriod
    total_orders: int
    pipeline_orders: int
    completed_orders: int
    cancelled_orders: int
    cancellation_rate_percent: Decimal
    by_status: List[SalesStatusCount]
    by_fulfillment_type: List[SalesFulfillmentCount]
    completed_revenue: List[MoneyAmount]


class AIContextResponse(BaseModel):
    generated_at: datetime
    timezone: str
    organization_id: UUID
    period_key: FinancialPeriod
    instructions: List[str]
    anomalies: List[str]
    data: Dict[str, Any]


class PerformanceDashboardSummary(BaseModel):
    generated_at: datetime
    timezone: str
    organization_id: UUID
    period_key: FinancialPeriod
    monthly_summary: MonthlyPerformanceSummary
    weekly_sales: WeeklySalesSummary
    inventory_summary: InventorySummary
    financial_summary: FinancialSummary
    sales_status: SalesStatusSummary
    top_products: TopProductsSummary
    trending_products: TrendingProductsSummary
