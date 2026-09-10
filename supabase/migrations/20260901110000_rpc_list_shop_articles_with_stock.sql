-- Liste optimisee articles + stock boutique en un seul appel SQL.
-- Objectif: eviter les allers-retours FastAPI -> Supabase pour verifier
-- membre, verifier boutique, lire articles, puis lire stock.

CREATE OR REPLACE FUNCTION public.list_shop_articles_with_stock(
    p_user_id uuid,
    p_organization_id uuid,
    p_shop_id uuid,
    p_active_only boolean DEFAULT NULL,
    p_limit integer DEFAULT 50,
    p_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    organization_id uuid,
    name text,
    category text,
    unit_sale_price numeric,
    sale_currency text,
    wholesale_prices jsonb,
    stock_quantity integer,
    alert_quantity integer,
    stock_status text,
    shop_id uuid,
    reserved_quantity integer,
    stock_scope text,
    description text,
    primary_image_storage_path text,
    additional_image_storage_paths text[],
    active boolean,
    created_at timestamptz,
    updated_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_limit integer := GREATEST(1, LEAST(COALESCE(p_limit, 50), 200));
    v_offset integer := GREATEST(0, COALESCE(p_offset, 0));
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.members m
        WHERE m.user_id = p_user_id
          AND m.organization_id = p_organization_id
          AND m.activity_status = true
    ) THEN
        RAISE EXCEPTION 'Acces refuse : vous n''etes pas membre actif de cette organisation';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.organization_shops s
        WHERE s.id = p_shop_id
          AND s.organization_id = p_organization_id
          AND s.shop_type = 'sales'::public.organization_shop_type_enum
          AND s.status <> 'archived'::public.organization_shop_status_enum
    ) THEN
        RAISE EXCEPTION 'Boutique de vente introuvable pour cette organisation';
    END IF;

    RETURN QUERY
    SELECT
        a.id,
        a.organization_id,
        a.name,
        a.category::text,
        a.unit_sale_price,
        a.sale_currency,
        a.wholesale_prices,
        COALESCE(st.stock_quantity, 0)::integer AS stock_quantity,
        COALESCE(st.alert_quantity, 0)::integer AS alert_quantity,
        COALESCE(st.stock_status, 'out_of_stock'::public.article_stock_status_enum)::text AS stock_status,
        p_shop_id AS shop_id,
        COALESCE(st.reserved_quantity, 0)::integer AS reserved_quantity,
        COALESCE(st.stock_scope, 'sales_item'::public.organization_stock_scope_enum)::text AS stock_scope,
        a.description,
        a.primary_image_storage_path,
        a.additional_image_storage_paths,
        a.active,
        a.created_at,
        a.updated_at
    FROM public.organization_articles a
    LEFT JOIN public.organization_shop_article_stocks st
      ON st.article_id = a.id
     AND st.organization_id = a.organization_id
     AND st.shop_id = p_shop_id
     AND st.stock_scope = 'sales_item'::public.organization_stock_scope_enum
    WHERE a.organization_id = p_organization_id
      AND a.resource_scope = 'sales_item'::public.organization_stock_scope_enum
      AND (p_active_only IS NULL OR a.active = p_active_only)
    ORDER BY a.created_at DESC
    LIMIT v_limit
    OFFSET v_offset;
END;
$$;
