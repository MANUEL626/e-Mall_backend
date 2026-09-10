-- Indexes for messaging list endpoints and Realtime-backed message screens.

CREATE INDEX IF NOT EXISTS idx_conversation_participants_user_conversation
    ON public.conversation_participants (
        user_id,
        conversation_id
    );

CREATE INDEX IF NOT EXISTS idx_conversation_participants_conversation_user
    ON public.conversation_participants (
        conversation_id,
        user_id
    );

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
    ON public.messages (
        conversation_id,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_conversations_last_message_created
    ON public.conversations (
        last_message_at DESC NULLS LAST,
        created_at DESC
    );
