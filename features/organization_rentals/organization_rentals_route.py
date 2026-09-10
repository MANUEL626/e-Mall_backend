from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.organization_rentals.organization_rentals_models import (
    RentalActionRequest,
    RentalAvailabilityResponse,
    RentalInvoiceResponse,
    RentalOrderCreate,
    RentalOrderResponse,
    RentalProformaCreate,
    RentalProformaPaymentCreate,
    RentalProformaPaymentResult,
    RentalProformaResponse,
    RentalProformaStatus,
    RentalProformaUpdate,
    RentalReservationCreate,
    RentalReservationResponse,
    RentalReservationStatus,
    RentalReservationUpdate,
    RentalStatusUpdate,
)
from features.organization_rentals.organization_rentals_service import (
    OrganizationRentalsService,
)
from features.organization_rentals.organization_rental_proformas_service import (
    OrganizationRentalProformasService,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/shops/{shop_id}/rentals",
    tags=["Organization shop rentals"],
)

security = HTTPBearer()
_auth = AuthService()
_service = OrganizationRentalsService()
_proforma_service = OrganizationRentalProformasService()


def _current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _exc(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("", response_model=List[RentalReservationResponse])
def list_shop_rentals(
    organization_id: UUID,
    shop_id: UUID,
    rental_status: Optional[RentalReservationStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(_current_user_id),
):
    try:
        rows = _service.list_reservations(
            user_id,
            str(organization_id),
            str(shop_id),
            status=rental_status,
            limit=limit,
            offset=offset,
        )
        return [RentalReservationResponse.model_validate(row) for row in rows]
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/availability", response_model=RentalAvailabilityResponse)
def get_shop_rental_availability(
    organization_id: UUID,
    shop_id: UUID,
    rental_asset_id: UUID = Query(...),
    starts_at: datetime = Query(...),
    ends_at: datetime = Query(...),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_availability(
            user_id,
            str(organization_id),
            str(shop_id),
            str(rental_asset_id),
            starts_at,
            ends_at,
        )
        return RentalAvailabilityResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post(
    "",
    response_model=RentalReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shop_rental(
    organization_id: UUID,
    shop_id: UUID,
    body: RentalReservationCreate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.create_reservation(user_id, str(organization_id), str(shop_id), body)
        return RentalReservationResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/proformas", response_model=List[RentalProformaResponse])
def list_shop_rental_proformas(
    organization_id: UUID,
    shop_id: UUID,
    proforma_status: Optional[RentalProformaStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(_current_user_id),
):
    try:
        rows = _proforma_service.list_proformas(
            user_id,
            str(organization_id),
            str(shop_id),
            proforma_status=proforma_status,
            limit=limit,
            offset=offset,
        )
        return [RentalProformaResponse.model_validate(row) for row in rows]
    except Exception as exc:
        raise _exc(exc) from exc


@router.post(
    "/proformas",
    response_model=RentalProformaResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shop_rental_proforma(
    organization_id: UUID,
    shop_id: UUID,
    body: RentalProformaCreate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _proforma_service.create_proforma(
            user_id,
            str(organization_id),
            str(shop_id),
            body,
        )
        return RentalProformaResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/proformas/{proforma_id}", response_model=RentalProformaResponse)
def get_shop_rental_proforma(
    organization_id: UUID,
    shop_id: UUID,
    proforma_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _proforma_service.get_proforma(
            user_id,
            str(organization_id),
            str(shop_id),
            str(proforma_id),
        )
        return RentalProformaResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.patch("/proformas/{proforma_id}", response_model=RentalProformaResponse)
def patch_shop_rental_proforma(
    organization_id: UUID,
    shop_id: UUID,
    proforma_id: UUID,
    body: RentalProformaUpdate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _proforma_service.update_proforma(
            user_id,
            str(organization_id),
            str(shop_id),
            str(proforma_id),
            body,
        )
        return RentalProformaResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get(
    "/proformas/{proforma_id}/document",
    response_model=RentalProformaResponse,
)
def get_shop_rental_proforma_document(
    organization_id: UUID,
    shop_id: UUID,
    proforma_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _proforma_service.get_proforma(
            user_id,
            str(organization_id),
            str(shop_id),
            str(proforma_id),
        )
        return RentalProformaResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/proformas/{proforma_id}/issue", response_model=RentalProformaResponse)
def issue_shop_rental_proforma(
    organization_id: UUID,
    shop_id: UUID,
    proforma_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _proforma_service.issue_proforma(
            user_id,
            str(organization_id),
            str(shop_id),
            str(proforma_id),
        )
        return RentalProformaResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/proformas/{proforma_id}/cancel", response_model=RentalProformaResponse)
def cancel_shop_rental_proforma(
    organization_id: UUID,
    shop_id: UUID,
    proforma_id: UUID,
    body: RentalActionRequest = Body(default_factory=RentalActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _proforma_service.cancel_proforma(
            user_id,
            str(organization_id),
            str(shop_id),
            str(proforma_id),
            note=body.note,
        )
        return RentalProformaResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post(
    "/proformas/{proforma_id}/payments",
    response_model=RentalProformaPaymentResult,
    status_code=status.HTTP_201_CREATED,
)
def record_shop_rental_proforma_payment(
    organization_id: UUID,
    shop_id: UUID,
    proforma_id: UUID,
    body: RentalProformaPaymentCreate,
    user_id: str = Depends(_current_user_id),
):
    try:
        result = _proforma_service.record_payment(
            user_id,
            str(organization_id),
            str(shop_id),
            str(proforma_id),
            body,
        )
        return RentalProformaPaymentResult.model_validate(result)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post(
    "/proformas/{proforma_id}/convert",
    response_model=RentalProformaPaymentResult,
)
def convert_shop_rental_proforma(
    organization_id: UUID,
    shop_id: UUID,
    proforma_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        result = _proforma_service.convert_proforma(
            user_id,
            str(organization_id),
            str(shop_id),
            str(proforma_id),
        )
        return RentalProformaPaymentResult.model_validate(result)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/orders", response_model=List[RentalOrderResponse])
def list_shop_rental_orders(
    organization_id: UUID,
    shop_id: UUID,
    rental_status: Optional[RentalReservationStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(_current_user_id),
):
    try:
        rows = _service.list_orders(
            user_id,
            str(organization_id),
            str(shop_id),
            status=rental_status,
            limit=limit,
            offset=offset,
        )
        return [RentalOrderResponse.model_validate(row) for row in rows]
    except Exception as exc:
        raise _exc(exc) from exc


@router.post(
    "/orders",
    response_model=RentalOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shop_rental_order(
    organization_id: UUID,
    shop_id: UUID,
    body: RentalOrderCreate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.create_order(user_id, str(organization_id), str(shop_id), body)
        return RentalOrderResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/orders/{order_id}", response_model=RentalOrderResponse)
def get_shop_rental_order(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_order(
            user_id,
            str(organization_id),
            str(shop_id),
            str(order_id),
        )
        return RentalOrderResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/orders/{order_id}/invoice", response_model=RentalInvoiceResponse)
def get_shop_rental_order_invoice(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_order_invoice(
            user_id,
            str(organization_id),
            str(shop_id),
            str(order_id),
        )
        return RentalInvoiceResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.patch("/orders/{order_id}/status", response_model=RentalOrderResponse)
def patch_shop_rental_order_status(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    body: RentalStatusUpdate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.update_order_status(
            user_id,
            str(organization_id),
            str(shop_id),
            str(order_id),
            body.status,
            note=body.note,
        )
        return RentalOrderResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/orders/{order_id}/start", response_model=RentalOrderResponse)
def start_shop_rental_order(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    body: RentalActionRequest = Body(default_factory=RentalActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.start_order(
            user_id,
            str(organization_id),
            str(shop_id),
            str(order_id),
            body,
        )
        return RentalOrderResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/orders/{order_id}/return", response_model=RentalOrderResponse)
def return_shop_rental_order(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    body: RentalActionRequest = Body(default_factory=RentalActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.return_order(
            user_id,
            str(organization_id),
            str(shop_id),
            str(order_id),
            body,
        )
        return RentalOrderResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/orders/{order_id}/cancel", response_model=RentalOrderResponse)
def cancel_shop_rental_order(
    organization_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    body: RentalActionRequest = Body(default_factory=RentalActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.cancel_order(
            user_id,
            str(organization_id),
            str(shop_id),
            str(order_id),
            body,
        )
        return RentalOrderResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/{reservation_id}", response_model=RentalReservationResponse)
def get_shop_rental(
    organization_id: UUID,
    shop_id: UUID,
    reservation_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_reservation(
            user_id,
            str(organization_id),
            str(shop_id),
            str(reservation_id),
        )
        return RentalReservationResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.patch("/{reservation_id}", response_model=RentalReservationResponse)
def patch_shop_rental(
    organization_id: UUID,
    shop_id: UUID,
    reservation_id: UUID,
    body: RentalReservationUpdate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.update_reservation(
            user_id,
            str(organization_id),
            str(shop_id),
            str(reservation_id),
            body,
        )
        return RentalReservationResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.patch("/{reservation_id}/status", response_model=RentalReservationResponse)
def patch_shop_rental_status(
    organization_id: UUID,
    shop_id: UUID,
    reservation_id: UUID,
    body: RentalStatusUpdate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.update_status(
            user_id,
            str(organization_id),
            str(shop_id),
            str(reservation_id),
            body.status,
            note=body.note,
        )
        return RentalReservationResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{reservation_id}/start", response_model=RentalReservationResponse)
def start_shop_rental(
    organization_id: UUID,
    shop_id: UUID,
    reservation_id: UUID,
    body: RentalActionRequest = Body(default_factory=RentalActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.start_reservation(
            user_id,
            str(organization_id),
            str(shop_id),
            str(reservation_id),
            body,
        )
        return RentalReservationResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{reservation_id}/return", response_model=RentalReservationResponse)
def return_shop_rental(
    organization_id: UUID,
    shop_id: UUID,
    reservation_id: UUID,
    body: RentalActionRequest = Body(default_factory=RentalActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.return_reservation(
            user_id,
            str(organization_id),
            str(shop_id),
            str(reservation_id),
            body,
        )
        return RentalReservationResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{reservation_id}/cancel", response_model=RentalReservationResponse)
def cancel_shop_rental(
    organization_id: UUID,
    shop_id: UUID,
    reservation_id: UUID,
    body: RentalActionRequest = Body(default_factory=RentalActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.cancel_reservation(
            user_id,
            str(organization_id),
            str(shop_id),
            str(reservation_id),
            body,
        )
        return RentalReservationResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc
