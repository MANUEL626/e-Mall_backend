"""
Messagerie : appels PostgREST avec le JWT utilisateur (RLS).
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TypeVar
from uuid import UUID

from postgrest.exceptions import APIError
from supabase import Client

from config.supabase_client import get_supabase_client_with_token, supabase_admin
from features.messaging.messaging_models import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationParticipantItem,
    ConversationParticipantUser,
    ConversationPeerPreview,
    ConversationSummary,
    ConversationType,
    DirectConversationResponse,
    MessageItem,
    MessageListResponse,
    OrganizationMemberForMessaging,
)

T = TypeVar("T")

MESSAGING_SCHEMA_MISSING_DETAIL = (
    "Messagerie non disponible : le schéma n'est pas déployé sur ce projet Supabase. "
    "Appliquer la migration `supabase/migrations/20260406120000_messaging.sql` "
    "(CLI : `supabase link` puis `supabase db push`, ou exécuter le SQL dans le SQL Editor du dashboard)."
)


class MessagingNotConfiguredError(Exception):
    """Tables / RPC messagerie absents (migration non appliquée sur l'instance Supabase)."""

    def __init__(self, detail: str = MESSAGING_SCHEMA_MISSING_DETAIL) -> None:
        super().__init__(detail)


class MessagingService:
    """Accès aux tables `conversations`, `conversation_participants`, `messages`."""

    def __init__(self) -> None:
        # Service role pour les contrôles d'appartenance org et la liste des membres.
        self.admin_db: Client = supabase_admin

    @staticmethod
    def _db(access_token: str) -> Client:
        return get_supabase_client_with_token(access_token)

    @staticmethod
    def _postgrest_execute(fn: Callable[[], T]) -> T:
        """
        PostgREST renvoie `PGRST205` si la table n'est pas dans le cache schéma
        (migration jamais appliquée sur ce projet).
        """
        try:
            return fn()
        except APIError as exc:
            # PGRST205 : table absente ; PGRST202 : fonction RPC absente — migration non appliquée.
            if exc.code in ("PGRST205", "PGRST202"):
                raise MessagingNotConfiguredError() from exc
            raise

    @staticmethod
    def _rpc_conversation_id(data: Any) -> str:
        """PostgREST renvoie souvent une chaîne UUID ou une liste d'une cellule."""
        if data is None:
            raise ValueError("Réponse vide de get_or_create_direct_conversation")
        if isinstance(data, str):
            return data
        if isinstance(data, list) and len(data) == 1:
            cell = data[0]
            if isinstance(cell, str):
                return cell
            if isinstance(cell, dict):
                for k, v in cell.items():
                    if v is not None:
                        return str(v)
        if isinstance(data, dict):
            for k, v in data.items():
                if v is not None:
                    return str(v)
        raise ValueError("Réponse inattendue de get_or_create_direct_conversation")

    @staticmethod
    def _map_rpc_exception(exc: Exception) -> None:
        raw = str(exc).lower()
        if "utilisateur introuvable" in raw:
            raise LookupError("Utilisateur introuvable") from exc
        if "interlocuteur invalide" in raw:
            raise ValueError("Interlocuteur invalide") from exc
        if "non authentifié" in raw:
            raise PermissionError("Non authentifié") from exc

    def get_or_create_direct(
        self, access_token: str, other_user_id: str
    ) -> DirectConversationResponse:
        client = self._db(access_token)
        try:
            result = self._postgrest_execute(
                lambda: client.rpc(
                    "get_or_create_direct_conversation",
                    {"p_other_user_id": other_user_id},
                ).execute()
            )
        except MessagingNotConfiguredError:
            raise
        except APIError:
            raise
        except Exception as exc:
            self._map_rpc_exception(exc)
            raise RuntimeError(str(exc)) from exc
        cid = self._rpc_conversation_id(result.data)
        return DirectConversationResponse(conversation_id=UUID(cid))

    def _fetch_last_messages_map(
        self,
        client: Client,
        conversation_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Dernier message par conversation (RPC DISTINCT ON, ou repli requête par fil)."""
        if not conversation_ids:
            return {}
        try:
            res = client.rpc(
                "get_last_messages_for_conversations",
                {"p_conversation_ids": conversation_ids},
            ).execute()
        except APIError as exc:
            if exc.code == "PGRST202":
                return self._fetch_last_messages_fallback(client, conversation_ids)
            raise
        out: Dict[str, Dict[str, Any]] = {}
        for r in res.data or []:
            if not isinstance(r, dict):
                continue
            cid = r.get("conversation_id")
            if cid is not None:
                out[str(cid)] = r
        return out

    def _fetch_last_messages_fallback(
        self,
        client: Client,
        conversation_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Si la RPC n'est pas encore déployée : un SELECT par conversation (RLS)."""
        out: Dict[str, Dict[str, Any]] = {}
        for cid in conversation_ids:
            r = self._postgrest_execute(
                lambda c=cid: client.table("messages")
                .select("id, conversation_id, sender_id, body, created_at")
                .eq("conversation_id", c)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if rows:
                out[cid] = rows[0]
        return out

    def list_conversations(
        self, access_token: str, user_id: str
    ) -> List[ConversationListItem]:
        client = self._db(access_token)
        res = self._postgrest_execute(
            lambda: client.table("conversation_participants")
            .select(
                "conversation_id, joined_at, conversations(id, type, title, last_message_at, created_at)"
            )
            .eq("user_id", user_id)
            .execute()
        )
        rows: List[Dict[str, Any]] = res.data or []
        summaries: List[ConversationSummary] = []
        for row in rows:
            c = row.get("conversations")
            if not c or not isinstance(c, dict):
                continue
            summaries.append(ConversationSummary.model_validate(c))

        def sort_key(s: ConversationSummary) -> datetime:
            if s.last_message_at:
                return s.last_message_at
            return s.created_at

        summaries.sort(key=sort_key, reverse=True)

        direct_ids = [
            str(s.id)
            for s in summaries
            if s.type == ConversationType.direct
        ]
        peer_by_conversation: Dict[str, str] = {}
        if direct_ids:
            pres = self._postgrest_execute(
                lambda: client.table("conversation_participants")
                .select("conversation_id, user_id")
                .in_("conversation_id", direct_ids)
                .neq("user_id", user_id)
                .execute()
            )
            for p in pres.data or []:
                cid = str(p.get("conversation_id"))
                uid = str(p.get("user_id"))
                if cid and uid:
                    peer_by_conversation[cid] = uid

        unique_peer_ids = list({uid for uid in peer_by_conversation.values()})
        user_by_id: Dict[str, Dict[str, Any]] = {}
        if unique_peer_ids:
            ures = self._postgrest_execute(
                lambda: client.table("users")
                .select(
                    "id, username, email, first_name, last_name, profile_picture, user_type"
                )
                .in_("id", unique_peer_ids)
                .execute()
            )
            for u in ures.data or []:
                user_by_id[str(u["id"])] = u

        all_cids = [str(s.id) for s in summaries]
        last_by_cid = self._fetch_last_messages_map(client, all_cids)

        out: List[ConversationListItem] = []
        for s in summaries:
            peer: Optional[ConversationPeerPreview] = None
            if s.type == ConversationType.direct:
                pid = peer_by_conversation.get(str(s.id))
                if pid:
                    raw = user_by_id.get(pid)
                    if raw:
                        peer = ConversationPeerPreview.model_validate(raw)
            lm_raw = last_by_cid.get(str(s.id))
            last_msg: Optional[MessageItem] = (
                MessageItem.model_validate(lm_raw) if lm_raw else None
            )
            out.append(
                ConversationListItem(
                    id=s.id,
                    type=s.type,
                    title=s.title,
                    last_message_at=s.last_message_at,
                    created_at=s.created_at,
                    other_participant=peer,
                    last_message=last_msg,
                )
            )
        return out

    def get_conversation(
        self, access_token: str, conversation_id: str
    ) -> ConversationDetailResponse:
        client = self._db(access_token)
        cres = self._postgrest_execute(
            lambda: client.table("conversations")
            .select("id, type, title, last_message_at, created_at")
            .eq("id", conversation_id)
            .limit(1)
            .execute()
        )
        crows = cres.data or []
        if not crows:
            raise LookupError("Conversation introuvable ou accès refusé")

        summary = ConversationSummary.model_validate(crows[0])

        pres = self._postgrest_execute(
            lambda: client.table("conversation_participants")
            .select("user_id, joined_at")
            .eq("conversation_id", conversation_id)
            .execute()
        )
        prows: List[Dict[str, Any]] = pres.data or []
        user_ids = [str(p["user_id"]) for p in prows]
        user_by_id: Dict[str, Dict[str, Any]] = {}
        if user_ids:
            ures = self._postgrest_execute(
                lambda: client.table("users")
                .select(
                    "id, username, first_name, last_name, profile_picture, user_type"
                )
                .in_("id", user_ids)
                .execute()
            )
            for u in ures.data or []:
                user_by_id[str(u["id"])] = u

        participants: List[ConversationParticipantItem] = []
        for p in prows:
            uid = str(p["user_id"])
            raw_u = user_by_id.get(uid)
            user_model = (
                ConversationParticipantUser.model_validate(raw_u) if raw_u else None
            )
            participants.append(
                ConversationParticipantItem(
                    user_id=p["user_id"],
                    joined_at=p["joined_at"],
                    user=user_model,
                )
            )

        return ConversationDetailResponse(conversation=summary, participants=participants)

    def list_messages(
        self,
        access_token: str,
        conversation_id: str,
        *,
        limit: int = 50,
        before: Optional[datetime] = None,
    ) -> MessageListResponse:
        client = self._db(access_token)
        lim = max(1, min(limit, 200))

        def _run() -> Any:
            q = (
                client.table("messages")
                .select("id, conversation_id, sender_id, body, created_at")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=True)
                .limit(lim)
            )
            if before is not None:
                q = q.lt("created_at", before.isoformat())
            return q.execute()

        res = self._postgrest_execute(_run)
        rows: List[Dict[str, Any]] = res.data or []
        rows.reverse()
        messages = [MessageItem.model_validate(r) for r in rows]
        return MessageListResponse(messages=messages)

    def send_message(
        self,
        access_token: str,
        sender_id: str,
        conversation_id: str,
        body: str,
    ) -> MessageItem:
        client = self._db(access_token)
        payload = {
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "body": body,
        }
        try:
            ins = self._postgrest_execute(
                lambda: client.table("messages").insert(payload).execute()
            )
        except APIError as exc:
            # Violation RLS / contraintes FK : utilisateur non participant, conversation absente, etc.
            raise PermissionError(
                "Impossible d'envoyer le message (accès refusé ou conversation inexistante)"
            ) from exc
        data = ins.data or []
        if data:
            return MessageItem.model_validate(data[0])

        # Fallback si le backend PostgREST retourne une représentation minimale.
        # On relit le dernier message de l'expéditeur dans ce fil.
        refetch = self._postgrest_execute(
            lambda: client.table("messages")
            .select("id, conversation_id, sender_id, body, created_at")
            .eq("conversation_id", conversation_id)
            .eq("sender_id", sender_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = refetch.data or []
        if not rows:
            raise PermissionError(
                "Impossible d'envoyer le message (accès refusé ou conversation inexistante)"
            )
        return MessageItem.model_validate(rows[0])

    def list_organization_members_for_messaging(
        self,
        requester_user_id: str,
        organization_id: str,
        *,
        include_self: bool = False,
    ) -> List[OrganizationMemberForMessaging]:
        """
        Retourne les membres actifs d'une organisation pour démarrer un chat.
        Accès autorisé uniquement si le demandeur est lui-même membre actif de l'organisation.
        """
        membership_check = (
            self.admin_db.table("members")
            .select("id")
            .eq("organization_id", organization_id)
            .eq("user_id", requester_user_id)
            .eq("activity_status", True)
            .limit(1)
            .execute()
        )
        if not (membership_check.data or []):
            raise PermissionError(
                "Accès refusé : vous n'êtes pas membre actif de cette organisation"
            )

        rows = (
            self.admin_db.table("members")
            .select(
                "user_id, member_type, member_role, users(id, username, first_name, last_name, profile_picture, user_type)"
            )
            .eq("organization_id", organization_id)
            .eq("activity_status", True)
            .execute()
        ).data or []

        out: List[OrganizationMemberForMessaging] = []
        for row in rows:
            uid = str(row.get("user_id"))
            if (not include_self) and uid == requester_user_id:
                continue
            u = row.get("users") or {}
            out.append(
                OrganizationMemberForMessaging(
                    user_id=uid,
                    username=u.get("username"),
                    first_name=u.get("first_name"),
                    last_name=u.get("last_name"),
                    profile_picture=u.get("profile_picture"),
                    user_type=u.get("user_type"),
                    member_type=row.get("member_type") or "member",
                    member_role=row.get("member_role"),
                )
            )

        out.sort(
            key=lambda m: (
                (m.first_name or "").lower(),
                (m.last_name or "").lower(),
                (m.username or "").lower(),
            )
        )
        return out
