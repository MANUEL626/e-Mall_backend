"""
Modèles API : liste de souhaits et paniers par organisation.
"""

from datetime import datetime
from decimal import Decimal
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field

from features.customers.customer_catalog_models import CustomerCatalogProduct


class AddWishlistItemBody(BaseModel):
    organization_article_id: UUID


class AddCartItemBody(BaseModel):
    organization_article_id: UUID
    quantity: int = Field(default=1, ge=1, le=99_999)


class PatchCartLineBody(BaseModel):
    quantity: int = Field(..., ge=1, le=99_999)


class CustomerWishlistResponse(BaseModel):
    items: List[CustomerCatalogProduct]


class CustomerCartLineItem(BaseModel):
    line_id: UUID
    quantity: int
    product: CustomerCatalogProduct


class CustomerCartGroup(BaseModel):
    cart_id: UUID
    organization_id: UUID
    organization_name: str
    updated_at: datetime
    items: List[CustomerCartLineItem]


class CustomerCartsResponse(BaseModel):
    carts: List[CustomerCartGroup]


class CustomerCartItemAddResponse(BaseModel):
    cart_id: UUID
    line_id: UUID
