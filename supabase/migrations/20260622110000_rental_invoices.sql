-- Rental invoices/receipts generated when a rental order is returned.

CREATE TABLE IF NOT EXISTS public.organization_rental_invoices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rental_order_id uuid NOT NULL UNIQUE
        REFERENCES public.organization_rental_orders (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL
        REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL
        REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    invoice_number text NOT NULL UNIQUE,
    currency text NOT NULL DEFAULT 'xof',
    subtotal_amount numeric(14, 2) NOT NULL DEFAULT 0,
    discount_amount numeric(14, 2) NOT NULL DEFAULT 0,
    deposit_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_items integer NOT NULL DEFAULT 0,
    total_lines integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'issued',
    customer_label text,
    organization_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    shop_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    rental_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    lines_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
    issued_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_rental_invoices_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    ),
    CONSTRAINT organization_rental_invoices_status_check CHECK (
        status IN ('issued', 'void')
    ),
    CONSTRAINT organization_rental_invoices_amounts_nonneg CHECK (
        subtotal_amount >= 0
        AND discount_amount >= 0
        AND deposit_amount >= 0
        AND total_amount >= 0
        AND total_items >= 0
        AND total_lines >= 0
    ),
    CONSTRAINT organization_rental_invoices_snapshots_check CHECK (
        jsonb_typeof(organization_snapshot) = 'object'
        AND jsonb_typeof(shop_snapshot) = 'object'
        AND jsonb_typeof(rental_snapshot) = 'object'
        AND jsonb_typeof(lines_snapshot) = 'array'
    )
);

CREATE INDEX IF NOT EXISTS idx_organization_rental_invoices_org_shop_issued_at
    ON public.organization_rental_invoices (organization_id, shop_id, issued_at DESC);

CREATE OR REPLACE FUNCTION public.touch_organization_rental_invoices_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_rental_invoices_updated_at
    ON public.organization_rental_invoices;
CREATE TRIGGER trg_organization_rental_invoices_updated_at
    BEFORE UPDATE ON public.organization_rental_invoices
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_rental_invoices_updated_at();

ALTER TABLE public.organization_rental_invoices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_rental_invoices_select_shop_member
    ON public.organization_rental_invoices;
CREATE POLICY organization_rental_invoices_select_shop_member
    ON public.organization_rental_invoices
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

GRANT SELECT ON public.organization_rental_invoices TO authenticated;
GRANT ALL ON public.organization_rental_invoices TO service_role;

COMMENT ON TABLE public.organization_rental_invoices IS
    'Rental invoices/receipts generated when a rental order is returned. Immutable snapshot for display, print and export.';

COMMENT ON COLUMN public.organization_rental_invoices.lines_snapshot IS
    'JSON copy of rented assets: asset, media paths, quantity, daily rate, currency and line total.';
