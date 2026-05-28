"""Modeles API pour le tracking analytics customer."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from features.organization_articles.organization_articles_models import ArticleCategory


class CustomerTrendEventType(str, Enum):
    search = "search"
    view = "view"
    post_view = "post_view"
    wishlist_add = "wishlist_add"
    cart_add = "cart_add"
    cart_abandon = "cart_abandon"


class CustomerArticleTrendEventCreate(BaseModel):
    organization_id: UUID
    article_id: Optional[UUID] = None
    event_type: CustomerTrendEventType
    search_query: Optional[str] = Field(None, max_length=255)
    category: Optional[ArticleCategory] = None
    country: Optional[str] = Field(None, min_length=2, max_length=2)
    locale: Optional[str] = Field(None, max_length=8)
    source: Optional[str] = Field(None, max_length=80)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("search_query", "locale", "source", mode="before")
    @classmethod
    def blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = str(value).strip().upper()
        if not value:
            return None
        if len(value) != 2 or not value.isalpha():
            raise ValueError("country doit etre un code ISO alpha-2")
        return value

    @model_validator(mode="after")
    def validate_event_context(self) -> "CustomerArticleTrendEventCreate":
        if self.event_type == CustomerTrendEventType.search:
            if self.article_id is None and not self.search_query:
                raise ValueError("search_query est requis pour une recherche globale")
            return self
        if self.article_id is None:
            raise ValueError("article_id est requis pour ce type d'evenement")
        return self


class CustomerArticleTrendEventResponse(BaseModel):
    id: UUID
    organization_id: UUID
    article_id: Optional[UUID] = None
    event_type: str
    deduplicated: bool = False
    occurred_at: datetime
