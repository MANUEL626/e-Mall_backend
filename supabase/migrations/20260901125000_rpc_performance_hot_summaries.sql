-- Targeted Performance RPCs for hot dashboard summaries.
-- These aggregate in SQL to avoid transferring thousands of rows to Python.

CREATE OR REPLACE FUNCTION public.get_performance_inventory_summary(
    p_organization_id uuid
)
RETURNS TABLE (
    total_products integer,
    active_products integer,
    inactive_products integer,
    in_stock_products integer,
    low_stock_products integer,
    out_of_stock_products integer,
    active_in_stock_products integer,
    active_low_stock_products integer,
    active_out_of_stock_products integer,
    stock_quantity integer,
    reserved_quantity integer,
    active_products_with_reserved_stock integer
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        COUNT(*)::integer AS total_products,
        COUNT(*) FILTER (WHERE active IS TRUE)::integer AS active_products,
        COUNT(*) FILTER (WHERE active IS NOT TRUE)::integer AS inactive_products,
        COUNT(*) FILTER (WHERE stock_status::text = 'in_stock')::integer AS in_stock_products,
        COUNT(*) FILTER (WHERE stock_status::text = 'low_stock')::integer AS low_stock_products,
        COUNT(*) FILTER (WHERE stock_status::text = 'out_of_stock')::integer AS out_of_stock_products,
        COUNT(*) FILTER (
            WHERE active IS TRUE AND stock_status::text = 'in_stock'
        )::integer AS active_in_stock_products,
        COUNT(*) FILTER (
            WHERE active IS TRUE AND stock_status::text = 'low_stock'
        )::integer AS active_low_stock_products,
        COUNT(*) FILTER (
            WHERE active IS TRUE AND stock_status::text = 'out_of_stock'
        )::integer AS active_out_of_stock_products,
        COALESCE(SUM(stock_quantity), 0)::integer AS stock_quantity,
        COALESCE(SUM(reserved_quantity), 0)::integer AS reserved_quantity,
        COUNT(*) FILTER (
            WHERE active IS TRUE AND COALESCE(reserved_quantity, 0) > 0
        )::integer AS active_products_with_reserved_stock
    FROM public.organization_articles
    WHERE organization_id = p_organization_id
      AND resource_scope = 'sales_item';
$$;

CREATE OR REPLACE FUNCTION public.get_performance_sales_status_summary(
    p_organization_id uuid,
    p_start timestamptz,
    p_end timestamptz
)
RETURNS TABLE (
    total_orders integer,
    pipeline_orders integer,
    completed_orders integer,
    cancelled_orders integer,
    by_status jsonb,
    by_fulfillment_type jsonb,
    completed_revenue jsonb
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    WITH period_orders AS (
        SELECT id, status::text AS status, fulfillment_type::text AS fulfillment_type
        FROM public.organization_customer_sale_orders
        WHERE organization_id = p_organization_id
          AND created_at >= p_start
          AND created_at < p_end
    ),
    status_keys AS (
        SELECT unnest(ARRAY[
            'pending',
            'in_progress',
            'in_delivery',
            'cancelled',
            'completed'
        ]) AS status
    ),
    fulfillment_keys AS (
        SELECT unnest(ARRAY['pickup', 'delivery', 'walk_in_offline']) AS fulfillment_type
    ),
    status_counts AS (
        SELECT
            k.status,
            COUNT(o.id)::integer AS count
        FROM status_keys AS k
        LEFT JOIN period_orders AS o
            ON o.status = k.status
        GROUP BY k.status
    ),
    fulfillment_counts AS (
        SELECT
            k.fulfillment_type,
            COUNT(o.id)::integer AS count
        FROM fulfillment_keys AS k
        LEFT JOIN period_orders AS o
            ON o.fulfillment_type = k.fulfillment_type
        GROUP BY k.fulfillment_type
    ),
    revenue AS (
        SELECT
            lower(COALESCE(l.currency_snapshot::text, o.currency::text, 'xof')) AS currency,
            COALESCE(SUM(l.quantity * l.unit_price_snapshot), 0)::numeric(14, 2) AS amount
        FROM public.organization_customer_sale_orders AS o
        INNER JOIN public.organization_customer_sale_order_lines AS l
            ON l.order_id = o.id
        WHERE o.organization_id = p_organization_id
          AND o.status::text = 'completed'
          AND o.created_at >= p_start
          AND o.created_at < p_end
        GROUP BY lower(COALESCE(l.currency_snapshot::text, o.currency::text, 'xof'))
    )
    SELECT
        (SELECT COUNT(*)::integer FROM period_orders) AS total_orders,
        (
            SELECT COUNT(*)::integer
            FROM period_orders
            WHERE status IN ('pending', 'in_progress', 'in_delivery')
        ) AS pipeline_orders,
        (
            SELECT COUNT(*)::integer
            FROM period_orders
            WHERE status = 'completed'
        ) AS completed_orders,
        (
            SELECT COUNT(*)::integer
            FROM period_orders
            WHERE status = 'cancelled'
        ) AS cancelled_orders,
        COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object('status', status, 'count', count)
                    ORDER BY array_position(
                        ARRAY['pending', 'in_progress', 'in_delivery', 'cancelled', 'completed'],
                        status
                    )
                )
                FROM status_counts
            ),
            '[]'::jsonb
        ) AS by_status,
        COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'fulfillment_type',
                        fulfillment_type,
                        'count',
                        count
                    )
                    ORDER BY array_position(
                        ARRAY['pickup', 'delivery', 'walk_in_offline'],
                        fulfillment_type
                    )
                )
                FROM fulfillment_counts
            ),
            '[]'::jsonb
        ) AS by_fulfillment_type,
        COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object('currency', currency, 'amount', amount)
                    ORDER BY currency
                )
                FROM revenue
            ),
            '[]'::jsonb
        ) AS completed_revenue;
$$;

REVOKE ALL ON FUNCTION public.get_performance_inventory_summary(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_performance_sales_status_summary(uuid, timestamptz, timestamptz) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_performance_inventory_summary(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_performance_sales_status_summary(uuid, timestamptz, timestamptz) TO service_role;
