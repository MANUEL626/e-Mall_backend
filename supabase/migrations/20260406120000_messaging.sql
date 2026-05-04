-- Messagerie : conversations, participants, messages (RLS + Realtime).
-- Compatible customer / member / tout utilisateur avec une ligne dans public.users.

DO $$
BEGIN
    CREATE TYPE public.conversation_type_enum AS ENUM ('direct', 'group');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type public.conversation_type_enum NOT NULL DEFAULT 'direct',
    title text,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_message_at timestamptz
);

COMMENT ON TABLE public.conversations IS
    'Fil de discussion ; type direct = conversation 1–1 après déduplication logique.';

CREATE TABLE IF NOT EXISTS public.conversation_participants (
    conversation_id uuid NOT NULL REFERENCES public.conversations (id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    joined_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_participants_user
    ON public.conversation_participants (user_id);

CREATE TABLE IF NOT EXISTS public.messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES public.conversations (id) ON DELETE CASCADE,
    sender_id uuid NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT messages_body_not_blank CHECK (length(trim(body)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
    ON public.messages (conversation_id, created_at DESC);

-- Mise à jour last_message_at sans accorder UPDATE conversations aux clients.
CREATE OR REPLACE FUNCTION public.messages_touch_conversation_last_message()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    UPDATE public.conversations
    SET last_message_at = NEW.created_at
    WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_messages_touch_conversation ON public.messages;
CREATE TRIGGER trg_messages_touch_conversation
    AFTER INSERT ON public.messages
    FOR EACH ROW
    EXECUTE FUNCTION public.messages_touch_conversation_last_message();

CREATE OR REPLACE FUNCTION public.is_conversation_participant(p_conversation_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.conversation_participants cp
        WHERE cp.conversation_id = p_conversation_id
          AND cp.user_id = auth.uid()
    );
$$;

COMMENT ON FUNCTION public.is_conversation_participant(uuid) IS
    'True si l''utilisateur JWT est participant du fil.';

-- Création atomique d''un fil direct (ou récupération s''il existe déjà).
CREATE OR REPLACE FUNCTION public.get_or_create_direct_conversation(p_other_user_id uuid)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_me uuid;
    v_cid uuid;
BEGIN
    v_me := auth.uid();
    IF v_me IS NULL THEN
        RAISE EXCEPTION 'Non authentifié';
    END IF;

    IF p_other_user_id = v_me THEN
        RAISE EXCEPTION 'Interlocuteur invalide';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = p_other_user_id) THEN
        RAISE EXCEPTION 'Utilisateur introuvable';
    END IF;

    SELECT c.id INTO v_cid
    FROM public.conversations c
    INNER JOIN public.conversation_participants p1
        ON p1.conversation_id = c.id AND p1.user_id = v_me
    INNER JOIN public.conversation_participants p2
        ON p2.conversation_id = c.id AND p2.user_id = p_other_user_id
    WHERE c.type = 'direct'
    LIMIT 1;

    IF v_cid IS NOT NULL THEN
        RETURN v_cid;
    END IF;

    INSERT INTO public.conversations (type)
    VALUES ('direct')
    RETURNING id INTO v_cid;

    INSERT INTO public.conversation_participants (conversation_id, user_id)
    VALUES (v_cid, v_me);

    INSERT INTO public.conversation_participants (conversation_id, user_id)
    VALUES (v_cid, p_other_user_id);

    RETURN v_cid;
END;
$$;

COMMENT ON FUNCTION public.get_or_create_direct_conversation(uuid) IS
    'Ouvre ou retrouve une conversation directe entre l''utilisateur courant et p_other_user_id.';

GRANT EXECUTE ON FUNCTION public.get_or_create_direct_conversation(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_or_create_direct_conversation(uuid) TO service_role;

ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS conversations_select_participant ON public.conversations;
CREATE POLICY conversations_select_participant
    ON public.conversations
    FOR SELECT
    TO authenticated
    USING (public.is_conversation_participant(id));

-- Pas d''INSERT/UPDATE/DELETE direct sur conversations pour le rôle client (création via RPC).

DROP POLICY IF EXISTS conversation_participants_select_member ON public.conversation_participants;
CREATE POLICY conversation_participants_select_member
    ON public.conversation_participants
    FOR SELECT
    TO authenticated
    USING (public.is_conversation_participant(conversation_id));

-- Pas d''INSERT manuel : ajout de participants via get_or_create_direct_conversation (défini par SECURITY DEFINER).

DROP POLICY IF EXISTS messages_select_participant ON public.messages;
CREATE POLICY messages_select_participant
    ON public.messages
    FOR SELECT
    TO authenticated
    USING (public.is_conversation_participant(conversation_id));

DROP POLICY IF EXISTS messages_insert_participant ON public.messages;
CREATE POLICY messages_insert_participant
    ON public.messages
    FOR INSERT
    TO authenticated
    WITH CHECK (
        sender_id = auth.uid()
        AND public.is_conversation_participant(conversation_id)
    );

-- Realtime (événements INSERT sur messages pour les clients abonnés, sous réserve RLS).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'public'
          AND tablename = 'messages'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;
    END IF;
END $$;

-- Lecture du profil applicatif pour soi-même ou pour un utilisateur partageant une conversation.
DROP POLICY IF EXISTS users_select_self_or_conversation_peer ON public.users;
CREATE POLICY users_select_self_or_conversation_peer
    ON public.users
    FOR SELECT
    TO authenticated
    USING (
        id = auth.uid()
        OR EXISTS (
            SELECT 1
            FROM public.conversation_participants me
            INNER JOIN public.conversation_participants them
                ON them.conversation_id = me.conversation_id
            WHERE me.user_id = auth.uid()
              AND them.user_id = users.id
        )
    );
