-- Articles en stock par organisation (prix, gros, images Storage, statut dérivé du stock).

-- Vrai si l'utilisateur connecté est membre actif de l'organisation (pour RLS + Storage).
CREATE OR REPLACE FUNCTION public.is_org_member(p_organization_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.members m
        WHERE m.organization_id = p_organization_id
          AND m.user_id = auth.uid()
          AND m.activity_status = true
    );
$$;

COMMENT ON FUNCTION public.is_org_member(uuid) IS
    'Utilisé par RLS / storage : membre actif de l''organisation.';

DO $$
BEGIN
    CREATE TYPE public.article_category_enum AS ENUM (
        'electronics',
        'appliances',
        'clothing',
        'food',
        'beauty',
        'sports',
        'home',
        'other'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE public.article_stock_status_enum AS ENUM (
        'in_stock',
        'low_stock',
        'out_of_stock'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.touch_organization_articles_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- Statut stock : 0 → rupture ; >0 et ≤ seuil critique → alerte ; au-dessus → en stock.
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

CREATE TABLE IF NOT EXISTS public.organization_articles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    name text NOT NULL,
    category public.article_category_enum NOT NULL,
    unit_sale_price numeric(14, 2) NOT NULL,
    wholesale_prices jsonb,
    stock_quantity integer NOT NULL DEFAULT 0,
    alert_quantity integer NOT NULL DEFAULT 0,
    stock_status public.article_stock_status_enum NOT NULL DEFAULT 'out_of_stock',
    description text,
    primary_image_storage_path text NOT NULL,
    additional_image_storage_paths text[] NOT NULL DEFAULT '{}'::text[],
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_articles_unit_price_nonneg CHECK (unit_sale_price >= 0),
    CONSTRAINT organization_articles_stock_nonneg CHECK (stock_quantity >= 0),
    CONSTRAINT organization_articles_alert_nonneg CHECK (alert_quantity >= 0),
    CONSTRAINT organization_articles_wholesale_array CHECK (
        wholesale_prices IS NULL OR jsonb_typeof(wholesale_prices) = 'array'
    )
);

COMMENT ON TABLE public.organization_articles IS
    'Catalogue / stock : articles rattachés à une organisation.';

COMMENT ON COLUMN public.organization_articles.wholesale_prices IS
    'JSON tableau : [{ "min_quantity": n, "max_quantity": m|null, "unit_price": x }, ...].';

COMMENT ON COLUMN public.organization_articles.stock_status IS
    'Maintenu par trg_organization_articles_stock_status : voir fonction organization_articles_set_stock_status.';

COMMENT ON COLUMN public.organization_articles.primary_image_storage_path IS
    'Chemin objet dans le bucket Storage `organization-articles` (obligatoire).';

COMMENT ON COLUMN public.organization_articles.additional_image_storage_paths IS
    'Chemins optionnels dans le même bucket.';

CREATE INDEX IF NOT EXISTS idx_organization_articles_org
    ON public.organization_articles (organization_id);

CREATE INDEX IF NOT EXISTS idx_organization_articles_org_active
    ON public.organization_articles (organization_id, active);

DROP TRIGGER IF EXISTS trg_organization_articles_stock_status ON public.organization_articles;
CREATE TRIGGER trg_organization_articles_stock_status
    BEFORE INSERT OR UPDATE ON public.organization_articles
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_articles_set_stock_status();

DROP TRIGGER IF EXISTS trg_organization_articles_updated_at ON public.organization_articles;
CREATE TRIGGER trg_organization_articles_updated_at
    BEFORE UPDATE ON public.organization_articles
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_articles_updated_at();

ALTER TABLE public.organization_articles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_articles_select_member ON public.organization_articles;
CREATE POLICY organization_articles_select_member
    ON public.organization_articles
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_articles_insert_member ON public.organization_articles;
CREATE POLICY organization_articles_insert_member
    ON public.organization_articles
    FOR INSERT
    TO authenticated
    WITH CHECK (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_articles_update_member ON public.organization_articles;
CREATE POLICY organization_articles_update_member
    ON public.organization_articles
    FOR UPDATE
    TO authenticated
    USING (public.is_org_member(organization_id))
    WITH CHECK (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_articles_delete_member ON public.organization_articles;
CREATE POLICY organization_articles_delete_member
    ON public.organization_articles
    FOR DELETE
    TO authenticated
    USING (public.is_org_member(organization_id));
