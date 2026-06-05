-- Stripe price ids for Standard and Premium subscription plans.

UPDATE public.organization_subscription_plans
SET
    stripe_monthly_price_id = 'price_1Teg14AFRiqwvhS4ITYskzVK',
    stripe_yearly_price_id = 'price_1Teg14AFRiqwvhS4Xeea2eAF'
WHERE code = 'standard';

UPDATE public.organization_subscription_plans
SET
    stripe_monthly_price_id = 'price_1Teg3EAFRiqwvhS46GxjxMrL',
    stripe_yearly_price_id = 'price_1Teg3EAFRiqwvhS49jNhW4q2'
WHERE code = 'premium';
