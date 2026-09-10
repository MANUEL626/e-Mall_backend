-- Locations par lot : un ordre de location peut contenir plusieurs actifs louables.

CREATE TABLE IF NOT EXISTS public.organization_rental_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    customer_name text,
    customer_phone text,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    deposit_amount numeric(14, 2) NOT NULL DEFAULT 0,
    subtotal_amount numeric(14, 2) NOT NULL DEFAULT 0,
    discount_amount numeric(14, 2) NOT NULL DEFAULT 0,
    discount_label text,
    total_amount numeric(14, 2) NOT NULL DEFAULT 0,
    currency text NOT NULL DEFAULT 'xof',
    status public.organization_rental_status_enum NOT NULL DEFAULT 'reserved',
    assigned_member_id uuid REFERENCES public.members (id) ON DELETE SET NULL,
    notes text,
    created_by_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    returned_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_rental_orders_period_valid CHECK (ends_at > starts_at),
    CONSTRAINT organization_rental_orders_amounts_non_negative CHECK (
        deposit_amount >= 0
        AND subtotal_amount >= 0
        AND discount_amount >= 0
        AND total_amount >= 0
        AND discount_amount <= subtotal_amount
    ),
    CONSTRAINT organization_rental_orders_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    )
);

CREATE TABLE IF NOT EXISTS public.organization_rental_order_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rental_order_id uuid NOT NULL
        REFERENCES public.organization_rental_orders (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    rental_asset_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE RESTRICT,
    quantity integer NOT NULL,
    daily_rate numeric(14, 2),
    line_subtotal numeric(14, 2) NOT NULL DEFAULT 0,
    currency text NOT NULL DEFAULT 'xof',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_rental_order_lines_quantity_positive CHECK (quantity > 0),
    CONSTRAINT organization_rental_order_lines_amounts_non_negative CHECK (
        (daily_rate IS NULL OR daily_rate >= 0)
        AND line_subtotal >= 0
    ),
    CONSTRAINT organization_rental_order_lines_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    ),
    CONSTRAINT organization_rental_order_lines_unique_asset
        UNIQUE (rental_order_id, rental_asset_id)
);

CREATE INDEX IF NOT EXISTS idx_organization_rental_orders_org_shop_status
    ON public.organization_rental_orders (organization_id, shop_id, status, starts_at DESC);

CREATE INDEX IF NOT EXISTS idx_organization_rental_order_lines_order
    ON public.organization_rental_order_lines (rental_order_id, created_at);

CREATE INDEX IF NOT EXISTS idx_organization_rental_order_lines_asset
    ON public.organization_rental_order_lines (rental_asset_id);

CREATE OR REPLACE FUNCTION public.touch_organization_rental_orders_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_rental_orders_updated_at
    ON public.organization_rental_orders;
CREATE TRIGGER trg_organization_rental_orders_updated_at
    BEFORE UPDATE ON public.organization_rental_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_rental_orders_updated_at();

CREATE OR REPLACE FUNCTION public.organization_rental_orders_check_shop()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_shop public.organization_shops%ROWTYPE;
BEGIN
    SELECT *
    INTO v_shop
    FROM public.organization_shops
    WHERE id = NEW.shop_id;

    IF v_shop.id IS NULL
       OR v_shop.organization_id <> NEW.organization_id
       OR v_shop.shop_type <> 'rental'::public.organization_shop_type_enum
       OR v_shop.status = 'archived'::public.organization_shop_status_enum THEN
        RAISE EXCEPTION 'La location doit appartenir a une boutique rental active de la meme organisation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_rental_order_lines_check_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_order public.organization_rental_orders%ROWTYPE;
    v_article public.organization_articles%ROWTYPE;
BEGIN
    SELECT *
    INTO v_order
    FROM public.organization_rental_orders
    WHERE id = NEW.rental_order_id;

    IF v_order.id IS NULL
       OR v_order.organization_id <> NEW.organization_id
       OR v_order.shop_id <> NEW.shop_id THEN
        RAISE EXCEPTION 'La ligne doit appartenir au meme ordre de location';
    END IF;

    SELECT *
    INTO v_article
    FROM public.organization_articles
    WHERE id = NEW.rental_asset_id;

    IF v_article.id IS NULL
       OR v_article.organization_id <> NEW.organization_id
       OR v_article.resource_scope <> 'rental_asset'::public.organization_stock_scope_enum THEN
        RAISE EXCEPTION 'Le bien loue doit etre une ressource rental_asset de la meme organisation';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_rental_orders_check_shop
    ON public.organization_rental_orders;
CREATE TRIGGER trg_organization_rental_orders_check_shop
    BEFORE INSERT OR UPDATE OF organization_id, shop_id
    ON public.organization_rental_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_rental_orders_check_shop();

DROP TRIGGER IF EXISTS trg_organization_rental_order_lines_check_scope
    ON public.organization_rental_order_lines;
CREATE TRIGGER trg_organization_rental_order_lines_check_scope
    BEFORE INSERT OR UPDATE OF rental_order_id, organization_id, shop_id, rental_asset_id
    ON public.organization_rental_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_rental_order_lines_check_scope();

ALTER TABLE public.organization_rental_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_rental_order_lines ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_rental_orders_select_shop_member
    ON public.organization_rental_orders;
CREATE POLICY organization_rental_orders_select_shop_member
    ON public.organization_rental_orders
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

DROP POLICY IF EXISTS organization_rental_orders_manage_shop
    ON public.organization_rental_orders;
CREATE POLICY organization_rental_orders_manage_shop
    ON public.organization_rental_orders
    FOR ALL
    TO authenticated
    USING (public.can_manage_shop(shop_id))
    WITH CHECK (public.can_manage_shop(shop_id));

DROP POLICY IF EXISTS organization_rental_order_lines_select_shop_member
    ON public.organization_rental_order_lines;
CREATE POLICY organization_rental_order_lines_select_shop_member
    ON public.organization_rental_order_lines
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

DROP POLICY IF EXISTS organization_rental_order_lines_manage_shop
    ON public.organization_rental_order_lines;
CREATE POLICY organization_rental_order_lines_manage_shop
    ON public.organization_rental_order_lines
    FOR ALL
    TO authenticated
    USING (public.can_manage_shop(shop_id))
    WITH CHECK (public.can_manage_shop(shop_id));

GRANT SELECT, INSERT, UPDATE ON public.organization_rental_orders TO authenticated;
GRANT SELECT, INSERT ON public.organization_rental_order_lines TO authenticated;
GRANT ALL ON public.organization_rental_orders TO service_role;
GRANT ALL ON public.organization_rental_order_lines TO service_role;

COMMENT ON TABLE public.organization_rental_orders IS
    'Ordres de location multi-actifs. Un ordre porte le client, la periode, la remise globale et les totaux.';

COMMENT ON TABLE public.organization_rental_order_lines IS
    'Lignes d''un ordre de location : actif louable, quantite, prix journalier et sous-total.';

