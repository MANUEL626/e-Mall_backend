"""
Modèles API catalogue customer (articles actifs, vue publique).
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from features.organization_article_posts.organization_article_posts_models import (
    ArticlePostMediaKind,
    ArticlePostProcessingStatus,
)
from features.organization_articles.organization_articles_models import (
    ArticleCategory,
    ArticleStockStatus,
    CurrencyCode,
)


class CustomerCatalogProduct(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    name: str
    category: ArticleCategory
    unit_sale_price: Decimal = Field(..., ge=0)
    sale_currency: CurrencyCode
    stock_status: ArticleStockStatus
    primary_image_storage_path: str
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class CustomerCatalogPage(BaseModel):
    items: List[CustomerCatalogProduct]
    total: int
    limit: int
    offset: int


class CustomerTrendEventCounts(BaseModel):
    search: int = 0
    view: int = 0
    post_view: int = 0
    wishlist_add: int = 0
    cart_add: int = 0
    purchase: int = 0
    cart_abandon: int = 0


class CustomerTrendingProduct(CustomerCatalogProduct):
    trend_score: Decimal
    events: CustomerTrendEventCounts


class CustomerTrendingProductsPage(BaseModel):
    items: List[CustomerTrendingProduct]
    total: int
    limit: int
    period_key: str
    country: Optional[str] = None
    category: Optional[ArticleCategory] = None


class CustomerArticlePostPublic(BaseModel):
    """Post promo visible côté client (article actif, post actif)."""

    id: UUID
    slot: int = Field(..., ge=1)
    media_kind: ArticlePostMediaKind
    media_storage_path: str
    video_mobile_low_storage_path: Optional[str] = None
    thumbnail_storage_path: Optional[str] = None
    caption: Optional[str] = None
    processing_status: ArticlePostProcessingStatus = ArticlePostProcessingStatus.ready
    media_width: Optional[int] = None
    media_height: Optional[int] = None
    media_duration_seconds: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerArticlePostFeedItem(BaseModel):
    """
    Post promo + contexte produit (sans identifiant du post, seulement article + org).
    """

    organization_id: UUID
    organization_name: str
    organization_article_id: UUID
    name: str
    category: ArticleCategory
    unit_sale_price: Decimal = Field(..., ge=0)
    sale_currency: CurrencyCode
    stock_status: ArticleStockStatus
    primary_image_storage_path: str
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    slot: int = Field(..., ge=1)
    media_kind: ArticlePostMediaKind
    media_storage_path: str
    video_mobile_low_storage_path: Optional[str] = None
    thumbnail_storage_path: Optional[str] = None
    caption: Optional[str] = None
    processing_status: ArticlePostProcessingStatus = ArticlePostProcessingStatus.ready
    media_width: Optional[int] = None
    media_height: Optional[int] = None
    media_duration_seconds: Optional[float] = None

    model_config = {"from_attributes": True}


class CustomerArticlePostFeedPage(BaseModel):
    items: List[CustomerArticlePostFeedItem]
    total: int
    limit: int
    offset: int
