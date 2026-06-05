-- Add monthly/yearly billing support for organization subscriptions.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'organization_subscription_billing_interval_enum'
    ) THEN
        CREATE TYPE public.organization_subscription_billing_interval_enum AS ENUM (
            'monthly',
            'yearly'
        );
    END IF;
END $$;

ALTER TABLE public.organization_subscription_plans
    ADD COLUMN IF NOT EXISTS price_currency text NOT NULL DEFAULT 'xof',
    ADD COLUMN IF NOT EXISTS monthly_price_amount numeric(14, 2),
    ADD COLUMN IF NOT EXISTS yearly_price_amount numeric(14, 2);

ALTER TABLE public.organization_subscription_plans
    DROP CONSTRAINT IF EXISTS organization_subscription_plans_price_currency_check,
    ADD CONSTRAINT organization_subscription_plans_price_currency_check
        CHECK (price_currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')),
    DROP CONSTRAINT IF EXISTS organization_subscription_plans_monthly_price_nonneg,
    ADD CONSTRAINT organization_subscription_plans_monthly_price_nonneg
        CHECK (monthly_price_amount IS NULL OR monthly_price_amount >= 0),
    DROP CONSTRAINT IF EXISTS organization_subscription_plans_yearly_price_nonneg,
    ADD CONSTRAINT organization_subscription_plans_yearly_price_nonneg
        CHECK (yearly_price_amount IS NULL OR yearly_price_amount >= 0);

ALTER TABLE public.organization_subscriptions
    ADD COLUMN IF NOT EXISTS billing_interval public.organization_subscription_billing_interval_enum
        NOT NULL DEFAULT 'monthly',
    ADD COLUMN IF NOT EXISTS stripe_price_id text;

UPDATE public.organization_subscription_plans
SET
    price_currency = 'xof',
    monthly_price_amount = 0,
    yearly_price_amount = 0
WHERE code = 'freemium';

COMMENT ON COLUMN public.organization_subscription_plans.monthly_price_amount IS
    'Monthly public price amount for display and Stripe checkout selection. Null means not configured yet.';

COMMENT ON COLUMN public.organization_subscription_plans.yearly_price_amount IS
    'Yearly public price amount for display and annual savings calculation. Null means not configured yet.';

COMMENT ON COLUMN public.organization_subscriptions.billing_interval IS
    'Selected billing interval for the organization subscription: monthly or yearly.';

COMMENT ON COLUMN public.organization_subscriptions.stripe_price_id IS
    'Stripe price currently used by the subscription, monthly or yearly depending on billing_interval.';
