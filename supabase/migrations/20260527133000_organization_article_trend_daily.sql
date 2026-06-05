-- Daily trend aggregates used as an optional cache for high-volume analytics.

CREATE TABLE IF NOT EXISTS public.organization_article_trend_daily (
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    article_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE CASCADE,
    day date NOT NULL,
    country varchar(2) NOT NULL DEFAULT '',
    category public.article_category_enum,
    search_count integer NOT NULL DEFAULT 0,
    view_count integer NOT NULL DEFAULT 0,
    post_view_count integer NOT NULL DEFAULT 0,
    wishlist_add_count integer NOT NULL DEFAULT 0,
    cart_add_count integer NOT NULL DEFAULT 0,
    purchase_count integer NOT NULL DEFAULT 0,
    purchase_quantity integer NOT NULL DEFAULT 0,
    cart_abandon_count integer NOT NULL DEFAULT 0,
    total_events integer NOT NULL DEFAULT 0,
    trend_score numeric(14, 2) NOT NULL DEFAULT 0,
    first_event_at timestamptz,
    last_event_at timestamptz,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, article_id, day, country),
    CONSTRAINT organization_article_trend_daily_country_check CHECK (
        country = '' OR country ~ '^[A-Z]{2}$'
    ),
    CONSTRAINT organization_article_trend_daily_counts_nonneg CHECK (
        search_count >= 0
        AND view_count >= 0
        AND post_view_count >= 0
        AND wishlist_add_count >= 0
        AND cart_add_count >= 0
        AND purchase_count >= 0
        AND purchase_quantity >= 0
        AND cart_abandon_count >= 0
        AND total_events >= 0
        AND trend_score >= 0
    )
);

COMMENT ON TABLE public.organization_article_trend_daily IS
    'Agregats journaliers des signaux customer par organisation/article/pays pour accelerer les tendances.';

CREATE INDEX IF NOT EXISTS idx_organization_article_trend_daily_org_day
    ON public.organization_article_trend_daily (organization_id, day DESC);

CREATE INDEX IF NOT EXISTS idx_organization_article_trend_daily_article_day
    ON public.organization_article_trend_daily (article_id, day DESC);

CREATE INDEX IF NOT EXISTS idx_organization_article_trend_daily_org_score
    ON public.organization_article_trend_daily (organization_id, trend_score DESC, day DESC);

CREATE OR REPLACE FUNCTION public.refresh_organization_article_trend_daily(
    p_start date DEFAULT (current_date - 90),
    p_end date DEFAULT current_date
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_rows integer := 0;
BEGIN
    IF p_start IS NULL OR p_end IS NULL THEN
        RAISE EXCEPTION 'p_start and p_end are required';
    END IF;

    IF p_start > p_end THEN
        RAISE EXCEPTION 'p_start must be <= p_end';
    END IF;

    DELETE FROM public.organization_article_trend_daily
    WHERE day >= p_start
      AND day <= p_end;

    INSERT INTO public.organization_article_trend_daily (
        organization_id,
        article_id,
        day,
        country,
        category,
        search_count,
        view_count,
        post_view_count,
        wishlist_add_count,
        cart_add_count,
        purchase_count,
        purchase_quantity,
        cart_abandon_count,
        total_events,
        trend_score,
        first_event_at,
        last_event_at,
        refreshed_at
    )
    SELECT
        e.organization_id,
        e.article_id,
        e.occurred_at::date AS day,
        COALESCE(NULLIF(e.country, ''), '') AS country,
        a.category AS category,
        COUNT(*) FILTER (WHERE e.event_type = 'search'::public.customer_article_trend_event_type_enum)::integer,
        COUNT(*) FILTER (WHERE e.event_type = 'view'::public.customer_article_trend_event_type_enum)::integer,
        COUNT(*) FILTER (WHERE e.event_type = 'post_view'::public.customer_article_trend_event_type_enum)::integer,
        COUNT(*) FILTER (WHERE e.event_type = 'wishlist_add'::public.customer_article_trend_event_type_enum)::integer,
        COUNT(*) FILTER (WHERE e.event_type = 'cart_add'::public.customer_article_trend_event_type_enum)::integer,
        COUNT(*) FILTER (WHERE e.event_type = 'purchase'::public.customer_article_trend_event_type_enum)::integer,
        SUM(
            CASE
                WHEN e.event_type = 'purchase'::public.customer_article_trend_event_type_enum
                 AND e.metadata ->> 'quantity' ~ '^[0-9]+$'
                THEN (e.metadata ->> 'quantity')::integer
                WHEN e.event_type = 'purchase'::public.customer_article_trend_event_type_enum
                THEN 1
                ELSE 0
            END
        )::integer AS purchase_quantity,
        COUNT(*) FILTER (WHERE e.event_type = 'cart_abandon'::public.customer_article_trend_event_type_enum)::integer,
        COUNT(*)::integer AS total_events,
        ROUND(SUM(e.weight), 2) AS trend_score,
        MIN(e.occurred_at) AS first_event_at,
        MAX(e.occurred_at) AS last_event_at,
        now() AS refreshed_at
    FROM public.customer_article_trend_events e
    INNER JOIN public.organization_articles a ON a.id = e.article_id
    WHERE e.article_id IS NOT NULL
      AND e.occurred_at >= p_start::timestamptz
      AND e.occurred_at < (p_end + 1)::timestamptz
    GROUP BY
        e.organization_id,
        e.article_id,
        e.occurred_at::date,
        COALESCE(NULLIF(e.country, ''), ''),
        a.category;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION public.refresh_organization_article_trend_daily(date, date) IS
    'Reconstruit les agregats de tendance journaliers sur une plage inclusive de dates.';

ALTER TABLE public.organization_article_trend_daily ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_article_trend_daily_select_member
    ON public.organization_article_trend_daily;
CREATE POLICY organization_article_trend_daily_select_member
    ON public.organization_article_trend_daily
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

REVOKE ALL ON public.organization_article_trend_daily FROM anon;
GRANT SELECT ON public.organization_article_trend_daily TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.organization_article_trend_daily TO service_role;
GRANT EXECUTE ON FUNCTION public.refresh_organization_article_trend_daily(date, date) TO service_role;
