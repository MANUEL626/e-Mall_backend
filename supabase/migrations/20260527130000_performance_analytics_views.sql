-- SQL views used by the Performance service for lighter analytics queries.

DROP VIEW IF EXISTS public.organization_completed_sale_lines;
CREATE VIEW public.organization_completed_sale_lines AS
SELECT
    o.organization_id,
    o.id AS order_id,
    l.id AS order_line_id,
    o.customer_id,
    o.fulfillment_type,
    o.created_at,
    o.currency AS order_currency,
    l.article_id,
    a.name AS article_name,
    a.category AS article_category,
    l.quantity,
    l.unit_price_snapshot,
    l.currency_snapshot,
    (l.quantity::numeric * l.unit_price_snapshot) AS line_total
FROM public.organization_customer_sale_orders o
INNER JOIN public.organization_customer_sale_order_lines l ON l.order_id = o.id
INNER JOIN public.organization_articles a ON a.id = l.article_id
WHERE o.status = 'completed'::public.customer_sale_order_status_enum;

COMMENT ON VIEW public.organization_completed_sale_lines IS
    'Lignes de ventes client completees, pretes pour rapports Performance.';

DROP VIEW IF EXISTS public.organization_supplier_order_line_totals;
CREATE VIEW public.organization_supplier_order_line_totals AS
SELECT
    o.organization_id,
    o.id AS order_id,
    l.id AS order_line_id,
    o.created_at,
    o.status,
    o.currency,
    l.article_id,
    a.name AS article_name,
    a.category AS article_category,
    l.quantity_ordered,
    l.quantity_received,
    l.unit_price,
    l.total_price
FROM public.organization_article_orders o
INNER JOIN public.organization_article_order_lines l ON l.order_id = o.id
INNER JOIN public.organization_articles a ON a.id = l.article_id;

COMMENT ON VIEW public.organization_supplier_order_line_totals IS
    'Lignes de commandes fournisseur avec total_price, pretes pour rapports Performance.';

REVOKE ALL ON public.organization_completed_sale_lines FROM anon, authenticated;
REVOKE ALL ON public.organization_supplier_order_line_totals FROM anon, authenticated;

GRANT SELECT ON public.organization_completed_sale_lines TO service_role;
GRANT SELECT ON public.organization_supplier_order_line_totals TO service_role;
