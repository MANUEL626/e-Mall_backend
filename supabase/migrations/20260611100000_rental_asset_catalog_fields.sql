-- Enrichissement des actifs louables.
-- Les biens `rental_asset` restent dans `organization_articles` pour reutiliser
-- les medias catalogue, categories, posts vitrines et le stock par boutique.

ALTER TABLE public.organization_articles
    ADD COLUMN IF NOT EXISTS unit_purchase_price numeric(14, 2) NOT NULL DEFAULT 0;

ALTER TABLE public.organization_articles
    DROP CONSTRAINT IF EXISTS organization_articles_unit_purchase_price_nonneg;

ALTER TABLE public.organization_articles
    ADD CONSTRAINT organization_articles_unit_purchase_price_nonneg
    CHECK (unit_purchase_price >= 0);

COMMENT ON COLUMN public.organization_articles.unit_purchase_price IS
    'Prix d''achat ou cout d''acquisition indicatif. Utilise notamment pour les rental_asset.';

COMMENT ON COLUMN public.organization_articles.unit_sale_price IS
    'Prix de vente pour sales_item. Pour rental_asset, prix de location unitaire par defaut.';

COMMENT ON COLUMN public.organization_articles.wholesale_prices IS
    'Paliers de prix en lot. Pour sales_item: prix de vente en lot. Pour rental_asset: prix de location en lot.';

CREATE INDEX IF NOT EXISTS idx_organization_articles_rental_assets_active
    ON public.organization_articles (organization_id, active, category)
    WHERE resource_scope = 'rental_asset'::public.organization_stock_scope_enum;
