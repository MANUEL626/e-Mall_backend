-- Recus de vente client : ticket marchand/customer emis apres finalisation.
-- A ne pas confondre avec customer_sale_order_receipt_tokens, qui sert au QR.

CREATE TABLE IF NOT EXISTS public.customer_sale_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE
        REFERENCES public.organization_customer_sale_orders (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL
        REFERENCES public.organizations (id) ON DELETE CASCADE,
    customer_id uuid
        REFERENCES public.customers (id) ON DELETE SET NULL,
    receipt_number text NOT NULL UNIQUE,
    currency text NOT NULL DEFAULT 'xof',
    subtotal_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_amount numeric(14, 2) NOT NULL DEFAULT 0,
    total_items integer NOT NULL DEFAULT 0,
    total_lines integer NOT NULL DEFAULT 0,
    fulfillment_type public.customer_sale_fulfillment_enum NOT NULL,
    status text NOT NULL DEFAULT 'issued',
    customer_label text,
    organization_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    customer_snapshot jsonb,
    lines_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
    issued_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT customer_sale_receipts_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    ),
    CONSTRAINT customer_sale_receipts_status_check CHECK (
        status IN ('issued', 'void')
    ),
    CONSTRAINT customer_sale_receipts_amounts_nonneg CHECK (
        subtotal_amount >= 0
        AND total_amount >= 0
        AND total_items >= 0
        AND total_lines >= 0
    ),
    CONSTRAINT customer_sale_receipts_snapshots_check CHECK (
        jsonb_typeof(organization_snapshot) = 'object'
        AND (customer_snapshot IS NULL OR jsonb_typeof(customer_snapshot) = 'object')
        AND jsonb_typeof(lines_snapshot) = 'array'
    )
);

CREATE INDEX IF NOT EXISTS idx_customer_sale_receipts_org_issued_at
    ON public.customer_sale_receipts (organization_id, issued_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_sale_receipts_customer_issued_at
    ON public.customer_sale_receipts (customer_id, issued_at DESC);

CREATE OR REPLACE FUNCTION public.touch_customer_sale_receipts_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_sale_receipts_updated_at
    ON public.customer_sale_receipts;
CREATE TRIGGER trg_customer_sale_receipts_updated_at
    BEFORE UPDATE ON public.customer_sale_receipts
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_customer_sale_receipts_updated_at();

ALTER TABLE public.customer_sale_receipts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS csr_select_org_members ON public.customer_sale_receipts;
CREATE POLICY csr_select_org_members
    ON public.customer_sale_receipts
    FOR SELECT
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS csr_select_customer_owner ON public.customer_sale_receipts;
CREATE POLICY csr_select_customer_owner
    ON public.customer_sale_receipts
    FOR SELECT
    USING (
        customer_id IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM public.customers c
            WHERE c.id = customer_sale_receipts.customer_id
              AND c.user_id = auth.uid()
        )
    );

GRANT SELECT ON public.customer_sale_receipts TO authenticated;
GRANT ALL ON public.customer_sale_receipts TO service_role;

COMMENT ON TABLE public.customer_sale_receipts IS
    'Recus de vente client emis apres completion. Snapshot immuable pour affichage, impression et export.';

COMMENT ON COLUMN public.customer_sale_receipts.receipt_number IS
    'Identifiant lisible du recu, derive de la date de vente et de la commande.';

COMMENT ON COLUMN public.customer_sale_receipts.lines_snapshot IS
    'Copie JSON des lignes vendues : article, quantite, prix unitaire, devise et total ligne.';
