-- Hot-path list RPC for supplier/article orders.
-- Returns one row per order plus its lines and computed total_amount.

CREATE OR REPLACE FUNCTION public.list_article_orders_with_lines(
    p_user_id uuid,
    p_organization_id uuid,
    p_shop_id uuid DEFAULT NULL,
    p_status text DEFAULT NULL,
    p_limit integer DEFAULT 50,
    p_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    organization_id uuid,
    shop_id uuid,
    status text,
    currency text,
    total_amount numeric,
    note text,
    created_at timestamptz,
    updated_at timestamptz,
    organization_article_order_lines jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.members AS m
        WHERE m.user_id = p_user_id
          AND m.organization_id = p_organization_id
          AND m.activity_status IS TRUE
    ) THEN
        RAISE EXCEPTION 'Acces refuse : membre actif requis pour cette organisation'
            USING ERRCODE = '42501';
    END IF;

    IF p_shop_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM public.organization_shops AS s
        WHERE s.id = p_shop_id
          AND s.organization_id = p_organization_id
          AND s.shop_type = 'sales'
          AND s.status <> 'archived'
    ) THEN
        RAISE EXCEPTION 'Boutique de vente introuvable pour cette organisation'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH page AS (
        SELECT o.*
        FROM public.organization_article_orders AS o
        WHERE o.organization_id = p_organization_id
          AND (p_shop_id IS NULL OR o.shop_id = p_shop_id)
          AND (p_status IS NULL OR o.status::text = p_status)
        ORDER BY o.created_at DESC
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 200))
        OFFSET GREATEST(0, COALESCE(p_offset, 0))
    ),
    line_totals AS (
        SELECT
            l.order_id,
            COALESCE(SUM(l.total_price), 0)::numeric(14, 2) AS total_amount,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', l.id,
                        'order_id', l.order_id,
                        'article_id', l.article_id,
                        'quantity_ordered', l.quantity_ordered,
                        'unit_price', l.unit_price,
                        'total_price', l.total_price,
                        'quantity_received', l.quantity_received,
                        'shortage_reason', l.shortage_reason,
                        'received_at', l.received_at,
                        'created_at', l.created_at
                    )
                    ORDER BY l.created_at ASC
                ),
                '[]'::jsonb
            ) AS lines
        FROM public.organization_article_order_lines AS l
        WHERE l.order_id IN (SELECT page.id FROM page)
        GROUP BY l.order_id
    )
    SELECT
        p.id,
        p.organization_id,
        p.shop_id,
        p.status::text,
        p.currency,
        COALESCE(t.total_amount, 0)::numeric(14, 2),
        p.note,
        p.created_at,
        p.updated_at,
        COALESCE(t.lines, '[]'::jsonb)
    FROM page AS p
    LEFT JOIN line_totals AS t
        ON t.order_id = p.id
    ORDER BY p.created_at DESC;
END;
$$;

REVOKE ALL ON FUNCTION public.list_article_orders_with_lines(uuid, uuid, uuid, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.list_article_orders_with_lines(uuid, uuid, uuid, text, integer, integer) TO service_role;
