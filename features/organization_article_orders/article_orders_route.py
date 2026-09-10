"""
Routes : commandes d'articles (création, réception, annulation).
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.organization_article_orders.article_orders_models import (
    ArticleOrderCreate,
    ArticleOrderReceiveRequest,
    ArticleOrderResponse,
    ArticleOrderStatus,
)
from features.organization_article_orders.article_orders_service import ArticleOrdersService

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/article-orders",
    tags=["Organization article orders"],
)

shop_router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/shops/{shop_id}/article-orders",
    tags=["Organization shop article orders"],
)

security = HTTPBearer()
_service = ArticleOrdersService()
_auth = AuthService()


def _current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.get("", response_model=List[ArticleOrderResponse])
def list_article_orders(
    organization_id: UUID,
    order_status: Optional[ArticleOrderStatus] = Query(
        None,
        alias="status",
        description="Filtrer par statut (open, received, cancelled).",
    ),
    shop_id: Optional[UUID] = Query(
        None,
        description="Filtrer les commandes fournisseur d'une boutique de vente.",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        rows = _service.list_article_orders(
            uid,
            str(organization_id),
            status=order_status.value if order_status else None,
            shop_id=str(shop_id) if shop_id is not None else None,
            limit=limit,
            offset=offset,
        )
        return [ArticleOrderResponse.model_validate(r) for r in rows]
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _assert_order_shop(row: dict, shop_id: UUID) -> None:
    if str(row.get("shop_id")) != str(shop_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commande introuvable dans cette boutique",
        )


@router.get("/{order_id}", response_model=ArticleOrderResponse)
def get_article_order(
    organization_id: UUID,
    order_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        row = _service.get_article_order(uid, str(organization_id), str(order_id))
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "",
    response_model=ArticleOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_article_order(
    organization_id: UUID,
    body: ArticleOrderCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        row = _service.create_article_order(uid, str(organization_id), body)
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/receive", response_model=ArticleOrderResponse)
def receive_article_order(
    organization_id: UUID,
    order_id: UUID,
    body: ArticleOrderReceiveRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Réceptionne la commande en une fois : une entrée par ligne.
    Le stock est augmenté de chaque `quantity_received` (trigger SQL).
    Si quantité reçue < commandée, `shortage_reason` est obligatoire.
    """
    uid = _current_user_id(credentials)
    try:
        row = _service.receive_article_order(
            uid, str(organization_id), str(order_id), body
        )
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/{order_id}/cancel", response_model=ArticleOrderResponse)
def cancel_article_order(
    organization_id: UUID,
    order_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Annule une commande encore ouverte et sans réception."""
    uid = _current_user_id(credentials)
    try:
        row = _service.cancel_article_order(uid, str(organization_id), str(order_id))
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@shop_router.get("", response_model=List[ArticleOrderResponse])
def list_shop_article_orders(
    organization_id: UUID,
    shop_id: UUID,
    order_status: Optional[ArticleOrderStatus] = Query(
        None,
        alias="status",
        description="Filtrer par statut (open, received, cancelled).",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        rows = _service.list_article_orders(
            uid,
            str(organization_id),
            status=order_status.value if order_status else None,
            shop_id=str(shop_id),
            limit=limit,
            offset=offset,
        )
        return [ArticleOrderResponse.model_validate(row) for row in rows]
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@shop_router.post(
    "",
    response_model=ArticleOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shop_article_order(
    organization_id: UUID,
    shop_id: UUID,
    body: ArticleOrderCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        row = _service.create_article_order(
            uid,
            str(organization_id),
            body.model_copy(update={"shop_id": shop_id}),
        )
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@shop_router.get("/{order_id}", response_model=ArticleOrderResponse)
def get_shop_article_order(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        row = _service.get_article_order(uid, str(organization_id), str(order_id))
        _assert_order_shop(row, shop_id)
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@shop_router.post("/{order_id}/receive", response_model=ArticleOrderResponse)
def receive_shop_article_order(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    body: ArticleOrderReceiveRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        existing = _service.get_article_order(uid, str(organization_id), str(order_id))
        _assert_order_shop(existing, shop_id)
        row = _service.receive_article_order(
            uid,
            str(organization_id),
            str(order_id),
            body,
        )
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@shop_router.post("/{order_id}/cancel", response_model=ArticleOrderResponse)
def cancel_shop_article_order(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uid = _current_user_id(credentials)
    try:
        existing = _service.get_article_order(uid, str(organization_id), str(order_id))
        _assert_order_shop(existing, shop_id)
        row = _service.cancel_article_order(uid, str(organization_id), str(order_id))
        return ArticleOrderResponse.model_validate(row)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
