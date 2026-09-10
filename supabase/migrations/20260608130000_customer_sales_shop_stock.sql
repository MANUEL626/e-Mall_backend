-- Ventes client rattachees a une boutique de vente.
-- Pickup/delivery reservent le stock boutique, la confirmation decremente stock + reservation,
-- et walk-in decremente directement le stock boutique.

ALTER TABLE public.organization_customer_sale_orders
    ADD COLUMN IF NOT EXISTS shop_id uuid REFERENCES public.organization_shops (id) ON DELETE RESTRICT;

UPDATE public.organization_customer_sale_orders o
SET shop_id = s.id
FROM public.organization_shops s
WHERE o.shop_id IS NULL
  AND s.organization_id = o.organization_id
  AND s.is_default IS TRUE
  AND s.shop_type = 'sales'::public.organization_shop_type_enum;

UPDATE public.organization_customer_sale_orders o
SET shop_id = s.id
FROM public.organization_shops s
WHERE o.shop_id IS NULL
  AND s.organization_id = o.organization_id
  AND s.shop_type = 'sales'::public.organization_shop_type_enum
  AND s.status <> 'archived'::public.organization_shop_status_enum;

ALTER TABLE public.organization_customer_sale_orders
    ALTER COLUMN shop_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ocso_org_shop_created
    ON public.organization_customer_sale_orders (organization_id, shop_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.organization_customer_sale_orders_check_shop()
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
                  MESSAGE = 'La vente doit viser une boutique de vente active de la meme organisation';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_customer_sale_orders_check_shop
    ON public.organization_customer_sale_orders;
CREATE TRIGGER trg_organization_customer_sale_orders_check_shop
    BEFORE INSERT OR UPDATE OF organization_id, shop_id
    ON public.organization_customer_sale_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_customer_sale_orders_check_shop();

CREATE OR REPLACE FUNCTION public.ocso_lines_after_insert_stock_effect()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org uuid;
    v_shop uuid;
    v_ff public.customer_sale_fulfillment_enum;
    v_st public.customer_sale_order_status_enum;
    avail integer;
BEGIN
    SELECT o.organization_id, o.shop_id, o.fulfillment_type, o.status
    INTO v_org, v_shop, v_ff, v_st
    FROM public.organization_customer_sale_orders o
    WHERE o.id = NEW.order_id;

    IF v_ff = 'walk_in_offline' THEN
        IF v_st <> 'completed'::public.customer_sale_order_status_enum THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Commande walk-in : statut doit etre completed a la creation des lignes';
        END IF;

        UPDATE public.organization_shop_article_stocks
        SET stock_quantity = stock_quantity - NEW.quantity
        WHERE organization_id = v_org
          AND shop_id = v_shop
          AND article_id = NEW.article_id
          AND stock_quantity - reserved_quantity >= NEW.quantity;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Stock insuffisant pour la vente magasin';
        END IF;

        PERFORM public.sync_legacy_article_stock_from_default_shop(
            v_org,
            v_shop,
            NEW.article_id
        );
        RETURN NEW;
    END IF;

    IF v_ff IN ('pickup', 'delivery') THEN
        IF v_st IN (
            'completed'::public.customer_sale_order_status_enum,
            'cancelled'::public.customer_sale_order_status_enum
        ) THEN
            RETURN NEW;
        END IF;

        SELECT stock_quantity - reserved_quantity
        INTO avail
        FROM public.organization_shop_article_stocks
        WHERE organization_id = v_org
          AND shop_id = v_shop
          AND article_id = NEW.article_id
        FOR UPDATE;

        IF avail IS NULL THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Article introuvable dans le stock de cette boutique';
        END IF;

        IF avail < NEW.quantity THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Stock disponible insuffisant dans cette boutique (reservations comprises)';
        END IF;

        UPDATE public.organization_shop_article_stocks
        SET reserved_quantity = reserved_quantity + NEW.quantity
        WHERE organization_id = v_org
          AND shop_id = v_shop
          AND article_id = NEW.article_id;

        PERFORM public.sync_legacy_article_stock_from_default_shop(
            v_org,
            v_shop,
            NEW.article_id
        );
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.ocso_order_release_reservations_on_cancel()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    r_line RECORD;
BEGIN
    IF NEW.status = 'cancelled'::public.customer_sale_order_status_enum
       AND OLD.status IS DISTINCT FROM 'cancelled'::public.customer_sale_order_status_enum
       AND OLD.status <> 'completed'::public.customer_sale_order_status_enum
       AND OLD.fulfillment_type IN (
           'pickup'::public.customer_sale_fulfillment_enum,
           'delivery'::public.customer_sale_fulfillment_enum
       ) THEN
        FOR r_line IN
            SELECT article_id, quantity
            FROM public.organization_customer_sale_order_lines
            WHERE order_id = NEW.id
        LOOP
            UPDATE public.organization_shop_article_stocks
            SET reserved_quantity = reserved_quantity - r_line.quantity
            WHERE organization_id = NEW.organization_id
              AND shop_id = NEW.shop_id
              AND article_id = r_line.article_id
              AND reserved_quantity >= r_line.quantity;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    USING ERRCODE = '23514',
                          MESSAGE = 'Incoherence reservation a l annulation';
            END IF;

            PERFORM public.sync_legacy_article_stock_from_default_shop(
                NEW.organization_id,
                NEW.shop_id,
                r_line.article_id
            );
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_customer_sale_receipt(
    p_order_id uuid,
    p_note text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    r_order public.organization_customer_sale_orders%ROWTYPE;
    r_line RECORD;
    updated_cnt integer;
BEGIN
    SELECT *
    INTO r_order
    FROM public.organization_customer_sale_orders
    WHERE id = p_order_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'Commande introuvable';
    END IF;

    IF r_order.fulfillment_type = 'walk_in_offline' THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'Flux non applicable';
    END IF;

    IF r_order.status IN (
        'completed'::public.customer_sale_order_status_enum,
        'cancelled'::public.customer_sale_order_status_enum
    ) THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'Commande deja cloturee';
    END IF;

    FOR r_line IN
        SELECT article_id, quantity
        FROM public.organization_customer_sale_order_lines
        WHERE order_id = p_order_id
    LOOP
        UPDATE public.organization_shop_article_stocks
        SET
            reserved_quantity = reserved_quantity - r_line.quantity,
            stock_quantity = stock_quantity - r_line.quantity
        WHERE organization_id = r_order.organization_id
          AND shop_id = r_order.shop_id
          AND article_id = r_line.article_id
          AND reserved_quantity >= r_line.quantity
          AND stock_quantity >= r_line.quantity;

        GET DIAGNOSTICS updated_cnt = ROW_COUNT;
        IF updated_cnt <> 1 THEN
            RAISE EXCEPTION
                USING ERRCODE = 'P0001',
                      MESSAGE = 'Stock ou reservation incoherente pour l article';
        END IF;

        PERFORM public.sync_legacy_article_stock_from_default_shop(
            r_order.organization_id,
            r_order.shop_id,
            r_line.article_id
        );
    END LOOP;

    UPDATE public.organization_customer_sale_orders
    SET
        status = 'completed'::public.customer_sale_order_status_enum,
        updated_at = now()
    WHERE id = p_order_id;

    INSERT INTO public.organization_customer_sale_order_status_events (
        order_id,
        from_status,
        to_status,
        note,
        created_by_user_id
    )
    VALUES (
        p_order_id,
        r_order.status,
        'completed'::public.customer_sale_order_status_enum,
        NULLIF(btrim(p_note), ''),
        NULL
    );
END;
$$;

COMMENT ON COLUMN public.organization_customer_sale_orders.shop_id IS
    'Boutique de vente qui porte la reservation/decrementation du stock.';
