-- Commandes fournisseur rattachees a une boutique de vente.
-- La reception augmente le stock de la boutique cible, puis synchronise le stock legacy
-- seulement si la boutique cible est la boutique par defaut.

ALTER TABLE public.organization_article_orders
    ADD COLUMN IF NOT EXISTS shop_id uuid REFERENCES public.organization_shops (id) ON DELETE RESTRICT;

UPDATE public.organization_article_orders o
SET shop_id = s.id
FROM public.organization_shops s
WHERE o.shop_id IS NULL
  AND s.organization_id = o.organization_id
  AND s.is_default IS TRUE
  AND s.shop_type = 'sales'::public.organization_shop_type_enum;

UPDATE public.organization_article_orders o
SET shop_id = s.id
FROM public.organization_shops s
WHERE o.shop_id IS NULL
  AND s.organization_id = o.organization_id
  AND s.shop_type = 'sales'::public.organization_shop_type_enum
  AND s.status <> 'archived'::public.organization_shop_status_enum;

ALTER TABLE public.organization_article_orders
    ALTER COLUMN shop_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_organization_article_orders_org_shop
    ON public.organization_article_orders (organization_id, shop_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.organization_article_orders_check_shop()
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
                  MESSAGE = 'La commande fournisseur doit viser une boutique de vente active de la meme organisation';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_article_orders_check_shop
    ON public.organization_article_orders;
CREATE TRIGGER trg_organization_article_orders_check_shop
    BEFORE INSERT OR UPDATE OF organization_id, shop_id
    ON public.organization_article_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_orders_check_shop();

CREATE OR REPLACE FUNCTION public.sync_legacy_article_stock_from_default_shop(
    p_organization_id uuid,
    p_shop_id uuid,
    p_article_id uuid
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_is_default boolean;
    v_stock integer;
    v_alert integer;
BEGIN
    SELECT is_default
    INTO v_is_default
    FROM public.organization_shops
    WHERE id = p_shop_id
      AND organization_id = p_organization_id;

    IF v_is_default IS NOT TRUE THEN
        RETURN;
    END IF;

    SELECT stock_quantity, alert_quantity
    INTO v_stock, v_alert
    FROM public.organization_shop_article_stocks
    WHERE organization_id = p_organization_id
      AND shop_id = p_shop_id
      AND article_id = p_article_id;

    IF FOUND THEN
        UPDATE public.organization_articles
        SET
            stock_quantity = v_stock,
            alert_quantity = v_alert
        WHERE id = p_article_id
          AND organization_id = p_organization_id;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_article_order_lines_apply_received_stock()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    delta integer := 0;
    v_order_org uuid;
    v_order_shop uuid;
BEGIN
    SELECT o.organization_id, o.shop_id
    INTO v_order_org, v_order_shop
    FROM public.organization_article_orders o
    WHERE o.id = NEW.order_id;

    IF TG_OP = 'INSERT' AND NEW.quantity_received IS NOT NULL THEN
        delta := NEW.quantity_received;
    ELSIF TG_OP = 'UPDATE'
          AND NEW.quantity_received IS DISTINCT FROM OLD.quantity_received
          AND NEW.quantity_received IS NOT NULL THEN
        delta := COALESCE(NEW.quantity_received, 0) - COALESCE(OLD.quantity_received, 0);
    END IF;

    IF delta <> 0 THEN
        INSERT INTO public.organization_shop_article_stocks (
            organization_id,
            shop_id,
            article_id,
            stock_scope,
            stock_quantity,
            reserved_quantity,
            alert_quantity,
            active
        )
        SELECT
            v_order_org,
            v_order_shop,
            NEW.article_id,
            'sales_item'::public.organization_stock_scope_enum,
            0,
            0,
            COALESCE(a.alert_quantity, 0),
            a.active
        FROM public.organization_articles a
        WHERE a.id = NEW.article_id
          AND a.organization_id = v_order_org
        ON CONFLICT (shop_id, article_id) DO NOTHING;

        UPDATE public.organization_shop_article_stocks
        SET stock_quantity = stock_quantity + delta
        WHERE organization_id = v_order_org
          AND shop_id = v_order_shop
          AND article_id = NEW.article_id;

        PERFORM public.sync_legacy_article_stock_from_default_shop(
            v_order_org,
            v_order_shop,
            NEW.article_id
        );
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_article_order_lines_revert_stock_on_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_order_org uuid;
    v_order_shop uuid;
BEGIN
    IF OLD.quantity_received IS NOT NULL AND OLD.quantity_received <> 0 THEN
        SELECT o.organization_id, o.shop_id
        INTO v_order_org, v_order_shop
        FROM public.organization_article_orders o
        WHERE o.id = OLD.order_id;

        UPDATE public.organization_shop_article_stocks
        SET stock_quantity = stock_quantity - OLD.quantity_received
        WHERE organization_id = v_order_org
          AND shop_id = v_order_shop
          AND article_id = OLD.article_id;

        PERFORM public.sync_legacy_article_stock_from_default_shop(
            v_order_org,
            v_order_shop,
            OLD.article_id
        );
    END IF;

    RETURN OLD;
END;
$$;

COMMENT ON COLUMN public.organization_article_orders.shop_id IS
    'Boutique de vente qui receptionne cette commande fournisseur.';
