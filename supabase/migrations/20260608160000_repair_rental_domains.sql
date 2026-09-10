-- Domaines metier MVP pour boutiques repair et rental.

DO $$
BEGIN
    CREATE TYPE public.organization_repair_status_enum AS ENUM (
        'requested',
        'received',
        'diagnosing',
        'quote_sent',
        'approved',
        'repairing',
        'ready_for_pickup',
        'delivered',
        'cancelled'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE public.organization_rental_status_enum AS ENUM (
        'reserved',
        'rented',
        'returned',
        'late',
        'maintenance',
        'cancelled'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.organization_repair_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    customer_name text,
    customer_phone text,
    item_label text NOT NULL,
    issue_description text,
    diagnostic text,
    quote_amount numeric(14, 2),
    currency text NOT NULL DEFAULT 'xof',
    status public.organization_repair_status_enum NOT NULL DEFAULT 'requested',
    assigned_member_id uuid REFERENCES public.members (id) ON DELETE SET NULL,
    notes text,
    created_by_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    received_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_repair_requests_quote_non_negative
        CHECK (quote_amount IS NULL OR quote_amount >= 0),
    CONSTRAINT organization_repair_requests_currency_check
        CHECK (
            currency = lower(currency)
            AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
        )
);

CREATE TABLE IF NOT EXISTS public.organization_rental_reservations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    rental_asset_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE RESTRICT,
    customer_name text,
    customer_phone text,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    quantity integer NOT NULL DEFAULT 1,
    daily_rate numeric(14, 2),
    deposit_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_amount numeric(14, 2) NOT NULL DEFAULT 0,
    currency text NOT NULL DEFAULT 'xof',
    status public.organization_rental_status_enum NOT NULL DEFAULT 'reserved',
    assigned_member_id uuid REFERENCES public.members (id) ON DELETE SET NULL,
    notes text,
    created_by_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    returned_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_rental_reservations_quantity_positive
        CHECK (quantity > 0),
    CONSTRAINT organization_rental_reservations_amounts_non_negative
        CHECK (
            (daily_rate IS NULL OR daily_rate >= 0)
            AND deposit_amount >= 0
            AND total_amount >= 0
        ),
    CONSTRAINT organization_rental_reservations_period_valid
        CHECK (ends_at > starts_at),
    CONSTRAINT organization_rental_reservations_currency_check
        CHECK (
            currency = lower(currency)
            AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
        )
);

CREATE TABLE IF NOT EXISTS public.organization_repair_request_parts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    repair_request_id uuid NOT NULL REFERENCES public.organization_repair_requests (id) ON DELETE CASCADE,
    resource_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE RESTRICT,
    quantity integer NOT NULL,
    unit_cost numeric(14, 2),
    total_cost numeric(14, 2) NOT NULL DEFAULT 0,
    currency text NOT NULL DEFAULT 'xof',
    note text,
    created_by_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_repair_request_parts_quantity_positive
        CHECK (quantity > 0),
    CONSTRAINT organization_repair_request_parts_amounts_non_negative
        CHECK (
            (unit_cost IS NULL OR unit_cost >= 0)
            AND total_cost >= 0
        ),
    CONSTRAINT organization_repair_request_parts_currency_check
        CHECK (
            currency = lower(currency)
            AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
        )
);

CREATE INDEX IF NOT EXISTS idx_organization_repair_requests_org_shop_status
    ON public.organization_repair_requests (organization_id, shop_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_organization_rental_reservations_org_shop_status
    ON public.organization_rental_reservations (organization_id, shop_id, status, starts_at DESC);

CREATE INDEX IF NOT EXISTS idx_organization_rental_reservations_asset_period
    ON public.organization_rental_reservations (rental_asset_id, starts_at, ends_at);

CREATE INDEX IF NOT EXISTS idx_organization_repair_request_parts_request
    ON public.organization_repair_request_parts (repair_request_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.touch_organization_repair_requests_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.touch_organization_rental_reservations_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_repair_requests_updated_at
    ON public.organization_repair_requests;
CREATE TRIGGER trg_organization_repair_requests_updated_at
    BEFORE UPDATE ON public.organization_repair_requests
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_repair_requests_updated_at();

DROP TRIGGER IF EXISTS trg_organization_rental_reservations_updated_at
    ON public.organization_rental_reservations;
CREATE TRIGGER trg_organization_rental_reservations_updated_at
    BEFORE UPDATE ON public.organization_rental_reservations
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_rental_reservations_updated_at();

CREATE OR REPLACE FUNCTION public.organization_repair_requests_check_shop()
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
       OR v_shop.shop_type <> 'repair'::public.organization_shop_type_enum
       OR v_shop.status = 'archived'::public.organization_shop_status_enum THEN
        RAISE EXCEPTION 'La demande de reparation doit appartenir a une boutique repair active de la meme organisation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_rental_reservations_check_shop_asset()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_shop public.organization_shops%ROWTYPE;
    v_article public.organization_articles%ROWTYPE;
BEGIN
    SELECT *
    INTO v_shop
    FROM public.organization_shops
    WHERE id = NEW.shop_id;

    SELECT *
    INTO v_article
    FROM public.organization_articles
    WHERE id = NEW.rental_asset_id;

    IF v_shop.id IS NULL
       OR v_shop.organization_id <> NEW.organization_id
       OR v_shop.shop_type <> 'rental'::public.organization_shop_type_enum
       OR v_shop.status = 'archived'::public.organization_shop_status_enum THEN
        RAISE EXCEPTION 'La reservation doit appartenir a une boutique rental active de la meme organisation';
    END IF;

    IF v_article.id IS NULL
       OR v_article.organization_id <> NEW.organization_id
       OR v_article.resource_scope <> 'rental_asset'::public.organization_stock_scope_enum THEN
        RAISE EXCEPTION 'Le bien loue doit etre une ressource rental_asset de la meme organisation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_repair_request_parts_check_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_repair public.organization_repair_requests%ROWTYPE;
    v_article public.organization_articles%ROWTYPE;
    v_stock public.organization_shop_article_stocks%ROWTYPE;
BEGIN
    SELECT *
    INTO v_repair
    FROM public.organization_repair_requests
    WHERE id = NEW.repair_request_id;

    SELECT *
    INTO v_article
    FROM public.organization_articles
    WHERE id = NEW.resource_id;

    SELECT *
    INTO v_stock
    FROM public.organization_shop_article_stocks
    WHERE organization_id = NEW.organization_id
      AND shop_id = NEW.shop_id
      AND article_id = NEW.resource_id
      AND stock_scope = 'repair_supply'::public.organization_stock_scope_enum;

    IF v_repair.id IS NULL
       OR v_repair.organization_id <> NEW.organization_id
       OR v_repair.shop_id <> NEW.shop_id THEN
        RAISE EXCEPTION 'La piece consommee doit appartenir a la meme demande de reparation';
    END IF;

    IF v_article.id IS NULL
       OR v_article.organization_id <> NEW.organization_id
       OR v_article.resource_scope <> 'repair_supply'::public.organization_stock_scope_enum THEN
        RAISE EXCEPTION 'La ressource consommee doit etre un repair_supply de la meme organisation';
    END IF;

    IF v_stock.id IS NULL OR v_stock.active IS NOT TRUE THEN
        RAISE EXCEPTION 'La piece de reparation est indisponible dans cette boutique';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_repair_requests_check_shop
    ON public.organization_repair_requests;
CREATE TRIGGER trg_organization_repair_requests_check_shop
    BEFORE INSERT OR UPDATE OF organization_id, shop_id
    ON public.organization_repair_requests
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_repair_requests_check_shop();

DROP TRIGGER IF EXISTS trg_organization_rental_reservations_check_shop_asset
    ON public.organization_rental_reservations;
CREATE TRIGGER trg_organization_rental_reservations_check_shop_asset
    BEFORE INSERT OR UPDATE OF organization_id, shop_id, rental_asset_id
    ON public.organization_rental_reservations
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_rental_reservations_check_shop_asset();

DROP TRIGGER IF EXISTS trg_organization_repair_request_parts_check_scope
    ON public.organization_repair_request_parts;
CREATE TRIGGER trg_organization_repair_request_parts_check_scope
    BEFORE INSERT OR UPDATE OF organization_id, shop_id, repair_request_id, resource_id
    ON public.organization_repair_request_parts
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_repair_request_parts_check_scope();

ALTER TABLE public.organization_repair_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_rental_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_repair_request_parts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_repair_requests_select_shop_member
    ON public.organization_repair_requests;
CREATE POLICY organization_repair_requests_select_shop_member
    ON public.organization_repair_requests
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

DROP POLICY IF EXISTS organization_repair_requests_manage_shop
    ON public.organization_repair_requests;
CREATE POLICY organization_repair_requests_manage_shop
    ON public.organization_repair_requests
    FOR ALL
    TO authenticated
    USING (public.can_manage_shop(shop_id))
    WITH CHECK (public.can_manage_shop(shop_id));

DROP POLICY IF EXISTS organization_rental_reservations_select_shop_member
    ON public.organization_rental_reservations;
CREATE POLICY organization_rental_reservations_select_shop_member
    ON public.organization_rental_reservations
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

DROP POLICY IF EXISTS organization_rental_reservations_manage_shop
    ON public.organization_rental_reservations;
CREATE POLICY organization_rental_reservations_manage_shop
    ON public.organization_rental_reservations
    FOR ALL
    TO authenticated
    USING (public.can_manage_shop(shop_id))
    WITH CHECK (public.can_manage_shop(shop_id));

DROP POLICY IF EXISTS organization_repair_request_parts_select_shop_member
    ON public.organization_repair_request_parts;
CREATE POLICY organization_repair_request_parts_select_shop_member
    ON public.organization_repair_request_parts
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

DROP POLICY IF EXISTS organization_repair_request_parts_manage_shop
    ON public.organization_repair_request_parts;
CREATE POLICY organization_repair_request_parts_manage_shop
    ON public.organization_repair_request_parts
    FOR ALL
    TO authenticated
    USING (public.can_manage_shop(shop_id))
    WITH CHECK (public.can_manage_shop(shop_id));

GRANT SELECT, INSERT, UPDATE ON public.organization_repair_requests TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.organization_rental_reservations TO authenticated;
GRANT SELECT, INSERT ON public.organization_repair_request_parts TO authenticated;
GRANT ALL ON public.organization_repair_requests TO service_role;
GRANT ALL ON public.organization_rental_reservations TO service_role;
GRANT ALL ON public.organization_repair_request_parts TO service_role;

COMMENT ON TABLE public.organization_repair_requests IS
    'Demandes de reparation par boutique repair. MVP workflow, diagnostic, devis, assignation.';

COMMENT ON TABLE public.organization_rental_reservations IS
    'Reservations/location de biens rental_asset par boutique rental, avec reservation de stock cote backend.';

COMMENT ON TABLE public.organization_repair_request_parts IS
    'Pieces consommables repair_supply utilisees sur une demande de reparation. Le backend decremente le stock lors de la creation.';
