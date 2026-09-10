-- Keep Premium as the full-access plan and refresh Stripe price IDs.

UPDATE public.organization_subscription_plans
SET
    stripe_monthly_price_id = 'price_1Teg14AFRiqwvhS4ITYskzVK',
    stripe_yearly_price_id = 'price_1Teg14AFRiqwvhS4Xeea2eAF'
WHERE code = 'standard';

UPDATE public.organization_subscription_plans
SET
    stripe_monthly_price_id = 'price_1Teg3EAFRiqwvhS46GxjxMrL',
    stripe_yearly_price_id = 'price_1Teg3EAFRiqwvhS49jNhW4q2',
    features = features
        || '{
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
            "priority_support": true,
            "multi_shops": true,
            "sales_shops": true,
            "delivery_shops": true,
            "repair_shops": true,
            "rental_shops": true,
            "repair_domain": true,
            "rental_domain": true,
            "rental_asset_posts": true,
            "delivery_realtime_ws": true,
            "sale_receipts": true,
            "repair_invoices": true,
            "subscription_invoices": true
        }'::jsonb
WHERE code = 'premium';
