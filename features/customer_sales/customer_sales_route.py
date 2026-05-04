"""
Routes : ventes client (commandes, QR, livraison, walk-in).
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.customer_sales.customer_sales_models import (
    AssignDeliveryBody,
    ConfirmReceiptBody,
    CustomerSaleOrderCreate,
    PatchOrderStatusBody,
    QrPayloadOut,
    ReceiptTokenCreated,
    SaleOrderDetailOut,
    SaleOrderLineOut,
    SaleOrderOut,
    StatusEventOut,
    StatusGroup,
    WalkInSaleCreate,
)
from features.customer_sales.customer_sales_service import CustomerSalesService

security = HTTPBearer()
_auth = AuthService()
_service = CustomerSalesService()


def _current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def _detail_from_row(row: Dict[str, Any]) -> SaleOrderDetailOut:
    r = dict(row)
    raw_lines = r.pop("organization_customer_sale_order_lines", None) or []
    order = SaleOrderOut.model_validate(r)
    lines = [SaleOrderLineOut.model_validate(x) for x in raw_lines]
    return SaleOrderDetailOut(order=order, lines=lines)


def _exc(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


customer_router = APIRouter(prefix="/api/v1/customer-sales", tags=["Customer sales"])

org_router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/customer-sales",
    tags=["Customer sales"],
)


def _bucket_param(
    bucket: Optional[StatusGroup] = Query(
        None,
        description="Filtre historique : in_progress | in_delivery | cancelled | completed",
    ),
    status_group: Optional[StatusGroup] = Query(
        None,
        description="Alias de bucket",
    ),
) -> Optional[StatusGroup]:
    return bucket or status_group


@customer_router.post("", response_model=SaleOrderDetailOut, status_code=status.HTTP_201_CREATED)
def create_customer_sale_order(
    body: CustomerSaleOrderCreate,
    user_id: str = Depends(_current_user_id),
):
    """Création pickup / livraison avec réservation de stock."""
    try:
        row = _service.create_customer_sale_order(user_id, body)
        return _detail_from_row(row)
    except (LookupError, ValueError, PermissionError, RuntimeError) as exc:
        raise _exc(exc) from exc


@customer_router.get("", response_model=List[SaleOrderDetailOut])
def list_my_customer_sale_orders(
    user_id: str = Depends(_current_user_id),
    group: Optional[StatusGroup] = Depends(_bucket_param),
):
    try:
        rows = _service.list_customer_orders(user_id, group)
        return [_detail_from_row(r) for r in rows]
    except LookupError as exc:
        raise _exc(exc) from exc


@customer_router.get("/{order_id}", response_model=SaleOrderDetailOut)
def get_my_customer_sale_order(
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_customer_order(user_id, str(order_id))
        return _detail_from_row(row)
    except (LookupError, PermissionError) as exc:
        raise _exc(exc) from exc


@customer_router.get("/{order_id}/history", response_model=List[StatusEventOut])
def get_my_customer_sale_history(
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        rows = _service.list_order_history(user_id, str(order_id))
        return [StatusEventOut.model_validate(r) for r in rows]
    except (LookupError, PermissionError) as exc:
        raise _exc(exc) from exc


@customer_router.post("/{order_id}/confirm-receipt", response_model=SaleOrderDetailOut)
def confirm_customer_sale_receipt(
    order_id: UUID,
    body: ConfirmReceiptBody,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.confirm_receipt(user_id, str(order_id), body)
        return _detail_from_row(row)
    except (LookupError, PermissionError, ValueError, RuntimeError) as exc:
        raise _exc(exc) from exc


@org_router.get("", response_model=List[SaleOrderDetailOut])
def list_org_customer_sales(
    organization_id: UUID,
    user_id: str = Depends(_current_user_id),
    group: Optional[StatusGroup] = Depends(_bucket_param),
):
    try:
        rows = _service.list_org_orders(user_id, str(organization_id), group)
        return [_detail_from_row(r) for r in rows]
    except PermissionError as exc:
        raise _exc(exc) from exc


@org_router.post(
    "/walk-in",
    response_model=SaleOrderDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_walk_in_sale(
    organization_id: UUID,
    body: WalkInSaleCreate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.walk_in_sale(user_id, str(organization_id), body)
        return _detail_from_row(row)
    except (PermissionError, LookupError, ValueError, RuntimeError) as exc:
        raise _exc(exc) from exc


@org_router.patch("/{order_id}/status", response_model=SaleOrderDetailOut)
def patch_org_sale_status(
    organization_id: UUID,
    order_id: UUID,
    body: PatchOrderStatusBody,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.patch_order_status(
            user_id, str(organization_id), str(order_id), body
        )
        return _detail_from_row(row)
    except (PermissionError, LookupError, ValueError, RuntimeError) as exc:
        raise _exc(exc) from exc


@org_router.get("/{order_id}/history", response_model=List[StatusEventOut])
def get_org_sale_history(
    organization_id: UUID,
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        rows = _service.list_org_order_history(
            user_id, str(organization_id), str(order_id)
        )
        return [StatusEventOut.model_validate(r) for r in rows]
    except (PermissionError, LookupError) as exc:
        raise _exc(exc) from exc


@org_router.post("/{order_id}/receipt-token", response_model=ReceiptTokenCreated)
def post_receipt_token(
    organization_id: UUID,
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        d = _service.upsert_receipt_token(user_id, str(organization_id), str(order_id))
        return ReceiptTokenCreated(
            order_id=UUID(d["order_id"]),
            secret=d["secret"],
            qr_payload=d["qr_payload"],
            expires_at=d.get("expires_at"),
        )
    except (PermissionError, LookupError, ValueError, RuntimeError) as exc:
        raise _exc(exc) from exc


@org_router.get("/{order_id}/pickup-qr", response_model=QrPayloadOut)
def get_pickup_qr(
    organization_id: UUID,
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    """Régénère un jeton et retourne le payload QR (retrait magasin)."""
    try:
        d = _service.get_pickup_qr_payload(user_id, str(organization_id), str(order_id))
        return QrPayloadOut(
            order_id=UUID(d["order_id"]),
            organization_id=UUID(d["organization_id"]),
            secret=d["secret"],
            qr_payload=d["qr_payload"],
        )
    except (PermissionError, LookupError, ValueError, RuntimeError) as exc:
        raise _exc(exc) from exc


@org_router.post("/{order_id}/assign-delivery", response_model=SaleOrderDetailOut)
def assign_delivery_member(
    organization_id: UUID,
    order_id: UUID,
    body: AssignDeliveryBody,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.assign_delivery(
            user_id,
            str(organization_id),
            str(order_id),
            str(body.member_id),
        )
        return _detail_from_row(row)
    except (PermissionError, LookupError, ValueError, RuntimeError) as exc:
        raise _exc(exc) from exc


@org_router.get("/{order_id}/delivery-qr", response_model=QrPayloadOut)
def get_delivery_qr(
    organization_id: UUID,
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    """Livreur assigné uniquement : régénère le payload QR."""
    try:
        d = _service.get_delivery_qr_payload(
            user_id, str(organization_id), str(order_id)
        )
        return QrPayloadOut(
            order_id=UUID(d["order_id"]),
            organization_id=UUID(d["organization_id"]),
            secret=d["secret"],
            qr_payload=d["qr_payload"],
        )
    except (PermissionError, LookupError, ValueError, RuntimeError) as exc:
        raise _exc(exc) from exc


delivery_router = APIRouter(
    prefix="/api/v1/customer-sales/delivery-assignments",
    tags=["Customer sales"],
)


@delivery_router.get("", response_model=List[SaleOrderDetailOut])
def list_my_delivery_assignments(user_id: str = Depends(_current_user_id)):
    rows = _service.list_delivery_assignments(user_id)
    return [_detail_from_row(r) for r in rows]


@org_router.get("/{order_id}", response_model=SaleOrderDetailOut)
def get_org_customer_sale_order(
    organization_id: UUID,
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_org_order(user_id, str(organization_id), str(order_id))
        return _detail_from_row(row)
    except (PermissionError, LookupError) as exc:
        raise _exc(exc) from exc
