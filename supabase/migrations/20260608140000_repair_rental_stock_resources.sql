-- Ressources de stock dediees aux boutiques repair/rental.
-- On garde organization_articles comme catalogue technique commun, mais on
-- distingue les ressources avec resource_scope pour ne pas les exposer comme
-- articles de vente.

ALTER TABLE public.organization_articles
    ADD COLUMN IF NOT EXISTS resource_scope public.organization_stock_scope_enum
    NOT NULL DEFAULT 'sales_item';

ALTER TABLE public.organization_articles
    ALTER COLUMN primary_image_storage_path DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_organization_articles_org_resource_scope
    ON public.organization_articles (organization_id, resource_scope, active);

CREATE OR REPLACE FUNCTION public.create_sales_stock_rows_for_article()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.resource_scope <> 'sales_item'::public.organization_stock_scope_enum THEN
        RETURN NEW;
    END IF;

    INSERT INTO public.organization_shop_article_stocks (
        organization_id,
        shop_id,
        article_id,
        stock_scope,
        stock_quantity,
        reserved_quantity,
        alert_quantity,
        active
    )
    SELECT
        NEW.organization_id,
        s.id,
        NEW.id,
        'sales_item'::public.organization_stock_scope_enum,
        CASE WHEN s.is_default IS TRUE THEN NEW.stock_quantity ELSE 0 END,
        CASE WHEN s.is_default IS TRUE THEN COALESCE(NEW.reserved_quantity, 0) ELSE 0 END,
        NEW.alert_quantity,
        NEW.active
    FROM public.organization_shops s
    WHERE s.organization_id = NEW.organization_id
      AND s.shop_type = 'sales'::public.organization_shop_type_enum
      AND s.status <> 'archived'::public.organization_shop_status_enum
    ON CONFLICT (shop_id, article_id) DO NOTHING;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_sales_stock_rows_for_shop()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.shop_type = 'sales'::public.organization_shop_type_enum THEN
        INSERT INTO public.organization_shop_article_stocks (
            organization_id,
            shop_id,
            article_id,
            stock_scope,
            stock_quantity,
            reserved_quantity,
            alert_quantity,
            active
        )
        SELECT
            NEW.organization_id,
            NEW.id,
            a.id,
            'sales_item'::public.organization_stock_scope_enum,
            0,
            0,
            a.alert_quantity,
            a.active
        FROM public.organization_articles a
        WHERE a.organization_id = NEW.organization_id
          AND a.resource_scope = 'sales_item'::public.organization_stock_scope_enum
        ON CONFLICT (shop_id, article_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON COLUMN public.organization_articles.resource_scope IS
    'Famille de ressource: sales_item, repair_supply, repair_tool ou rental_asset. Les ressources non sales_item ne sont pas exposees dans le catalogue client.';
