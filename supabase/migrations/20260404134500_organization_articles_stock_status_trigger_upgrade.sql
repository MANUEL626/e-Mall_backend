-- Si la table a été créée avec stock_status en colonne GENERATED, la remplacer par une
-- colonne classique alimentée par le trigger (les migrations initiales déjà appliquées ne
-- sont pas rejouées par CREATE TABLE IF NOT EXISTS).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
          AND c.table_name = 'organization_articles'
          AND c.column_name = 'stock_status'
          AND c.is_generated = 'ALWAYS'
    ) THEN
        ALTER TABLE public.organization_articles DROP COLUMN stock_status;
        ALTER TABLE public.organization_articles
            ADD COLUMN stock_status public.article_stock_status_enum NOT NULL DEFAULT 'out_of_stock';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.organization_articles_set_stock_status()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.stock_quantity <= 0 THEN
        NEW.stock_status := 'out_of_stock'::public.article_stock_status_enum;
    ELSIF NEW.stock_quantity <= NEW.alert_quantity THEN
        NEW.stock_status := 'low_stock'::public.article_stock_status_enum;
    ELSE
        NEW.stock_status := 'in_stock'::public.article_stock_status_enum;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.organization_articles_set_stock_status() IS
    'out_of_stock si stock 0 ; low_stock si stock > 0 et ≤ quantité d''alerte ; sinon in_stock.';

DROP TRIGGER IF EXISTS trg_organization_articles_stock_status ON public.organization_articles;
CREATE TRIGGER trg_organization_articles_stock_status
    BEFORE INSERT OR UPDATE ON public.organization_articles
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_articles_set_stock_status();

COMMENT ON COLUMN public.organization_articles.stock_status IS
    'Maintenu par trg_organization_articles_stock_status : voir fonction organization_articles_set_stock_status.';

UPDATE public.organization_articles
SET stock_quantity = stock_quantity;
