-- Dernier message par conversation (liste inbox), une ligne par fil, respect RLS (SECURITY INVOKER).

CREATE OR REPLACE FUNCTION public.get_last_messages_for_conversations(p_conversation_ids uuid[])
RETURNS TABLE (
    id uuid,
    conversation_id uuid,
    sender_id uuid,
    body text,
    created_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT DISTINCT ON (m.conversation_id)
        m.id,
        m.conversation_id,
        m.sender_id,
        m.body,
        m.created_at
    FROM public.messages m
    WHERE m.conversation_id = ANY (p_conversation_ids)
    ORDER BY m.conversation_id, m.created_at DESC;
$$;

COMMENT ON FUNCTION public.get_last_messages_for_conversations(uuid[]) IS
    'Dernier message par conversation (liste). RLS messages appliquée.';

GRANT EXECUTE ON FUNCTION public.get_last_messages_for_conversations(uuid[]) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_last_messages_for_conversations(uuid[]) TO service_role;
