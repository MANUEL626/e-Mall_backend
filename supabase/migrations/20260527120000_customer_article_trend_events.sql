-- Customer trend signals used by performance reports and future recommendations.

DO $$
BEGIN
    CREATE TYPE public.customer_article_trend_event_type_enum AS ENUM (
        'search',
        'view',
        'post_view',
        'wishlist_add',
        'cart_add',
        'purchase',
        'cart_abandon'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.customer_article_trend_events_set_defaults()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.search_query := NULLIF(btrim(NEW.search_query), '');
    NEW.country := upper(NULLIF(btrim(NEW.country), ''));
    NEW.locale := NULLIF(btrim(NEW.locale), '');
    NEW.source := NULLIF(btrim(NEW.source), '');

    IF NEW.weight IS NULL THEN
        NEW.weight := CASE NEW.event_type
            WHEN 'search'::public.customer_article_trend_event_type_enum THEN 1
            WHEN 'view'::public.customer_article_trend_event_type_enum THEN 2
            WHEN 'post_view'::public.customer_article_trend_event_type_enum THEN 2
            WHEN 'wishlist_add'::public.customer_article_trend_event_type_enum THEN 4
            WHEN 'cart_add'::public.customer_article_trend_event_type_enum THEN 6
            WHEN 'purchase'::public.customer_article_trend_event_type_enum THEN 10
            WHEN 'cart_abandon'::public.customer_article_trend_event_type_enum THEN 3
            ELSE 1
        END;
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.customer_article_trend_events_set_defaults() IS
    'Normalise les champs texte et applique le poids metier par defaut selon le type d''evenement.';

CREATE OR REPLACE FUNCTION public.customer_article_trend_events_validate_article_org()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.article_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM public.organization_articles a
        WHERE a.id = NEW.article_id
          AND a.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'article_id must belong to organization_id'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.customer_article_trend_events_validate_article_org() IS
    'Garantit qu''un signal tendance lie a un article reste dans la meme organisation.';

CREATE TABLE IF NOT EXISTS public.customer_article_trend_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    article_id uuid REFERENCES public.organization_articles (id) ON DELETE SET NULL,
    customer_id uuid REFERENCES public.customers (id) ON DELETE SET NULL,
    event_type public.customer_article_trend_event_type_enum NOT NULL,
    search_query text,
    category public.article_category_enum,
    country varchar(2),
    locale text,
    source text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    weight numeric(8, 2) NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT customer_article_trend_events_weight_check CHECK (weight >= 0),
    CONSTRAINT customer_article_trend_events_metadata_object CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT customer_article_trend_events_country_check CHECK (
        country IS NULL OR country ~ '^[A-Z]{2}$'
    ),
    CONSTRAINT customer_article_trend_events_locale_check CHECK (
        locale IS NULL OR locale ~ '^[A-Za-z]{2}([-_][A-Za-z]{2})?$'
    ),
    CONSTRAINT customer_article_trend_events_search_query_len CHECK (
        search_query IS NULL OR char_length(search_query) <= 255
    ),
    CONSTRAINT customer_article_trend_events_source_len CHECK (
        source IS NULL OR char_length(source) <= 80
    )
);

COMMENT ON TABLE public.customer_article_trend_events IS
    'Signaux customer pour calculer les articles tendance: recherches, vues, favoris, panier, achats et abandons.';

COMMENT ON COLUMN public.customer_article_trend_events.event_type IS
    'Enum strict: search, view, post_view, wishlist_add, cart_add, purchase, cart_abandon.';

COMMENT ON COLUMN public.customer_article_trend_events.weight IS
    'Poids metier applique par defaut via trigger; peut etre ajuste par le backend service_role.';

COMMENT ON COLUMN public.customer_article_trend_events.metadata IS
    'Objet JSON libre pour contexte non critique: screen, position, post_id, request_id, etc.';

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_org_time
    ON public.customer_article_trend_events (organization_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_article_time
    ON public.customer_article_trend_events (article_id, occurred_at DESC)
    WHERE article_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_customer_time
    ON public.customer_article_trend_events (customer_id, occurred_at DESC)
    WHERE customer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_org_article_type_time
    ON public.customer_article_trend_events (organization_id, article_id, event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_org_type_time
    ON public.customer_article_trend_events (organization_id, event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_category_time
    ON public.customer_article_trend_events (category, occurred_at DESC)
    WHERE category IS NOT NULL;

DROP TRIGGER IF EXISTS trg_customer_article_trend_events_defaults ON public.customer_article_trend_events;
CREATE TRIGGER trg_customer_article_trend_events_defaults
    BEFORE INSERT OR UPDATE ON public.customer_article_trend_events
    FOR EACH ROW
    EXECUTE FUNCTION public.customer_article_trend_events_set_defaults();

DROP TRIGGER IF EXISTS trg_customer_article_trend_events_article_org ON public.customer_article_trend_events;
CREATE TRIGGER trg_customer_article_trend_events_article_org
    BEFORE INSERT OR UPDATE OF organization_id, article_id ON public.customer_article_trend_events
    FOR EACH ROW
    EXECUTE FUNCTION public.customer_article_trend_events_validate_article_org();

ALTER TABLE public.customer_article_trend_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS customer_article_trend_events_select_member ON public.customer_article_trend_events;
CREATE POLICY customer_article_trend_events_select_member
    ON public.customer_article_trend_events
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS customer_article_trend_events_select_customer_self ON public.customer_article_trend_events;
CREATE POLICY customer_article_trend_events_select_customer_self
    ON public.customer_article_trend_events
    FOR SELECT
    TO authenticated
    USING (
        customer_id IS NOT NULL
        AND public.is_customer_self(customer_id)
    );

DROP POLICY IF EXISTS customer_article_trend_events_no_direct_writes ON public.customer_article_trend_events;
CREATE POLICY customer_article_trend_events_no_direct_writes
    ON public.customer_article_trend_events
    FOR ALL
    TO authenticated
    USING (false)
    WITH CHECK (false);
