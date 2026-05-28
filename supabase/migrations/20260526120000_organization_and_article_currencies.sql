-- Devises organisation / articles / operations.
-- Format applicatif: codes ISO 4217 en minuscules.

ALTER TABLE public.organizations
    ADD COLUMN IF NOT EXISTS default_currencies jsonb NOT NULL
    DEFAULT '{"purchase":"eur","sale":"xof"}'::jsonb;

UPDATE public.organizations
SET default_currencies = '{"purchase":"eur","sale":"xof"}'::jsonb
WHERE default_currencies IS NULL;

ALTER TABLE public.organizations
    DROP CONSTRAINT IF EXISTS organizations_default_currencies_check;
ALTER TABLE public.organizations
    ADD CONSTRAINT organizations_default_currencies_check CHECK (
        jsonb_typeof(default_currencies) = 'object'
        AND default_currencies ? 'purchase'
        AND default_currencies ? 'sale'
        AND (default_currencies ->> 'purchase') = lower(default_currencies ->> 'purchase')
        AND (default_currencies ->> 'sale') = lower(default_currencies ->> 'sale')
        AND (default_currencies ->> 'purchase') IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
        AND (default_currencies ->> 'sale') IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    );

COMMENT ON COLUMN public.organizations.default_currencies IS
    'JSONB: {"purchase":"eur","sale":"xof"} devises par defaut de l''organisation.';

ALTER TABLE public.organization_articles
    ADD COLUMN IF NOT EXISTS sale_currency text NOT NULL DEFAULT 'xof';

UPDATE public.organization_articles
SET sale_currency = 'xof'
WHERE sale_currency IS NULL OR btrim(sale_currency) = '';

ALTER TABLE public.organization_articles
    DROP CONSTRAINT IF EXISTS organization_articles_sale_currency_check;
ALTER TABLE public.organization_articles
    ADD CONSTRAINT organization_articles_sale_currency_check CHECK (
        sale_currency = lower(sale_currency)
        AND sale_currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    );

COMMENT ON COLUMN public.organization_articles.sale_currency IS
    'Devise du prix de vente public de l''article (code ISO 4217 en minuscules).';

ALTER TABLE public.organization_article_orders
    ADD COLUMN IF NOT EXISTS currency text NOT NULL DEFAULT 'eur';

UPDATE public.organization_article_orders
SET currency = 'eur'
WHERE currency IS NULL OR btrim(currency) = '';

ALTER TABLE public.organization_article_orders
    DROP CONSTRAINT IF EXISTS organization_article_orders_currency_check;
ALTER TABLE public.organization_article_orders
    ADD CONSTRAINT organization_article_orders_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    );

COMMENT ON COLUMN public.organization_article_orders.currency IS
    'Devise utilisee pour cette commande fournisseur (snapshot operationnel).';

ALTER TABLE public.organization_customer_sale_orders
    ALTER COLUMN currency SET DEFAULT 'xof';

UPDATE public.organization_customer_sale_orders
SET currency = lower(COALESCE(currency, 'xof'))
WHERE currency IS NULL OR currency <> lower(currency);

ALTER TABLE public.organization_customer_sale_orders
    DROP CONSTRAINT IF EXISTS organization_customer_sale_orders_currency_check;
ALTER TABLE public.organization_customer_sale_orders
    ADD CONSTRAINT organization_customer_sale_orders_currency_check CHECK (
        currency = lower(currency)
        AND currency IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    );

COMMENT ON COLUMN public.organization_customer_sale_orders.currency IS
    'Devise principale de la commande client (snapshot operationnel).';

ALTER TABLE public.organization_customer_sale_order_lines
    ADD COLUMN IF NOT EXISTS currency_snapshot text NOT NULL DEFAULT 'xof';

UPDATE public.organization_customer_sale_order_lines l
SET currency_snapshot = COALESCE(a.sale_currency, 'xof')
FROM public.organization_articles a
WHERE l.article_id = a.id
  AND (l.currency_snapshot IS NULL OR btrim(l.currency_snapshot) = '');

ALTER TABLE public.organization_customer_sale_order_lines
    DROP CONSTRAINT IF EXISTS ocso_lines_currency_snapshot_check;
ALTER TABLE public.organization_customer_sale_order_lines
    ADD CONSTRAINT ocso_lines_currency_snapshot_check CHECK (
        currency_snapshot = lower(currency_snapshot)
        AND currency_snapshot IN ('xof', 'eur', 'usd', 'gbp', 'cny', 'ngn', 'ghs')
    );

COMMENT ON COLUMN public.organization_customer_sale_order_lines.currency_snapshot IS
    'Devise du prix capturee au moment de la vente client.';

DROP VIEW IF EXISTS public.customer_article_post_feed;

CREATE VIEW public.customer_article_post_feed AS
SELECT
    p.slot,
    p.media_kind,
    COALESCE(p.video_mobile_low_storage_path, p.media_storage_path) AS media_storage_path,
    p.video_mobile_low_storage_path,
    p.thumbnail_storage_path,
    p.caption,
    p.processing_status,
    p.media_width,
    p.media_height,
    p.media_duration_seconds,
    a.id AS organization_article_id,
    a.organization_id,
    a.name,
    a.category,
    a.unit_sale_price,
    a.sale_currency,
    a.stock_status,
    a.primary_image_storage_path,
    a.additional_image_storage_paths,
    a.description,
    p.created_at AS post_created_at
FROM public.organization_article_posts p
INNER JOIN public.organization_articles a ON a.id = p.organization_article_id
WHERE p.active IS TRUE
  AND a.active IS TRUE
  AND (
      p.media_kind = 'image'
      OR (
          p.processing_status = 'ready'
          AND p.video_mobile_low_storage_path IS NOT NULL
      )
  );

COMMENT ON VIEW public.customer_article_post_feed IS
    'Posts actifs pour le feed customer. Inclut la devise de vente de l''article.';

GRANT SELECT ON public.customer_article_post_feed TO service_role;
