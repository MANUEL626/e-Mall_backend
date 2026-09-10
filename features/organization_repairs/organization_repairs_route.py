from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.organization_repairs.organization_repairs_models import (
    RepairActionRequest,
    RepairInvoiceResponse,
    RepairPartCreate,
    RepairPartResponse,
    RepairRequestCreate,
    RepairRequestResponse,
    RepairRequestStatus,
    RepairRequestUpdate,
    RepairSendQuoteRequest,
    RepairStatusUpdate,
)
from features.organization_repairs.organization_repairs_service import (
    OrganizationRepairsService,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/shops/{shop_id}/repairs",
    tags=["Organization shop repairs"],
)

security = HTTPBearer()
_auth = AuthService()
_service = OrganizationRepairsService()


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


@router.get("", response_model=List[RepairRequestResponse])
def list_shop_repairs(
    organization_id: UUID,
    shop_id: UUID,
    repair_status: Optional[RepairRequestStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(_current_user_id),
):
    try:
        rows = _service.list_repairs(
            user_id,
            str(organization_id),
            str(shop_id),
            status=repair_status,
            limit=limit,
            offset=offset,
        )
        return [RepairRequestResponse.model_validate(row) for row in rows]
    except Exception as exc:
        raise _exc(exc) from exc


@router.post(
    "",
    response_model=RepairRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shop_repair(
    organization_id: UUID,
    shop_id: UUID,
    body: RepairRequestCreate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.create_repair(user_id, str(organization_id), str(shop_id), body)
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/{repair_id}", response_model=RepairRequestResponse)
def get_shop_repair(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_repair(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.patch("/{repair_id}", response_model=RepairRequestResponse)
def patch_shop_repair(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairRequestUpdate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.update_repair(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.patch("/{repair_id}/status", response_model=RepairRequestResponse)
def patch_shop_repair_status(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairStatusUpdate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.update_status(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body.status,
            note=body.note,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/receive", response_model=RepairRequestResponse)
def receive_shop_repair(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairActionRequest = Body(default_factory=RepairActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.receive_repair(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/start-diagnosis", response_model=RepairRequestResponse)
def start_shop_repair_diagnosis(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairActionRequest = Body(default_factory=RepairActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.start_diagnosis(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/send-quote", response_model=RepairRequestResponse)
def send_shop_repair_quote(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairSendQuoteRequest,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.send_quote(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/approve-quote", response_model=RepairRequestResponse)
def approve_shop_repair_quote(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairActionRequest = Body(default_factory=RepairActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.approve_quote(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/start-repair", response_model=RepairRequestResponse)
def start_shop_repair_work(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairActionRequest = Body(default_factory=RepairActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.start_repair(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/mark-ready", response_model=RepairRequestResponse)
def mark_shop_repair_ready(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairActionRequest = Body(default_factory=RepairActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.mark_ready(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/deliver", response_model=RepairRequestResponse)
def deliver_shop_repair(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairActionRequest = Body(default_factory=RepairActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.deliver_repair(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.post("/{repair_id}/cancel", response_model=RepairRequestResponse)
def cancel_shop_repair(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairActionRequest = Body(default_factory=RepairActionRequest),
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.cancel_repair(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairRequestResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/{repair_id}/invoice", response_model=RepairInvoiceResponse)
def get_shop_repair_invoice(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.get_invoice(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
        )
        return RepairInvoiceResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc


@router.get("/{repair_id}/parts", response_model=List[RepairPartResponse])
def list_shop_repair_parts(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    user_id: str = Depends(_current_user_id),
):
    try:
        rows = _service.list_parts(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
        )
        return [RepairPartResponse.model_validate(row) for row in rows]
    except Exception as exc:
        raise _exc(exc) from exc


@router.post(
    "/{repair_id}/parts",
    response_model=RepairPartResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_shop_repair_part(
    organization_id: UUID,
    shop_id: UUID,
    repair_id: UUID,
    body: RepairPartCreate,
    user_id: str = Depends(_current_user_id),
):
    try:
        row = _service.add_part(
            user_id,
            str(organization_id),
            str(shop_id),
            str(repair_id),
            body,
        )
        return RepairPartResponse.model_validate(row)
    except Exception as exc:
        raise _exc(exc) from exc
