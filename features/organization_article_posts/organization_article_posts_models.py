"""
Modeles Pydantic : posts promotionnels par article.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ArticlePostMediaKind(str, Enum):
    """Aligne sur `public.article_post_media_kind_enum`."""

    image = "image"
    video = "video"


class ArticlePostProcessingStatus(str, Enum):
    """Etat de preparation du media expose aux clients."""

    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class OrganizationArticlePostUpsert(BaseModel):
    """Creation ou remplacement du contenu a l'emplacement `slot`."""

    media_kind: ArticlePostMediaKind
    media_storage_path: str = Field(..., min_length=1, max_length=1024)
    original_media_storage_path: Optional[str] = Field(None, min_length=1, max_length=1024)
    caption: Optional[str] = Field(None, max_length=500)
    active: bool = True


class OrganizationArticlePostResponse(BaseModel):
    id: UUID
    organization_article_id: UUID
    slot: int = Field(..., ge=1)
    media_kind: ArticlePostMediaKind
    media_storage_path: str
    original_media_storage_path: Optional[str] = None
    video_mobile_low_storage_path: Optional[str] = None
    thumbnail_storage_path: Optional[str] = None
    caption: Optional[str] = None
    active: bool
    processing_status: ArticlePostProcessingStatus = ArticlePostProcessingStatus.ready
    processing_error: Optional[str] = None
    media_width: Optional[int] = None
    media_height: Optional[int] = None
    media_duration_seconds: Optional[float] = None
    media_size_bytes: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
