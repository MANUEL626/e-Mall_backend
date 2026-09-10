-- Hot-path list RPCs for customer sale orders.
-- They return one row per order plus a JSON array of lines enriched with article_name.

CREATE OR REPLACE FUNCTION public.list_customer_sales_with_lines(
    p_customer_id uuid,
    p_statuses text[] DEFAULT NULL,
    p_limit integer DEFAULT 50,
    p_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    organization_id uuid,
    shop_id uuid,
    fulfillment_type text,
    customer_id uuid,
    status text,
    assigned_delivery_member_id uuid,
    delivery_longitude double precision,
    delivery_latitude double precision,
    currency text,
    notes text,
    external_customer_label text,
    subtotal_amount numeric,
    total_items integer,
    total_lines integer,
    created_at timestamptz,
    updated_at timestamptz,
    organization_customer_sale_order_lines jsonb
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    WITH page AS (
        SELECT o.*
        FROM public.organization_customer_sale_orders AS o
        WHERE o.customer_id = p_customer_id
          AND (p_statuses IS NULL OR o.status::text = ANY (p_statuses))
        ORDER BY o.created_at DESC
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 200))
        OFFSET GREATEST(0, COALESCE(p_offset, 0))
    ),
    line_totals AS (
        SELECT
            l.order_id,
            COALESCE(SUM(l.quantity * l.unit_price_snapshot), 0)::numeric(14, 2) AS subtotal_amount,
            COALESCE(SUM(l.quantity), 0)::integer AS total_items,
            COUNT(*)::integer AS total_lines,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', l.id,
                        'order_id', l.order_id,
                        'article_id', l.article_id,
                        'article_name', a.name,
                        'quantity', l.quantity,
                        'unit_price_snapshot', l.unit_price_snapshot,
                        'currency_snapshot', l.currency_snapshot
                    )
                    ORDER BY l.created_at ASC
                ),
                '[]'::jsonb
            ) AS lines
        FROM public.organization_customer_sale_order_lines AS l
        LEFT JOIN public.organization_articles AS a
            ON a.id = l.article_id
        WHERE l.order_id IN (SELECT page.id FROM page)
        GROUP BY l.order_id
    )
    SELECT
        p.id,
        p.organization_id,
        p.shop_id,
        p.fulfillment_type::text,
        p.customer_id,
        p.status::text,
        p.assigned_delivery_member_id,
        p.delivery_longitude,
        p.delivery_latitude,
        p.currency,
        p.notes,
        p.external_customer_label,
        COALESCE(t.subtotal_amount, 0)::numeric(14, 2),
        COALESCE(t.total_items, 0),
        COALESCE(t.total_lines, 0),
        p.created_at,
        p.updated_at,
        COALESCE(t.lines, '[]'::jsonb)
    FROM page AS p
    LEFT JOIN line_totals AS t
        ON t.order_id = p.id
    ORDER BY p.created_at DESC;
$$;

CREATE OR REPLACE FUNCTION public.list_org_customer_sales_with_lines(
    p_user_id uuid,
    p_organization_id uuid,
    p_shop_id uuid DEFAULT NULL,
    p_statuses text[] DEFAULT NULL,
    p_limit integer DEFAULT 50,
    p_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    organization_id uuid,
    shop_id uuid,
    fulfillment_type text,
    customer_id uuid,
    status text,
    assigned_delivery_member_id uuid,
    delivery_longitude double precision,
    delivery_latitude double precision,
    currency text,
    notes text,
    external_customer_label text,
    subtotal_amount numeric,
    total_items integer,
    total_lines integer,
    created_at timestamptz,
    updated_at timestamptz,
    organization_customer_sale_order_lines jsonb
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
        FROM public.organization_customer_sale_orders AS o
        WHERE o.organization_id = p_organization_id
          AND (p_shop_id IS NULL OR o.shop_id = p_shop_id)
          AND (p_statuses IS NULL OR o.status::text = ANY (p_statuses))
        ORDER BY o.created_at DESC
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 200))
        OFFSET GREATEST(0, COALESCE(p_offset, 0))
    ),
    line_totals AS (
        SELECT
            l.order_id,
            COALESCE(SUM(l.quantity * l.unit_price_snapshot), 0)::numeric(14, 2) AS subtotal_amount,
            COALESCE(SUM(l.quantity), 0)::integer AS total_items,
            COUNT(*)::integer AS total_lines,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', l.id,
                        'order_id', l.order_id,
                        'article_id', l.article_id,
                        'article_name', a.name,
                        'quantity', l.quantity,
                        'unit_price_snapshot', l.unit_price_snapshot,
                        'currency_snapshot', l.currency_snapshot
                    )
                    ORDER BY l.created_at ASC
                ),
                '[]'::jsonb
            ) AS lines
        FROM public.organization_customer_sale_order_lines AS l
        LEFT JOIN public.organization_articles AS a
            ON a.id = l.article_id
        WHERE l.order_id IN (SELECT page.id FROM page)
        GROUP BY l.order_id
    )
    SELECT
        p.id,
        p.organization_id,
        p.shop_id,
        p.fulfillment_type::text,
        p.customer_id,
        p.status::text,
        p.assigned_delivery_member_id,
        p.delivery_longitude,
        p.delivery_latitude,
        p.currency,
        p.notes,
        p.external_customer_label,
        COALESCE(t.subtotal_amount, 0)::numeric(14, 2),
        COALESCE(t.total_items, 0),
        COALESCE(t.total_lines, 0),
        p.created_at,
        p.updated_at,
        COALESCE(t.lines, '[]'::jsonb)
    FROM page AS p
    LEFT JOIN line_totals AS t
        ON t.order_id = p.id
    ORDER BY p.created_at DESC;
END;
$$;

REVOKE ALL ON FUNCTION public.list_customer_sales_with_lines(uuid, text[], integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.list_org_customer_sales_with_lines(uuid, uuid, uuid, text[], integer, integer) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.list_customer_sales_with_lines(uuid, text[], integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.list_org_customer_sales_with_lines(uuid, uuid, uuid, text[], integer, integer) TO service_role;
