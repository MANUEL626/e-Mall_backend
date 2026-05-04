"""
Modèles Pydantic : messagerie (conversations, messages).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ConversationType(str, Enum):
    """Aligné sur `public.conversation_type_enum`."""

    direct = "direct"
    group = "group"


class DirectConversationRequest(BaseModel):
    """Ouverture d'une conversation 1–1 avec un autre utilisateur (`public.users`)."""

    other_user_id: UUID


class ConversationSummary(BaseModel):
    """Résumé d'un fil pour la liste."""

    id: UUID
    type: ConversationType
    title: Optional[str] = None
    last_message_at: Optional[datetime] = None
    created_at: datetime


class ConversationPeerPreview(BaseModel):
    """Interlocuteur pour l'affichage liste (conversation directe)."""

    id: UUID
    username: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_picture: Optional[str] = None
    user_type: Optional[str] = None


class ConversationListItem(BaseModel):
    """Élément de liste avec métadonnées du correspondant (direct)."""

    id: UUID
    type: ConversationType
    title: Optional[str] = None
    last_message_at: Optional[datetime] = None
    created_at: datetime
    other_participant: Optional[ConversationPeerPreview] = None
    last_message: Optional[MessageItem] = None


class ConversationParticipantUser(BaseModel):
    """Aperçu profil pour les participants."""

    id: UUID
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_picture: Optional[str] = None
    user_type: Optional[str] = None


class ConversationParticipantItem(BaseModel):
    user_id: UUID
    joined_at: datetime
    user: Optional[ConversationParticipantUser] = None


class ConversationDetailResponse(BaseModel):
    conversation: ConversationSummary
    participants: List[ConversationParticipantItem]


class MessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=20000)

    @field_validator("body")
    @classmethod
    def strip_body(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Le message ne peut pas être vide")
        return s


class MessageItem(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_id: UUID
    body: str
    created_at: datetime


class MessageListResponse(BaseModel):
    """Page ordonnée du plus ancien au plus récent (affichage type bulles)."""

    messages: List[MessageItem]


class DirectConversationResponse(BaseModel):
    conversation_id: UUID


class OrganizationMemberForMessaging(BaseModel):
    """
    Profil minimal d'un membre actif d'organisation utilisable pour initier un chat.
    """

    user_id: UUID
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_picture: Optional[str] = None
    user_type: Optional[str] = None
    member_type: str
    member_role: Optional[str] = None
