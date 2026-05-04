-- Abonnements client → organisation (marchand). Statut pour réactivation sans doublon.

DO $$
BEGIN
    CREATE TYPE public.customer_org_subscription_status AS ENUM ('active', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.customer_organization_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid NOT NULL REFERENCES public.customers (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    status public.customer_org_subscription_status NOT NULL DEFAULT 'active',
    subscribed_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_org_subscription UNIQUE (customer_id, organization_id),
    CONSTRAINT customer_org_sub_cancelled_at CHECK (
        (status = 'active' AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND cancelled_at IS NOT NULL)
    )
);

COMMENT ON TABLE public.customer_organization_subscriptions IS
    'Abonnement d''un client à une organisation marchande (suivi, notifications futures).';

CREATE INDEX IF NOT EXISTS idx_customer_org_subscriptions_customer
    ON public.customer_organization_subscriptions (customer_id);

CREATE INDEX IF NOT EXISTS idx_customer_org_subscriptions_org_active
    ON public.customer_organization_subscriptions (organization_id)
    WHERE status = 'active';

CREATE OR REPLACE FUNCTION public.touch_customer_organization_subscriptions_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_org_subscriptions_updated_at
    ON public.customer_organization_subscriptions;
CREATE TRIGGER trg_customer_org_subscriptions_updated_at
    BEFORE UPDATE ON public.customer_organization_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_customer_organization_subscriptions_updated_at();

CREATE OR REPLACE FUNCTION public.customer_org_subscriptions_set_cancelled_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    IF NEW.status = 'cancelled'::public.customer_org_subscription_status
       AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status) THEN
        NEW.cancelled_at := COALESCE(NEW.cancelled_at, now());
    ELSIF NEW.status = 'active'::public.customer_org_subscription_status THEN
        NEW.cancelled_at := NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_org_subscriptions_status ON public.customer_organization_subscriptions;
CREATE TRIGGER trg_customer_org_subscriptions_status
    BEFORE INSERT OR UPDATE OF status ON public.customer_organization_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION public.customer_org_subscriptions_set_cancelled_at();

ALTER TABLE public.customer_organization_subscriptions ENABLE ROW LEVEL SECURITY;

-- Lecture : propriétaire (client) ou membre actif de l’organisation.
DROP POLICY IF EXISTS customer_org_subscriptions_select ON public.customer_organization_subscriptions;
CREATE POLICY customer_org_subscriptions_select
    ON public.customer_organization_subscriptions
    FOR SELECT
    TO authenticated
    USING (
        customer_id IN (
            SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid()
        )
        OR organization_id IN (
            SELECT m.organization_id
            FROM public.members m
            WHERE m.user_id = auth.uid() AND m.activity_status = true
        )
    );

DROP POLICY IF EXISTS customer_org_subscriptions_insert ON public.customer_organization_subscriptions;
CREATE POLICY customer_org_subscriptions_insert
    ON public.customer_organization_subscriptions
    FOR INSERT
    TO authenticated
    WITH CHECK (
        customer_id IN (
            SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS customer_org_subscriptions_update ON public.customer_organization_subscriptions;
CREATE POLICY customer_org_subscriptions_update
    ON public.customer_organization_subscriptions
    FOR UPDATE
    TO authenticated
    USING (
        customer_id IN (
            SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid()
        )
    )
    WITH CHECK (
        customer_id IN (
            SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS customer_org_subscriptions_delete ON public.customer_organization_subscriptions;
CREATE POLICY customer_org_subscriptions_delete
    ON public.customer_organization_subscriptions
    FOR DELETE
    TO authenticated
    USING (
        customer_id IN (
            SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid()
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.customer_organization_subscriptions TO authenticated;
