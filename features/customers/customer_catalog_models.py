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
)
from features.organization_articles.organization_articles_models import (
    ArticleCategory,
    ArticleStockStatus,
)


class CustomerCatalogProduct(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    name: str
    category: ArticleCategory
    unit_sale_price: Decimal = Field(..., ge=0)
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


class CustomerArticlePostPublic(BaseModel):
    """Post promo visible côté client (article actif, post actif)."""

    id: UUID
    slot: int = Field(..., ge=1, le=3)
    media_kind: ArticlePostMediaKind
    media_storage_path: str
    caption: Optional[str] = None
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
    stock_status: ArticleStockStatus
    primary_image_storage_path: str
    additional_image_storage_paths: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    slot: int = Field(..., ge=1, le=3)
    media_kind: ArticlePostMediaKind
    media_storage_path: str
    caption: Optional[str] = None

    model_config = {"from_attributes": True}


class CustomerArticlePostFeedPage(BaseModel):
    items: List[CustomerArticlePostFeedItem]
    total: int
    limit: int
    offset: int
