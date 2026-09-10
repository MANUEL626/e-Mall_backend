-- Stock par boutique pour les articles de vente.
-- Cette phase garde les colonnes legacy de organization_articles pour compatibilite.

DO $$
BEGIN
    CREATE TYPE public.organization_stock_scope_enum AS ENUM (
        'sales_item',
        'repair_supply',
        'repair_tool',
        'rental_asset'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.organization_shop_article_stocks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    article_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE CASCADE,
    stock_scope public.organization_stock_scope_enum NOT NULL DEFAULT 'sales_item',
    stock_quantity integer NOT NULL DEFAULT 0,
    reserved_quantity integer NOT NULL DEFAULT 0,
    alert_quantity integer NOT NULL DEFAULT 0,
    stock_status public.article_stock_status_enum NOT NULL DEFAULT 'out_of_stock',
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_org_shop_article_stocks_shop_article UNIQUE (shop_id, article_id),
    CONSTRAINT org_shop_article_stocks_stock_nonneg CHECK (stock_quantity >= 0),
    CONSTRAINT org_shop_article_stocks_reserved_nonneg CHECK (reserved_quantity >= 0),
    CONSTRAINT org_shop_article_stocks_alert_nonneg CHECK (alert_quantity >= 0),
    CONSTRAINT org_shop_article_stocks_stock_covers_reserved CHECK (
        stock_quantity >= reserved_quantity
    )
);

CREATE INDEX IF NOT EXISTS idx_org_shop_article_stocks_org_shop
    ON public.organization_shop_article_stocks (organization_id, shop_id);

CREATE INDEX IF NOT EXISTS idx_org_shop_article_stocks_article
    ON public.organization_shop_article_stocks (article_id);

CREATE INDEX IF NOT EXISTS idx_org_shop_article_stocks_shop_status
    ON public.organization_shop_article_stocks (shop_id, stock_status);

CREATE OR REPLACE FUNCTION public.touch_org_shop_article_stocks_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.org_shop_article_stocks_set_stock_status()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.stock_quantity <= 0 THEN
        NEW.stock_status := 'out_of_stock'::public.article_stock_status_enum;
    ELSIF NEW.stock_quantity <= NEW.alert_quantity THEN
        NEW.stock_status := 'low_stock'::public.article_stock_status_enum;
    ELSE
        NEW.stock_status := 'in_stock'::public.article_stock_status_enum;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.org_shop_article_stocks_check_same_org_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_shop_org uuid;
    v_shop_type public.organization_shop_type_enum;
    v_article_org uuid;
BEGIN
    SELECT organization_id, shop_type
    INTO v_shop_org, v_shop_type
    FROM public.organization_shops
    WHERE id = NEW.shop_id;

    SELECT organization_id
    INTO v_article_org
    FROM public.organization_articles
    WHERE id = NEW.article_id;

    IF v_shop_org IS NULL OR v_article_org IS NULL OR v_shop_org <> v_article_org THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'La boutique et l article doivent appartenir a la meme organisation';
    END IF;

    IF v_shop_type = 'sales'::public.organization_shop_type_enum
       AND NEW.stock_scope <> 'sales_item'::public.organization_stock_scope_enum THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'Une boutique de vente accepte uniquement le stock sales_item';
    END IF;

    IF v_shop_type = 'repair'::public.organization_shop_type_enum
       AND NEW.stock_scope NOT IN (
           'repair_supply'::public.organization_stock_scope_enum,
           'repair_tool'::public.organization_stock_scope_enum
       ) THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'Une boutique de reparation accepte uniquement repair_supply ou repair_tool';
    END IF;

    IF v_shop_type = 'rental'::public.organization_shop_type_enum
       AND NEW.stock_scope <> 'rental_asset'::public.organization_stock_scope_enum THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'Une boutique de location accepte uniquement rental_asset';
    END IF;

    IF v_shop_type = 'delivery'::public.organization_shop_type_enum THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'Une boutique livraison ne gere pas de stock dans cette phase';
    END IF;

    NEW.organization_id := v_shop_org;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_org_shop_article_stocks_same_org_scope
    ON public.organization_shop_article_stocks;
CREATE TRIGGER trg_org_shop_article_stocks_same_org_scope
    BEFORE INSERT OR UPDATE OF shop_id, article_id, stock_scope
    ON public.organization_shop_article_stocks
    FOR EACH ROW
    EXECUTE FUNCTION public.org_shop_article_stocks_check_same_org_scope();

DROP TRIGGER IF EXISTS trg_org_shop_article_stocks_status
    ON public.organization_shop_article_stocks;
CREATE TRIGGER trg_org_shop_article_stocks_status
    BEFORE INSERT OR UPDATE OF stock_quantity, alert_quantity
    ON public.organization_shop_article_stocks
    FOR EACH ROW
    EXECUTE FUNCTION public.org_shop_article_stocks_set_stock_status();

DROP TRIGGER IF EXISTS trg_org_shop_article_stocks_updated_at
    ON public.organization_shop_article_stocks;
CREATE TRIGGER trg_org_shop_article_stocks_updated_at
    BEFORE UPDATE ON public.organization_shop_article_stocks
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_org_shop_article_stocks_updated_at();

CREATE OR REPLACE FUNCTION public.create_sales_stock_rows_for_article()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
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

DROP TRIGGER IF EXISTS trg_create_sales_stock_rows_for_article
    ON public.organization_articles;
CREATE TRIGGER trg_create_sales_stock_rows_for_article
    AFTER INSERT ON public.organization_articles
    FOR EACH ROW
    EXECUTE FUNCTION public.create_sales_stock_rows_for_article();

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
        ON CONFLICT (shop_id, article_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_create_sales_stock_rows_for_shop
    ON public.organization_shops;
CREATE TRIGGER trg_create_sales_stock_rows_for_shop
    AFTER INSERT ON public.organization_shops
    FOR EACH ROW
    EXECUTE FUNCTION public.create_sales_stock_rows_for_shop();

-- Backfill : articles existants vers toutes les boutiques sales.
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
    a.organization_id,
    s.id,
    a.id,
    'sales_item'::public.organization_stock_scope_enum,
    CASE WHEN s.is_default IS TRUE THEN a.stock_quantity ELSE 0 END,
    CASE WHEN s.is_default IS TRUE THEN COALESCE(a.reserved_quantity, 0) ELSE 0 END,
    a.alert_quantity,
    a.active
FROM public.organization_articles a
INNER JOIN public.organization_shops s
    ON s.organization_id = a.organization_id
   AND s.shop_type = 'sales'::public.organization_shop_type_enum
   AND s.status <> 'archived'::public.organization_shop_status_enum
ON CONFLICT (shop_id, article_id) DO NOTHING;

ALTER TABLE public.organization_shop_article_stocks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS org_shop_article_stocks_select_shop_member
    ON public.organization_shop_article_stocks;
CREATE POLICY org_shop_article_stocks_select_shop_member
    ON public.organization_shop_article_stocks
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

DROP POLICY IF EXISTS org_shop_article_stocks_insert_shop_manager
    ON public.organization_shop_article_stocks;
CREATE POLICY org_shop_article_stocks_insert_shop_manager
    ON public.organization_shop_article_stocks
    FOR INSERT
    TO authenticated
    WITH CHECK (public.can_manage_shop(shop_id));

DROP POLICY IF EXISTS org_shop_article_stocks_update_shop_manager
    ON public.organization_shop_article_stocks;
CREATE POLICY org_shop_article_stocks_update_shop_manager
    ON public.organization_shop_article_stocks
    FOR UPDATE
    TO authenticated
    USING (public.can_manage_shop(shop_id))
    WITH CHECK (public.can_manage_shop(shop_id));

GRANT SELECT, INSERT, UPDATE ON public.organization_shop_article_stocks TO authenticated;
GRANT ALL ON public.organization_shop_article_stocks TO service_role;

COMMENT ON TABLE public.organization_shop_article_stocks IS
    'Stock par boutique. Phase actuelle : sales_item pour articles de vente, avec scopes reserves pour repair/rental.';
