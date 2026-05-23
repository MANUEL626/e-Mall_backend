"""
Routes REST messagerie (JWT Supabase ; RLS côté base).
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from features.auth.auth_service import AuthService
from features.messaging.messaging_models import (
    ConversationDetailResponse,
    ConversationListItem,
    DirectConversationRequest,
    DirectConversationResponse,
    MessageCreate,
    MessageItem,
    MessageListResponse,
    OrganizationMemberForMessaging,
)
from features.messaging.messaging_service import MessagingService

router = APIRouter(prefix="/api/v1/messaging", tags=["Messaging"])

security = HTTPBearer()
_auth = AuthService()
_service = MessagingService()


def _current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    try:
        return _auth.get_user_id_from_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.post(
    "/conversations/direct",
    response_model=DirectConversationResponse,
    status_code=status.HTTP_200_OK,
)
def open_or_get_direct_conversation(
    body: DirectConversationRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Retrouve ou crée une conversation directe entre l'utilisateur connecté
    et `other_user_id` (membre ou customer, tant qu'une ligne `public.users` existe).
    """
    token = credentials.credentials
    try:
        return _service.get_or_create_direct(token, str(body.other_user_id))
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
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/conversations", response_model=List[ConversationListItem])
def list_my_conversations(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Liste les conversations dont l'utilisateur est participant (tri récent)."""
    token = credentials.credentials
    uid = _current_user_id(credentials)
    return _service.list_conversations(token, uid)


@router.get(
    "/organizations/{organization_id}/members",
    response_model=List[OrganizationMemberForMessaging],
)
def list_organization_members_for_messaging(
    organization_id: UUID,
    include_self: bool = Query(
        False,
        description="Inclure ou non l'utilisateur courant dans la liste.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Liste les membres actifs d'une organisation (profil minimal)
    pour initier un chat direct.
    """
    uid = _current_user_id(credentials)
    try:
        return _service.list_organization_members_for_messaging(
            requester_user_id=uid,
            organization_id=str(organization_id),
            include_self=include_self,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation_detail(
    conversation_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials
    try:
        return _service.get_conversation(token, str(conversation_id))
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
def list_conversation_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[datetime] = Query(
        None,
        description="ISO 8601 : messages plus anciens que cette date (pagination « charger plus »).",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Page de messages, ordre chronologique pour l'affichage (les plus anciens en premier).
    """
    token = credentials.credentials
    return _service.list_messages(
        token,
        str(conversation_id),
        limit=limit,
        before=before,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageItem,
    status_code=status.HTTP_201_CREATED,
)
def post_message(
    conversation_id: UUID,
    body: MessageCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials
    uid = _current_user_id(credentials)
    try:
        return _service.send_message(token, uid, str(conversation_id), body.body)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
