-- Indexes pour les listes article/stock, commandes fournisseur et posts vitrine.

CREATE INDEX IF NOT EXISTS idx_organization_articles_org_scope_created
    ON public.organization_articles (organization_id, resource_scope, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_organization_articles_org_scope_active_created
    ON public.organization_articles (
        organization_id,
        resource_scope,
        active,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_org_shop_article_stocks_org_shop_scope_created
    ON public.organization_shop_article_stocks (
        organization_id,
        shop_id,
        stock_scope,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_org_shop_article_stocks_org_shop_scope_active_created
    ON public.organization_shop_article_stocks (
        organization_id,
        shop_id,
        stock_scope,
        active,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_organization_article_orders_org_status_created
    ON public.organization_article_orders (organization_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_organization_article_orders_org_shop_created
    ON public.organization_article_orders (organization_id, shop_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_organization_article_orders_org_shop_status_created
    ON public.organization_article_orders (
        organization_id,
        shop_id,
        status,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_organization_article_order_lines_order_article
    ON public.organization_article_order_lines (order_id, article_id);

CREATE INDEX IF NOT EXISTS idx_organization_article_posts_article_slot
    ON public.organization_article_posts (organization_article_id, slot);
