-- Liste de souhaits et paniers par organisation (client).

CREATE TABLE IF NOT EXISTS public.customer_wishlist_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid NOT NULL REFERENCES public.customers (id) ON DELETE CASCADE,
    organization_article_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_wishlist UNIQUE (customer_id, organization_article_id)
);

COMMENT ON TABLE public.customer_wishlist_items IS
    'Produits marqués en favori par un client (un article par ligne).';

CREATE INDEX IF NOT EXISTS idx_customer_wishlist_items_customer
    ON public.customer_wishlist_items (customer_id);

CREATE TABLE IF NOT EXISTS public.customer_carts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid NOT NULL REFERENCES public.customers (id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_cart_per_org UNIQUE (customer_id, organization_id)
);

COMMENT ON TABLE public.customer_carts IS
    'Panier d''achat par couple (client, organisation marchande).';

CREATE INDEX IF NOT EXISTS idx_customer_carts_customer
    ON public.customer_carts (customer_id);

CREATE TABLE IF NOT EXISTS public.customer_cart_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id uuid NOT NULL REFERENCES public.customer_carts (id) ON DELETE CASCADE,
    organization_article_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE CASCADE,
    quantity integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_cart_line UNIQUE (cart_id, organization_article_id),
    CONSTRAINT customer_cart_items_quantity_pos CHECK (quantity >= 1)
);

COMMENT ON TABLE public.customer_cart_items IS
    'Ligne de panier : article et quantité ; l''article doit appartenir à l''organisation du panier.';

CREATE INDEX IF NOT EXISTS idx_customer_cart_items_cart
    ON public.customer_cart_items (cart_id);

-- Cohérence : l'article appartient à la même organisation que le panier.
CREATE OR REPLACE FUNCTION public.customer_cart_items_enforce_article_org()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_article_org uuid;
    v_cart_org uuid;
BEGIN
    SELECT organization_id INTO v_article_org
    FROM public.organization_articles
    WHERE id = NEW.organization_article_id;

    IF v_article_org IS NULL THEN
        RAISE EXCEPTION 'Article introuvable';
    END IF;

    SELECT organization_id INTO v_cart_org
    FROM public.customer_carts
    WHERE id = NEW.cart_id;

    IF v_cart_org IS NULL THEN
        RAISE EXCEPTION 'Panier introuvable';
    END IF;

    IF v_article_org IS DISTINCT FROM v_cart_org THEN
        RAISE EXCEPTION 'L''article n''appartient pas à l''organisation du panier';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_cart_items_org ON public.customer_cart_items;
CREATE TRIGGER trg_customer_cart_items_org
    BEFORE INSERT OR UPDATE OF organization_article_id, cart_id ON public.customer_cart_items
    FOR EACH ROW
    EXECUTE FUNCTION public.customer_cart_items_enforce_article_org();

CREATE OR REPLACE FUNCTION public.touch_customer_carts_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    UPDATE public.customer_carts
    SET updated_at = now()
    WHERE id = COALESCE(NEW.cart_id, OLD.cart_id);
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_cart_items_touch_cart ON public.customer_cart_items;
CREATE TRIGGER trg_customer_cart_items_touch_cart
    AFTER INSERT OR UPDATE OR DELETE ON public.customer_cart_items
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_customer_carts_updated_at();

CREATE OR REPLACE FUNCTION public.touch_customer_cart_items_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_cart_items_updated_at ON public.customer_cart_items;
CREATE TRIGGER trg_customer_cart_items_updated_at
    BEFORE UPDATE ON public.customer_cart_items
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_customer_cart_items_updated_at();

ALTER TABLE public.customer_wishlist_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_carts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_cart_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS customer_wishlist_items_own ON public.customer_wishlist_items;
CREATE POLICY customer_wishlist_items_own
    ON public.customer_wishlist_items
    FOR ALL
    TO authenticated
    USING (
        customer_id IN (SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid())
    )
    WITH CHECK (
        customer_id IN (SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid())
    );

DROP POLICY IF EXISTS customer_carts_own ON public.customer_carts;
CREATE POLICY customer_carts_own
    ON public.customer_carts
    FOR ALL
    TO authenticated
    USING (
        customer_id IN (SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid())
    )
    WITH CHECK (
        customer_id IN (SELECT c.id FROM public.customers c WHERE c.user_id = auth.uid())
    );

DROP POLICY IF EXISTS customer_cart_items_own ON public.customer_cart_items;
CREATE POLICY customer_cart_items_own
    ON public.customer_cart_items
    FOR ALL
    TO authenticated
    USING (
        cart_id IN (
            SELECT cc.id
            FROM public.customer_carts cc
            INNER JOIN public.customers c ON c.id = cc.customer_id
            WHERE c.user_id = auth.uid()
        )
    )
    WITH CHECK (
        cart_id IN (
            SELECT cc.id
            FROM public.customer_carts cc
            INNER JOIN public.customers c ON c.id = cc.customer_id
            WHERE c.user_id = auth.uid()
        )
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.customer_wishlist_items TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.customer_carts TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.customer_cart_items TO authenticated;
