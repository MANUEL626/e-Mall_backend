-- Indexes for high-traffic API paths and subscription guards.

CREATE INDEX IF NOT EXISTS idx_members_org_active
    ON public.members (organization_id, activity_status);

CREATE INDEX IF NOT EXISTS idx_members_user_org_active
    ON public.members (user_id, organization_id, activity_status);

CREATE INDEX IF NOT EXISTS idx_ocso_org_created
    ON public.organization_customer_sale_orders (organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ocso_customer_created
    ON public.organization_customer_sale_orders (customer_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ocso_org_fulfillment_created
    ON public.organization_customer_sale_orders (
        organization_id,
        fulfillment_type,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_ocso_assigned_delivery_created
    ON public.organization_customer_sale_orders (
        assigned_delivery_member_id,
        created_at DESC
    )
    WHERE assigned_delivery_member_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ocso_lines_article
    ON public.organization_customer_sale_order_lines (article_id);

CREATE INDEX IF NOT EXISTS idx_organization_article_orders_org_created
    ON public.organization_article_orders (organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_organization_article_order_lines_article
    ON public.organization_article_order_lines (article_id);

CREATE INDEX IF NOT EXISTS idx_organization_article_posts_article_active_slot
    ON public.organization_article_posts (
        organization_article_id,
        active,
        slot
    );

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_article_occurred
    ON public.customer_article_trend_events (article_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_org_occurred
    ON public.customer_article_trend_events (organization_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_country_category_occurred
    ON public.customer_article_trend_events (
        country,
        category,
        occurred_at DESC
    );
