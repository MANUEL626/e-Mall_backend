-- Internal organization subscription engine.
-- Stripe will sync into these rows later; the product logic reads from here.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'organization_subscription_plan_enum'
    ) THEN
        CREATE TYPE public.organization_subscription_plan_enum AS ENUM (
            'freemium',
            'standard',
            'premium'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'organization_subscription_status_enum'
    ) THEN
        CREATE TYPE public.organization_subscription_status_enum AS ENUM (
            'trialing',
            'active',
            'past_due',
            'canceled',
            'expired',
            'suspended'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.organization_subscription_plans (
    code public.organization_subscription_plan_enum PRIMARY KEY,
    name text NOT NULL,
    description text,
    features jsonb NOT NULL DEFAULT '{}'::jsonb,
    limits jsonb NOT NULL DEFAULT '{}'::jsonb,
    stripe_product_id text,
    stripe_monthly_price_id text,
    stripe_yearly_price_id text,
    active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_subscription_plans_features_object
        CHECK (jsonb_typeof(features) = 'object'),
    CONSTRAINT organization_subscription_plans_limits_object
        CHECK (jsonb_typeof(limits) = 'object')
);

CREATE TABLE IF NOT EXISTS public.organization_subscriptions (
    organization_id uuid PRIMARY KEY REFERENCES public.organizations(id) ON DELETE CASCADE,
    plan public.organization_subscription_plan_enum NOT NULL DEFAULT 'freemium',
    status public.organization_subscription_status_enum NOT NULL DEFAULT 'active',
    source text NOT NULL DEFAULT 'internal',
    current_period_start timestamptz NOT NULL DEFAULT now(),
    current_period_end timestamptz,
    trial_end timestamptz,
    cancel_at_period_end boolean NOT NULL DEFAULT false,
    stripe_customer_id text,
    stripe_subscription_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_subscriptions_source_check
        CHECK (source IN ('internal', 'manual', 'stripe', 'promo')),
    CONSTRAINT organization_subscriptions_metadata_object
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS organization_subscriptions_stripe_subscription_uidx
    ON public.organization_subscriptions (stripe_subscription_id)
    WHERE stripe_subscription_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS organization_subscriptions_plan_idx
    ON public.organization_subscriptions (plan);

CREATE INDEX IF NOT EXISTS organization_subscriptions_status_idx
    ON public.organization_subscriptions (status);

CREATE OR REPLACE FUNCTION public.touch_organization_subscription_plans_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_subscription_plans_updated_at
    ON public.organization_subscription_plans;
CREATE TRIGGER trg_organization_subscription_plans_updated_at
BEFORE UPDATE ON public.organization_subscription_plans
FOR EACH ROW EXECUTE FUNCTION public.touch_organization_subscription_plans_updated_at();

CREATE OR REPLACE FUNCTION public.touch_organization_subscriptions_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_subscriptions_updated_at
    ON public.organization_subscriptions;
CREATE TRIGGER trg_organization_subscriptions_updated_at
BEFORE UPDATE ON public.organization_subscriptions
FOR EACH ROW EXECUTE FUNCTION public.touch_organization_subscriptions_updated_at();

INSERT INTO public.organization_subscription_plans
    (code, name, description, features, limits, active, sort_order)
VALUES
    (
        'freemium',
        'Freemium',
        'Plan gratuit pour tester e-Mall avec une boutique simple.',
        '{
            "basic_catalog": true,
            "simple_stock": true,
            "walk_in_sales": true,
            "article_posts": false,
            "supplier_orders": false,
            "pickup_delivery": false,
            "delivery_assignment": false,
            "delivery_status_history": false,
            "sales_dashboard": "basic",
            "advanced_reports": false,
            "ai_performance_agent": false,
            "team_customer_messaging": false,
            "advanced_roles": false,
            "realtime_gps": false,
            "priority_support": false
        }'::jsonb,
        '{
            "active_articles": 20,
            "monthly_walk_in_sales": 50,
            "team_members": 1,
            "monthly_ai_requests": 0
        }'::jsonb,
        true,
        10
    ),
    (
        'standard',
        'Standard',
        'Plan operationnel pour une boutique active avec commandes et livraison.',
        '{
            "basic_catalog": true,
            "simple_stock": true,
            "walk_in_sales": true,
            "article_posts": true,
            "supplier_orders": true,
            "pickup_delivery": true,
            "delivery_assignment": true,
            "delivery_status_history": true,
            "sales_dashboard": "standard",
            "advanced_reports": false,
            "ai_performance_agent": false,
            "team_customer_messaging": false,
            "advanced_roles": false,
            "realtime_gps": false,
            "priority_support": false
        }'::jsonb,
        '{
            "active_articles": null,
            "monthly_walk_in_sales": null,
            "team_members": 5,
            "monthly_ai_requests": 0
        }'::jsonb,
        true,
        20
    ),
    (
        'premium',
        'Premium',
        'Plan avance pour equipes, GPS, messagerie, rapports et agent IA.',
        '{
            "basic_catalog": true,
            "simple_stock": true,
            "walk_in_sales": true,
            "article_posts": true,
            "supplier_orders": true,
            "pickup_delivery": true,
            "delivery_assignment": true,
            "delivery_status_history": true,
            "sales_dashboard": "advanced",
            "advanced_reports": true,
            "ai_performance_agent": true,
            "team_customer_messaging": true,
            "advanced_roles": true,
            "realtime_gps": true,
            "priority_support": true
        }'::jsonb,
        '{
            "active_articles": null,
            "monthly_walk_in_sales": null,
            "team_members": null,
            "monthly_ai_requests": 500
        }'::jsonb,
        true,
        30
    )
ON CONFLICT (code) DO UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    features = EXCLUDED.features,
    limits = EXCLUDED.limits,
    active = EXCLUDED.active,
    sort_order = EXCLUDED.sort_order;

INSERT INTO public.organization_subscriptions
    (organization_id, plan, status, source, metadata)
SELECT
    o.id,
    'freemium',
    'active',
    'internal',
    '{"backfilled": true}'::jsonb
FROM public.organizations o
ON CONFLICT (organization_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.create_default_organization_subscription()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.organization_subscriptions
        (organization_id, plan, status, source)
    VALUES
        (NEW.id, 'freemium', 'active', 'internal')
    ON CONFLICT (organization_id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organizations_default_subscription ON public.organizations;
CREATE TRIGGER trg_organizations_default_subscription
AFTER INSERT ON public.organizations
FOR EACH ROW EXECUTE FUNCTION public.create_default_organization_subscription();

ALTER TABLE public.organization_subscription_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS org_subscription_plans_select_active
    ON public.organization_subscription_plans;
CREATE POLICY org_subscription_plans_select_active
    ON public.organization_subscription_plans
    FOR SELECT
    USING (active = true);

DROP POLICY IF EXISTS org_subscriptions_member_select
    ON public.organization_subscriptions;
CREATE POLICY org_subscriptions_member_select
    ON public.organization_subscriptions
    FOR SELECT
    USING (public.is_org_member(organization_id));

GRANT SELECT ON public.organization_subscription_plans TO authenticated;
GRANT SELECT ON public.organization_subscriptions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.organization_subscription_plans TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.organization_subscriptions TO service_role;
