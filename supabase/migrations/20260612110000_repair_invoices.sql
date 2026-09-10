-- Factures/reçus de réparation émis à la fin du workflow atelier.

CREATE TABLE IF NOT EXISTS public.organization_repair_invoices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repair_request_id uuid NOT NULL UNIQUE
        REFERENCES public.organization_repair_requests (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL
        REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL
        REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    invoice_number text NOT NULL UNIQUE,
    currency text NOT NULL DEFAULT 'xof',
    labor_amount numeric(14, 2) NOT NULL DEFAULT 0,
    parts_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_parts integer NOT NULL DEFAULT 0,
    total_lines integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'issued',
    customer_label text,
    organization_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    shop_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    repair_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    parts_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
    issued_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_repair_invoices_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    ),
    CONSTRAINT organization_repair_invoices_status_check CHECK (
        status IN ('issued', 'void')
    ),
    CONSTRAINT organization_repair_invoices_amounts_nonneg CHECK (
        labor_amount >= 0
        AND parts_amount >= 0
        AND total_amount >= 0
        AND total_parts >= 0
        AND total_lines >= 0
    ),
    CONSTRAINT organization_repair_invoices_snapshots_check CHECK (
        jsonb_typeof(organization_snapshot) = 'object'
        AND jsonb_typeof(shop_snapshot) = 'object'
        AND jsonb_typeof(repair_snapshot) = 'object'
        AND jsonb_typeof(parts_snapshot) = 'array'
    )
);

CREATE INDEX IF NOT EXISTS idx_organization_repair_invoices_org_shop_issued_at
    ON public.organization_repair_invoices (organization_id, shop_id, issued_at DESC);

CREATE OR REPLACE FUNCTION public.touch_organization_repair_invoices_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_repair_invoices_updated_at
    ON public.organization_repair_invoices;
CREATE TRIGGER trg_organization_repair_invoices_updated_at
    BEFORE UPDATE ON public.organization_repair_invoices
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_repair_invoices_updated_at();

ALTER TABLE public.organization_repair_invoices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_repair_invoices_select_shop_member
    ON public.organization_repair_invoices;
CREATE POLICY organization_repair_invoices_select_shop_member
    ON public.organization_repair_invoices
    FOR SELECT
    TO authenticated
    USING (public.is_shop_member(shop_id));

GRANT SELECT ON public.organization_repair_invoices TO authenticated;
GRANT ALL ON public.organization_repair_invoices TO service_role;

COMMENT ON TABLE public.organization_repair_invoices IS
    'Factures/reçus de réparation émis lorsque la réparation est livrée. Snapshot immuable pour affichage, impression et export.';

COMMENT ON COLUMN public.organization_repair_invoices.invoice_number IS
    'Identifiant lisible de la facture réparation, dérivé de la date et de la demande.';

COMMENT ON COLUMN public.organization_repair_invoices.parts_snapshot IS
    'Copie JSON des consommables utilisés : ressource, quantité, coût unitaire, devise et total ligne.';
