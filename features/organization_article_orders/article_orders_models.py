"""
Modèles Pydantic : commandes d'articles et réception.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ArticleOrderStatus(str, Enum):
    open = "open"
    received = "received"
    cancelled = "cancelled"


class ArticleOrderLineCreate(BaseModel):
    article_id: UUID
    quantity_ordered: int = Field(..., ge=1)


class ArticleOrderCreate(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)
    lines: List[ArticleOrderLineCreate] = Field(..., min_length=1)


class ReceiveLineItem(BaseModel):
    line_id: UUID
    quantity_received: int = Field(..., ge=0)
    shortage_reason: Optional[str] = Field(
        None,
        max_length=2000,
        description="Obligatoire si quantité reçue < quantité commandée",
    )


class ArticleOrderReceiveRequest(BaseModel):
    """Une entrée par ligne de commande ; met à jour le stock (quantités reçues)."""

    lines: List[ReceiveLineItem] = Field(..., min_length=1)


class ArticleOrderLineResponse(BaseModel):
    id: UUID
    order_id: UUID
    article_id: UUID
    quantity_ordered: int
    quantity_received: Optional[int] = None
    shortage_reason: Optional[str] = None
    received_at: Optional[datetime] = None
    created_at: datetime


class ArticleOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    status: ArticleOrderStatus
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    lines: List[ArticleOrderLineResponse] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "organization_article_order_lines",
            "lines",
        ),
    )
