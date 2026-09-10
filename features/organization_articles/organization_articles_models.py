"""
Modèles Pydantic : articles d'organisation (prix, gros, stock, images Storage).
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ArticleCategory(str, Enum):
    """Aligné sur `public.article_category_enum`."""

    electronics = "electronics"
    appliances = "appliances"
    clothing = "clothing"
    food = "food"
    beauty = "beauty"
    sports = "sports"
    home = "home"
    other = "other"


class ArticleStockStatus(str, Enum):
    """Aligné sur `public.article_stock_status_enum` (colonne générée)."""

    in_stock = "in_stock"
    low_stock = "low_stock"
    out_of_stock = "out_of_stock"


class OrganizationStockScope(str, Enum):
    sales_item = "sales_item"
    repair_supply = "repair_supply"
    repair_tool = "repair_tool"
    rental_asset = "rental_asset"


class CurrencyCode(str, Enum):
    """Codes devises supportes par l'application (ISO 4217 en minuscules)."""

    xof = "xof"
    eur = "eur"
    usd = "usd"
    gbp = "gbp"
    cny = "cny"
    ngn = "ngn"
    ghs = "ghs"


class WholesalePriceTier(BaseModel):
    """
    Palier de prix de vente en gros.
    `max_quantity` null = pas de plafond (tout lot >= min_quantity).
    """

    min_quantity: int = Field(..., ge=1)
    max_quantity: Optional[int] = Field(None, ge=1)
    unit_price: Decimal = Field(..., ge=0)

    @model_validator(mode="after")
    def max_ge_min(self) -> "WholesalePriceTier":
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("max_quantity doit être >= min_quantity")
        return self


def validate_wholesale_tiers_contiguous(tiers: List[WholesalePriceTier]) -> None:
    """
    Paliers triés par min_quantity : pas de doublon de min, pas de chevauchement ni de trou.
    Chaque palier (sauf le premier) doit commencer à max_quantity + 1 du précédent.
    Un seul palier peut avoir max_quantity null, et il doit être le dernier.
    """
    if len(tiers) <= 1:
        return
    ordered = sorted(tiers, key=lambda t: t.min_quantity)
    for i in range(len(ordered) - 1):
        if ordered[i].min_quantity == ordered[i + 1].min_quantity:
            raise ValueError("Deux paliers ne peuvent pas avoir la même quantité minimum")
    for i in range(1, len(ordered)):
        prev, cur = ordered[i - 1], ordered[i]
        if prev.max_quantity is None:
            raise ValueError(
                "Un palier sans quantité maximum doit être le dernier du tableau"
            )
        expected_min = prev.max_quantity + 1
        if cur.min_quantity != expected_min:
            raise ValueError(
                "Les plages de lot doivent se suivre sans trou ni chevauchement : "
                f"après la plage {prev.min_quantity}–{prev.max_quantity}, "
                f"le palier suivant doit commencer à {expected_min} "
                f"(reçu {cur.min_quantity})"
            )


class OrganizationArticleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    category: ArticleCategory
    unit_sale_price: Decimal = Field(..., ge=0)
    sale_currency: Optional[CurrencyCode] = None
    wholesale_prices: Optional[List[WholesalePriceTier]] = None
    stock_quantity: int = Field(0, ge=0)
    alert_quantity: int = Field(0, ge=0)
    shop_id: Optional[UUID] = None
    description: Optional[str] = Field(None, max_length=10000)
    primary_image_storage_path: str = Field(..., min_length=1, max_length=1024)
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    active: bool = True

    @model_validator(mode="after")
    def wholesale_tiers_contiguous(self) -> "OrganizationArticleCreate":
        if self.wholesale_prices:
            validate_wholesale_tiers_contiguous(self.wholesale_prices)
        return self


class OrganizationArticleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    category: Optional[ArticleCategory] = None
    unit_sale_price: Optional[Decimal] = Field(None, ge=0)
    sale_currency: Optional[CurrencyCode] = None
    wholesale_prices: Optional[List[WholesalePriceTier]] = None
    stock_quantity: Optional[int] = Field(None, ge=0)
    alert_quantity: Optional[int] = Field(None, ge=0)
    shop_id: Optional[UUID] = None
    description: Optional[str] = Field(None, max_length=10000)
    primary_image_storage_path: Optional[str] = Field(None, min_length=1, max_length=1024)
    additional_image_storage_paths: Optional[List[str]] = None
    active: Optional[bool] = None

    @model_validator(mode="after")
    def wholesale_tiers_contiguous(self) -> "OrganizationArticleUpdate":
        if self.wholesale_prices is not None and len(self.wholesale_prices) > 1:
            validate_wholesale_tiers_contiguous(self.wholesale_prices)
        return self


class OrganizationArticleResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    category: ArticleCategory
    unit_sale_price: Decimal
    sale_currency: CurrencyCode
    wholesale_prices: Optional[Any] = None
    stock_quantity: int
    alert_quantity: int
    stock_status: ArticleStockStatus
    shop_id: Optional[UUID] = None
    reserved_quantity: int = 0
    stock_scope: str = "sales_item"
    description: Optional[str] = None
    primary_image_storage_path: Optional[str] = None
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("additional_image_storage_paths", mode="before")
    @classmethod
    def coerce_additional(cls, v: Any) -> Any:
        if v is None:
            return []
        return v

    model_config = {"from_attributes": True}


class ShopStockResourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    stock_scope: OrganizationStockScope
    stock_quantity: int = Field(0, ge=0)
    alert_quantity: int = Field(0, ge=0)
    unit_purchase_price: Decimal = Field(Decimal("0"), ge=0)
    unit_rental_price: Optional[Decimal] = Field(None, ge=0)
    rental_currency: Optional[CurrencyCode] = None
    rental_bulk_prices: Optional[List[WholesalePriceTier]] = None
    description: Optional[str] = Field(None, max_length=10000)
    category: ArticleCategory = ArticleCategory.other
    primary_image_storage_path: Optional[str] = Field(None, min_length=1, max_length=1024)
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    active: bool = True

    @model_validator(mode="after")
    def resource_scope_only(self) -> "ShopStockResourceCreate":
        if self.stock_scope == OrganizationStockScope.sales_item:
            raise ValueError("Utiliser les endpoints articles pour le stock sales_item")
        if self.stock_scope != OrganizationStockScope.rental_asset:
            if self.unit_rental_price is not None or self.rental_bulk_prices is not None:
                raise ValueError("Les prix de location sont reserves aux rental_asset")
        if self.rental_bulk_prices:
            validate_wholesale_tiers_contiguous(self.rental_bulk_prices)
        return self


class ShopStockResourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    stock_quantity: Optional[int] = Field(None, ge=0)
    alert_quantity: Optional[int] = Field(None, ge=0)
    unit_purchase_price: Optional[Decimal] = Field(None, ge=0)
    unit_rental_price: Optional[Decimal] = Field(None, ge=0)
    rental_currency: Optional[CurrencyCode] = None
    rental_bulk_prices: Optional[List[WholesalePriceTier]] = None
    description: Optional[str] = Field(None, max_length=10000)
    category: Optional[ArticleCategory] = None
    primary_image_storage_path: Optional[str] = Field(None, min_length=1, max_length=1024)
    additional_image_storage_paths: Optional[List[str]] = None
    active: Optional[bool] = None

    @model_validator(mode="after")
    def wholesale_tiers_contiguous(self) -> "ShopStockResourceUpdate":
        if self.rental_bulk_prices is not None and len(self.rental_bulk_prices) > 1:
            validate_wholesale_tiers_contiguous(self.rental_bulk_prices)
        return self


class ShopStockResourceResponse(BaseModel):
    id: UUID
    organization_id: UUID
    shop_id: UUID
    name: str
    category: ArticleCategory
    stock_scope: OrganizationStockScope
    stock_quantity: int
    reserved_quantity: int = 0
    alert_quantity: int
    stock_status: ArticleStockStatus
    unit_purchase_price: Decimal = Decimal("0")
    unit_rental_price: Optional[Decimal] = None
    rental_currency: Optional[CurrencyCode] = None
    rental_bulk_prices: Optional[Any] = None
    description: Optional[str] = None
    primary_image_storage_path: Optional[str] = None
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("additional_image_storage_paths", mode="before")
    @classmethod
    def coerce_additional(cls, v: Any) -> Any:
        if v is None:
            return []
        return v

    model_config = {"from_attributes": True}


class OrganizationArticleStockPatch(BaseModel):
    stock_quantity: Optional[int] = Field(None, ge=0)
    alert_quantity: Optional[int] = Field(None, ge=0)
    active: Optional[bool] = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "OrganizationArticleStockPatch":
        if (
            self.stock_quantity is None
            and self.alert_quantity is None
            and self.active is None
        ):
            raise ValueError(
                "Au moins un parmi stock_quantity, alert_quantity, active est requis"
            )
        return self
