"""
Modèles Pydantic : posts promotionnels par article (slot 1–3).
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ArticlePostMediaKind(str, Enum):
    """Aligné sur `public.article_post_media_kind_enum`."""

    image = "image"
    video = "video"


class OrganizationArticlePostUpsert(BaseModel):
    """Création ou remplacement du contenu à l'emplacement `slot` (1–3)."""

    media_kind: ArticlePostMediaKind
    media_storage_path: str = Field(..., min_length=1, max_length=1024)
    caption: Optional[str] = Field(None, max_length=500)
    active: bool = True


class OrganizationArticlePostResponse(BaseModel):
    id: UUID
    organization_article_id: UUID
    slot: int = Field(..., ge=1, le=3)
    media_kind: ArticlePostMediaKind
    media_storage_path: str
    caption: Optional[str] = None
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
