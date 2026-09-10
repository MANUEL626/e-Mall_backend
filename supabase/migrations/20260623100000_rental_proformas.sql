-- Rental proformas, payments and conversion link to rental orders.

CREATE TABLE IF NOT EXISTS public.organization_rental_proformas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    proforma_number text NOT NULL UNIQUE,
    customer_name text,
    customer_phone text,
    customer_email text,
    customer_address text,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    subtotal_amount numeric(14, 2) NOT NULL DEFAULT 0,
    discount_amount numeric(14, 2) NOT NULL DEFAULT 0,
    discount_label text,
    security_deposit_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_payable_amount numeric(14, 2) NOT NULL DEFAULT 0,
    advance_required_amount numeric(14, 2) NOT NULL DEFAULT 0,
    amount_paid numeric(14, 2) NOT NULL DEFAULT 0,
    currency text NOT NULL DEFAULT 'xof',
    status text NOT NULL DEFAULT 'draft',
    payment_status text NOT NULL DEFAULT 'unpaid',
    assigned_member_id uuid REFERENCES public.members (id) ON DELETE SET NULL,
    expires_at timestamptz,
    issued_at timestamptz,
    accepted_at timestamptz,
    converted_at timestamptz,
    cancelled_at timestamptz,
    converted_rental_order_id uuid,
    notes text,
    terms text,
    organization_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    shop_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_rental_proformas_period_valid CHECK (ends_at > starts_at),
    CONSTRAINT organization_rental_proformas_amounts_valid CHECK (
        subtotal_amount >= 0
        AND discount_amount >= 0
        AND discount_amount <= subtotal_amount
        AND security_deposit_amount >= 0
        AND total_amount >= 0
        AND total_payable_amount = total_amount + security_deposit_amount
        AND advance_required_amount >= 0
        AND advance_required_amount <= total_payable_amount
        AND amount_paid >= 0
    ),
    CONSTRAINT organization_rental_proformas_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    ),
    CONSTRAINT organization_rental_proformas_status_check CHECK (
        status IN ('draft', 'issued', 'accepted', 'expired', 'cancelled', 'converted')
    ),
    CONSTRAINT organization_rental_proformas_payment_status_check CHECK (
        payment_status IN ('unpaid', 'partially_paid', 'paid', 'refunded')
    ),
    CONSTRAINT organization_rental_proformas_snapshots_check CHECK (
        jsonb_typeof(organization_snapshot) = 'object'
        AND jsonb_typeof(shop_snapshot) = 'object'
    )
);

CREATE TABLE IF NOT EXISTS public.organization_rental_proforma_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rental_proforma_id uuid NOT NULL
        REFERENCES public.organization_rental_proformas (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    rental_asset_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE RESTRICT,
    quantity integer NOT NULL,
    daily_rate numeric(14, 2) NOT NULL DEFAULT 0,
    line_subtotal numeric(14, 2) NOT NULL DEFAULT 0,
    currency text NOT NULL DEFAULT 'xof',
    asset_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_rental_proforma_lines_quantity_positive CHECK (quantity > 0),
    CONSTRAINT organization_rental_proforma_lines_amounts_non_negative CHECK (
        daily_rate >= 0 AND line_subtotal >= 0
    ),
    CONSTRAINT organization_rental_proforma_lines_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    ),
    CONSTRAINT organization_rental_proforma_lines_asset_snapshot_check CHECK (
        jsonb_typeof(asset_snapshot) = 'object'
    ),
    CONSTRAINT organization_rental_proforma_lines_unique_asset
        UNIQUE (rental_proforma_id, rental_asset_id)
);

CREATE TABLE IF NOT EXISTS public.organization_rental_proforma_payments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rental_proforma_id uuid NOT NULL
        REFERENCES public.organization_rental_proformas (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    amount numeric(14, 2) NOT NULL,
    currency text NOT NULL,
    payment_method text NOT NULL,
    payment_reference text,
    idempotency_key text,
    status text NOT NULL DEFAULT 'confirmed',
    paid_at timestamptz NOT NULL DEFAULT now(),
    note text,
    created_by_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_rental_proforma_payments_amount_positive CHECK (amount > 0),
    CONSTRAINT organization_rental_proforma_payments_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    ),
    CONSTRAINT organization_rental_proforma_payments_status_check CHECK (
        status IN ('confirmed', 'refunded')
    )
);

ALTER TABLE public.organization_rental_orders
    ADD COLUMN IF NOT EXISTS source_proforma_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'organization_rental_orders_source_proforma_fkey'
    ) THEN
        ALTER TABLE public.organization_rental_orders
            ADD CONSTRAINT organization_rental_orders_source_proforma_fkey
            FOREIGN KEY (source_proforma_id)
            REFERENCES public.organization_rental_proformas (id) ON DELETE SET NULL;
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_rental_orders_source_proforma
    ON public.organization_rental_orders (source_proforma_id)
    WHERE source_proforma_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'organization_rental_proformas_converted_order_fkey'
    ) THEN
        ALTER TABLE public.organization_rental_proformas
            ADD CONSTRAINT organization_rental_proformas_converted_order_fkey
            FOREIGN KEY (converted_rental_order_id)
            REFERENCES public.organization_rental_orders (id) ON DELETE SET NULL;
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_rental_proformas_converted_order
    ON public.organization_rental_proformas (converted_rental_order_id)
    WHERE converted_rental_order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_rental_proforma_payment_idempotency
    ON public.organization_rental_proforma_payments (organization_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_rental_proformas_org_shop_status
    ON public.organization_rental_proformas (organization_id, shop_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rental_proforma_lines_proforma
    ON public.organization_rental_proforma_lines (rental_proforma_id, created_at);

CREATE INDEX IF NOT EXISTS idx_rental_proforma_payments_proforma
    ON public.organization_rental_proforma_payments (rental_proforma_id, paid_at);

CREATE OR REPLACE FUNCTION public.touch_organization_rental_proformas_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_rental_proformas_updated_at
    ON public.organization_rental_proformas;
CREATE TRIGGER trg_organization_rental_proformas_updated_at
    BEFORE UPDATE ON public.organization_rental_proformas
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_rental_proformas_updated_at();

CREATE OR REPLACE FUNCTION public.organization_rental_proformas_check_shop()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_shop public.organization_shops%ROWTYPE;
BEGIN
    SELECT * INTO v_shop
    FROM public.organization_shops
    WHERE id = NEW.shop_id;

    IF v_shop.id IS NULL
       OR v_shop.organization_id <> NEW.organization_id
       OR v_shop.shop_type <> 'rental'::public.organization_shop_type_enum
       OR v_shop.status = 'archived'::public.organization_shop_status_enum THEN
        RAISE EXCEPTION 'La proforma doit appartenir a une boutique rental active de la meme organisation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_rental_proforma_lines_check_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_proforma public.organization_rental_proformas%ROWTYPE;
    v_article public.organization_articles%ROWTYPE;
BEGIN
    SELECT * INTO v_proforma
    FROM public.organization_rental_proformas
    WHERE id = NEW.rental_proforma_id;

    IF v_proforma.id IS NULL
       OR v_proforma.organization_id <> NEW.organization_id
       OR v_proforma.shop_id <> NEW.shop_id THEN
        RAISE EXCEPTION 'La ligne doit appartenir a la meme proforma de location';
    END IF;

    SELECT * INTO v_article
    FROM public.organization_articles
    WHERE id = NEW.rental_asset_id;

    IF v_article.id IS NULL
       OR v_article.organization_id <> NEW.organization_id
       OR v_article.resource_scope <> 'rental_asset'::public.organization_stock_scope_enum THEN
        RAISE EXCEPTION 'La ligne proforma doit utiliser un actif rental_asset de la meme organisation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_rental_proforma_payments_check_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_proforma public.organization_rental_proformas%ROWTYPE;
    v_confirmed_amount numeric(14, 2);
BEGIN
    SELECT * INTO v_proforma
    FROM public.organization_rental_proformas
    WHERE id = NEW.rental_proforma_id
    FOR UPDATE;

    IF v_proforma.id IS NULL
       OR v_proforma.organization_id <> NEW.organization_id
       OR v_proforma.shop_id <> NEW.shop_id
       OR v_proforma.currency <> NEW.currency THEN
        RAISE EXCEPTION 'Le paiement doit correspondre a la proforma, sa boutique et sa devise';
    END IF;

    IF v_proforma.status NOT IN ('issued', 'accepted')
       OR (v_proforma.expires_at IS NOT NULL AND v_proforma.expires_at < now()) THEN
        RAISE EXCEPTION 'La proforma doit etre emise, valide et non expiree pour recevoir un paiement';
    END IF;

    SELECT COALESCE(sum(amount), 0)
    INTO v_confirmed_amount
    FROM public.organization_rental_proforma_payments
    WHERE rental_proforma_id = NEW.rental_proforma_id
      AND status = 'confirmed';

    IF NEW.status = 'confirmed'
       AND v_confirmed_amount + NEW.amount > v_proforma.total_payable_amount THEN
        RAISE EXCEPTION 'Le paiement depasse le solde restant de la proforma';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_rental_proformas_check_shop
    ON public.organization_rental_proformas;
CREATE TRIGGER trg_organization_rental_proformas_check_shop
    BEFORE INSERT OR UPDATE OF organization_id, shop_id
    ON public.organization_rental_proformas
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_rental_proformas_check_shop();

DROP TRIGGER IF EXISTS trg_organization_rental_proforma_lines_check_scope
    ON public.organization_rental_proforma_lines;
CREATE TRIGGER trg_organization_rental_proforma_lines_check_scope
    BEFORE INSERT OR UPDATE OF rental_proforma_id, organization_id, shop_id, rental_asset_id
    ON public.organization_rental_proforma_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_rental_proforma_lines_check_scope();

DROP TRIGGER IF EXISTS trg_organization_rental_proforma_payments_check_scope
    ON public.organization_rental_proforma_payments;
CREATE TRIGGER trg_organization_rental_proforma_payments_check_scope
    BEFORE INSERT OR UPDATE OF rental_proforma_id, organization_id, shop_id, currency
    ON public.organization_rental_proforma_payments
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_rental_proforma_payments_check_scope();

CREATE OR REPLACE FUNCTION public.organization_rental_orders_check_source_proforma()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_proforma public.organization_rental_proformas%ROWTYPE;
BEGIN
    IF NEW.source_proforma_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO v_proforma
    FROM public.organization_rental_proformas
    WHERE id = NEW.source_proforma_id;

    IF v_proforma.id IS NULL
       OR v_proforma.organization_id <> NEW.organization_id
       OR v_proforma.shop_id <> NEW.shop_id
       OR v_proforma.status NOT IN ('issued', 'accepted', 'converted') THEN
        RAISE EXCEPTION 'La location source doit correspondre a une proforma valide de la meme boutique';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_rental_orders_check_source_proforma
    ON public.organization_rental_orders;
CREATE TRIGGER trg_organization_rental_orders_check_source_proforma
    BEFORE INSERT OR UPDATE OF source_proforma_id, organization_id, shop_id
    ON public.organization_rental_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_rental_orders_check_source_proforma();

ALTER TABLE public.organization_rental_proformas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_rental_proforma_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_rental_proforma_payments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_rental_proformas_select_shop_member
    ON public.organization_rental_proformas;
CREATE POLICY organization_rental_proformas_select_shop_member
    ON public.organization_rental_proformas FOR SELECT TO authenticated
    USING (public.is_shop_member(shop_id));
DROP POLICY IF EXISTS organization_rental_proformas_manage_shop
    ON public.organization_rental_proformas;
CREATE POLICY organization_rental_proformas_manage_shop
    ON public.organization_rental_proformas FOR ALL TO authenticated
    USING (public.can_manage_shop(shop_id)) WITH CHECK (public.can_manage_shop(shop_id));

DROP POLICY IF EXISTS organization_rental_proforma_lines_select_shop_member
    ON public.organization_rental_proforma_lines;
CREATE POLICY organization_rental_proforma_lines_select_shop_member
    ON public.organization_rental_proforma_lines FOR SELECT TO authenticated
    USING (public.is_shop_member(shop_id));
DROP POLICY IF EXISTS organization_rental_proforma_lines_manage_shop
    ON public.organization_rental_proforma_lines;
CREATE POLICY organization_rental_proforma_lines_manage_shop
    ON public.organization_rental_proforma_lines FOR ALL TO authenticated
    USING (public.can_manage_shop(shop_id)) WITH CHECK (public.can_manage_shop(shop_id));

DROP POLICY IF EXISTS organization_rental_proforma_payments_select_shop_member
    ON public.organization_rental_proforma_payments;
CREATE POLICY organization_rental_proforma_payments_select_shop_member
    ON public.organization_rental_proforma_payments FOR SELECT TO authenticated
    USING (public.is_shop_member(shop_id));
DROP POLICY IF EXISTS organization_rental_proforma_payments_manage_shop
    ON public.organization_rental_proforma_payments;
CREATE POLICY organization_rental_proforma_payments_manage_shop
    ON public.organization_rental_proforma_payments FOR ALL TO authenticated
    USING (public.can_manage_shop(shop_id)) WITH CHECK (public.can_manage_shop(shop_id));

GRANT SELECT, INSERT, UPDATE ON public.organization_rental_proformas TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.organization_rental_proforma_lines TO authenticated;
GRANT SELECT, INSERT ON public.organization_rental_proforma_payments TO authenticated;
GRANT ALL ON public.organization_rental_proformas TO service_role;
GRANT ALL ON public.organization_rental_proforma_lines TO service_role;
GRANT ALL ON public.organization_rental_proforma_payments TO service_role;

COMMENT ON TABLE public.organization_rental_proformas IS
    'Rental proformas created before a rental order. Issued documents are immutable and can be converted once.';
COMMENT ON COLUMN public.organization_rental_proformas.security_deposit_amount IS
    'Refundable security deposit, kept separate from rental revenue.';
COMMENT ON COLUMN public.organization_rental_proformas.advance_required_amount IS
    'Minimum confirmed payment required before conversion into a rental order.';
