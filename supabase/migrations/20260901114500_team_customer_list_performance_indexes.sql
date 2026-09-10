-- Indexes for team, shop and customer list endpoints.

CREATE INDEX IF NOT EXISTS idx_organization_shops_org_default_created
    ON public.organization_shops (
        organization_id,
        is_default DESC,
        created_at ASC
    );

CREATE INDEX IF NOT EXISTS idx_members_org_created
    ON public.members (
        organization_id,
        created_at ASC
    );

CREATE INDEX IF NOT EXISTS idx_customer_wishlist_customer_created
    ON public.customer_wishlist_items (
        customer_id,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_customer_carts_customer_updated
    ON public.customer_carts (
        customer_id,
        updated_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_customer_cart_items_cart_article
    ON public.customer_cart_items (
        cart_id,
        organization_article_id
    );

CREATE INDEX IF NOT EXISTS idx_customer_org_subscriptions_org_status_subscribed
    ON public.customer_organization_subscriptions (
        organization_id,
        status,
        subscribed_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_customer_org_subscriptions_customer_status_subscribed
    ON public.customer_organization_subscriptions (
        customer_id,
        status,
        subscribed_at DESC
    );
