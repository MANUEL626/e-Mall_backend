-- Links purchase trend events to completed customer sale lines for idempotency.

ALTER TABLE public.customer_article_trend_events
    ADD COLUMN IF NOT EXISTS sale_order_id uuid
        REFERENCES public.organization_customer_sale_orders (id) ON DELETE SET NULL;

ALTER TABLE public.customer_article_trend_events
    ADD COLUMN IF NOT EXISTS sale_order_line_id uuid
        REFERENCES public.organization_customer_sale_order_lines (id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_article_trend_events_purchase_line
    ON public.customer_article_trend_events (sale_order_line_id)
    WHERE event_type = 'purchase'::public.customer_article_trend_event_type_enum
      AND sale_order_line_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_sale_order
    ON public.customer_article_trend_events (sale_order_id)
    WHERE sale_order_id IS NOT NULL;

COMMENT ON COLUMN public.customer_article_trend_events.sale_order_id IS
    'Commande customer source pour les evenements purchase generes automatiquement.';

COMMENT ON COLUMN public.customer_article_trend_events.sale_order_line_id IS
    'Ligne de commande source; unique pour event_type=purchase afin d''eviter les doublons.';
