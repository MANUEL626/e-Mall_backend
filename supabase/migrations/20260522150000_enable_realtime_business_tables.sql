-- Realtime business tables.
--
-- Pattern:
-- - FastAPI keeps the business writes and validations.
-- - Supabase Realtime pushes Postgres changes to authenticated clients.
-- - RLS still decides which rows a client can receive.

CREATE OR REPLACE FUNCTION public.add_table_to_supabase_realtime(
    p_schema_name text,
    p_table_name text
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_publication
        WHERE pubname = 'supabase_realtime'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = p_schema_name
          AND tablename = p_table_name
    ) THEN
        EXECUTE format(
            'ALTER PUBLICATION supabase_realtime ADD TABLE %I.%I',
            p_schema_name,
            p_table_name
        );
    END IF;
END;
$$;

-- Useful DELETE payloads for client-side state reconciliation.
ALTER TABLE public.users REPLICA IDENTITY FULL;
ALTER TABLE public.organizations REPLICA IDENTITY FULL;
ALTER TABLE public.members REPLICA IDENTITY FULL;
ALTER TABLE public.organization_articles REPLICA IDENTITY FULL;
ALTER TABLE public.organization_article_posts REPLICA IDENTITY FULL;
ALTER TABLE public.organization_article_orders REPLICA IDENTITY FULL;
ALTER TABLE public.organization_article_order_lines REPLICA IDENTITY FULL;
ALTER TABLE public.organization_customer_sale_orders REPLICA IDENTITY FULL;
ALTER TABLE public.organization_customer_sale_order_lines REPLICA IDENTITY FULL;
ALTER TABLE public.organization_customer_sale_order_status_events REPLICA IDENTITY FULL;
ALTER TABLE public.customer_sale_delivery_track_points REPLICA IDENTITY FULL;
ALTER TABLE public.conversations REPLICA IDENTITY FULL;
ALTER TABLE public.conversation_participants REPLICA IDENTITY FULL;
ALTER TABLE public.messages REPLICA IDENTITY FULL;

-- Back-office catalogue and stock.
SELECT public.add_table_to_supabase_realtime('public', 'organization_articles');
SELECT public.add_table_to_supabase_realtime('public', 'organization_article_posts');

-- Supplier orders / stock reception.
SELECT public.add_table_to_supabase_realtime('public', 'organization_article_orders');
SELECT public.add_table_to_supabase_realtime('public', 'organization_article_order_lines');

-- Customer sales / delivery lifecycle.
SELECT public.add_table_to_supabase_realtime('public', 'organization_customer_sale_orders');
SELECT public.add_table_to_supabase_realtime('public', 'organization_customer_sale_order_lines');
SELECT public.add_table_to_supabase_realtime('public', 'organization_customer_sale_order_status_events');
SELECT public.add_table_to_supabase_realtime('public', 'customer_sale_delivery_track_points');

-- Organization teams.
SELECT public.add_table_to_supabase_realtime('public', 'members');
SELECT public.add_table_to_supabase_realtime('public', 'users');
SELECT public.add_table_to_supabase_realtime('public', 'organizations');

-- Messaging list + message stream.
SELECT public.add_table_to_supabase_realtime('public', 'conversations');
SELECT public.add_table_to_supabase_realtime('public', 'conversation_participants');
SELECT public.add_table_to_supabase_realtime('public', 'messages');

DROP FUNCTION IF EXISTS public.add_table_to_supabase_realtime(text, text);

-- Customers can subscribe to active products and active/ready posts.
DROP POLICY IF EXISTS organization_articles_select_customer_active ON public.organization_articles;
CREATE POLICY organization_articles_select_customer_active
    ON public.organization_articles
    FOR SELECT
    TO authenticated
    USING (active IS TRUE);

DROP POLICY IF EXISTS organization_article_posts_select_customer_active ON public.organization_article_posts;
CREATE POLICY organization_article_posts_select_customer_active
    ON public.organization_article_posts
    FOR SELECT
    TO authenticated
    USING (
        active IS TRUE
        AND (
            media_kind = 'image'::public.article_post_media_kind_enum
            OR processing_status = 'ready'
        )
        AND EXISTS (
            SELECT 1
            FROM public.organization_articles a
            WHERE a.id = organization_article_id
              AND a.active IS TRUE
        )
    );

-- Members can receive organization/team changes for organizations they belong to.
DROP POLICY IF EXISTS organizations_select_member ON public.organizations;
CREATE POLICY organizations_select_member
    ON public.organizations
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(id));

DROP POLICY IF EXISTS members_select_same_org_member ON public.members;
CREATE POLICY members_select_same_org_member
    ON public.members
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS users_select_same_org_member ON public.users;
CREATE POLICY users_select_same_org_member
    ON public.users
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.members target_member
            WHERE target_member.user_id = users.id
              AND public.is_org_member(target_member.organization_id)
        )
    );
