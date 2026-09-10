-- Optimise les listes de ventes customer / organisation / boutique.
-- Les endpoints lisent toujours les lignes en lot cote API, puis paginent les commandes.

CREATE INDEX IF NOT EXISTS idx_ocso_customer_status_created
    ON public.organization_customer_sale_orders (customer_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ocso_org_status_created
    ON public.organization_customer_sale_orders (organization_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ocso_org_shop_status_created
    ON public.organization_customer_sale_orders (
        organization_id,
        shop_id,
        status,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_ocso_lines_order_article
    ON public.organization_customer_sale_order_lines (order_id, article_id);
