-- Phase 5 : contexte boutique pour catalogue customer, paniers et tendances.

CREATE OR REPLACE FUNCTION public.default_sales_shop_id_for_org(p_organization_id uuid)
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT s.id
    FROM public.organization_shops s
    WHERE s.organization_id = p_organization_id
      AND s.shop_type = 'sales'::public.organization_shop_type_enum
      AND s.status <> 'archived'::public.organization_shop_status_enum
    ORDER BY s.is_default DESC, s.created_at ASC
    LIMIT 1
$$;

ALTER TABLE public.customer_carts
    ADD COLUMN IF NOT EXISTS shop_id uuid REFERENCES public.organization_shops (id) ON DELETE CASCADE;

UPDATE public.customer_carts c
SET shop_id = public.default_sales_shop_id_for_org(c.organization_id)
WHERE c.shop_id IS NULL;

ALTER TABLE public.customer_carts
    ALTER COLUMN shop_id SET NOT NULL;

ALTER TABLE public.customer_carts
    DROP CONSTRAINT IF EXISTS uq_customer_cart_per_org;

ALTER TABLE public.customer_carts
    ADD CONSTRAINT uq_customer_cart_per_org_shop UNIQUE (
        customer_id,
        organization_id,
        shop_id
    );

CREATE INDEX IF NOT EXISTS idx_customer_carts_customer_org_shop
    ON public.customer_carts (customer_id, organization_id, shop_id);

CREATE OR REPLACE FUNCTION public.customer_carts_check_shop_org()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_shop_org uuid;
    v_shop_type public.organization_shop_type_enum;
    v_shop_status public.organization_shop_status_enum;
BEGIN
    SELECT organization_id, shop_type, status
    INTO v_shop_org, v_shop_type, v_shop_status
    FROM public.organization_shops
    WHERE id = NEW.shop_id;

    IF v_shop_org IS NULL
       OR v_shop_org <> NEW.organization_id
       OR v_shop_type <> 'sales'::public.organization_shop_type_enum
       OR v_shop_status = 'archived'::public.organization_shop_status_enum THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'Le panier customer doit viser une boutique de vente active de la meme organisation';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_carts_check_shop_org
    ON public.customer_carts;
CREATE TRIGGER trg_customer_carts_check_shop_org
    BEFORE INSERT OR UPDATE OF organization_id, shop_id
    ON public.customer_carts
    FOR EACH ROW
    EXECUTE FUNCTION public.customer_carts_check_shop_org();

ALTER TABLE public.customer_article_trend_events
    ADD COLUMN IF NOT EXISTS shop_id uuid REFERENCES public.organization_shops (id) ON DELETE SET NULL;

UPDATE public.customer_article_trend_events e
SET shop_id = public.default_sales_shop_id_for_org(e.organization_id)
WHERE e.shop_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_customer_article_trend_events_shop
    ON public.customer_article_trend_events (organization_id, shop_id, occurred_at DESC);

COMMENT ON COLUMN public.customer_carts.shop_id IS
    'Boutique sales visee par ce panier. Un customer peut avoir un panier par organisation et boutique.';

COMMENT ON COLUMN public.customer_article_trend_events.shop_id IS
    'Boutique sales concernee par le signal tendance customer, si connue.';
