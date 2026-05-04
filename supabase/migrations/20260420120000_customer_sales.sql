-- Ventes client : enums, customer_params, commandes, lignes, historique, réservations, tokens QR, RLS, RPC finalize.

-- ============================
-- ENUMS
-- ============================
DO $$
BEGIN
    CREATE TYPE public.customer_sale_fulfillment_enum AS ENUM (
        'pickup',
        'delivery',
        'walk_in_offline'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE public.customer_sale_order_status_enum AS ENUM (
        'pending',
        'in_progress',
        'in_delivery',
        'cancelled',
        'completed'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- ============================
-- customer_params (1:1 customers)
-- ============================
CREATE TABLE IF NOT EXISTS public.customer_params (
    customer_id uuid PRIMARY KEY REFERENCES public.customers (id) ON DELETE CASCADE,
    locale text NOT NULL DEFAULT 'fr',
    default_longitude double precision,
    default_latitude double precision,
    extra jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.touch_customer_params_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_customer_params_updated_at ON public.customer_params;
CREATE TRIGGER trg_customer_params_updated_at
    BEFORE UPDATE ON public.customer_params
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_customer_params_updated_at();

-- ============================
-- organization_customer_sale_orders
-- ============================
CREATE TABLE IF NOT EXISTS public.organization_customer_sale_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    fulfillment_type public.customer_sale_fulfillment_enum NOT NULL,
    customer_id uuid REFERENCES public.customers (id) ON DELETE RESTRICT,
    status public.customer_sale_order_status_enum NOT NULL DEFAULT 'pending',
    assigned_delivery_member_id uuid REFERENCES public.members (id) ON DELETE SET NULL,
    delivery_longitude double precision,
    delivery_latitude double precision,
    currency text DEFAULT 'XOF',
    notes text,
    external_customer_label text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_customer_sale_orders_customer_walk_in CHECK (
        (
            fulfillment_type <> 'walk_in_offline'::public.customer_sale_fulfillment_enum
            AND customer_id IS NOT NULL
        )
        OR (fulfillment_type = 'walk_in_offline'::public.customer_sale_fulfillment_enum)
    ),
    CONSTRAINT organization_customer_sale_orders_delivery_coords CHECK (
        fulfillment_type <> 'delivery'::public.customer_sale_fulfillment_enum
        OR (
            delivery_longitude IS NOT NULL
            AND delivery_latitude IS NOT NULL
        )
    )
);

CREATE OR REPLACE FUNCTION public.touch_organization_customer_sale_orders_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_customer_sale_orders_updated_at
    ON public.organization_customer_sale_orders;
CREATE TRIGGER trg_organization_customer_sale_orders_updated_at
    BEFORE UPDATE ON public.organization_customer_sale_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_customer_sale_orders_updated_at();

CREATE INDEX IF NOT EXISTS idx_ocso_org
    ON public.organization_customer_sale_orders (organization_id);
CREATE INDEX IF NOT EXISTS idx_ocso_customer
    ON public.organization_customer_sale_orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_ocso_org_status
    ON public.organization_customer_sale_orders (organization_id, status);

-- ============================
-- organization_customer_sale_order_lines
-- ============================
CREATE TABLE IF NOT EXISTS public.organization_customer_sale_order_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL REFERENCES public.organization_customer_sale_orders (id) ON DELETE CASCADE,
    article_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE RESTRICT,
    quantity integer NOT NULL,
    unit_price_snapshot numeric(14, 2) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_customer_sale_order_lines_qty_pos CHECK (quantity > 0),
    CONSTRAINT organization_customer_sale_order_lines_price_nonneg CHECK (unit_price_snapshot >= 0),
    CONSTRAINT uq_ocso_lines_order_article UNIQUE (order_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_ocso_lines_order
    ON public.organization_customer_sale_order_lines (order_id);

-- Ligne d’article même organisation que la commande
CREATE OR REPLACE FUNCTION public.ocso_lines_check_article_org()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.organization_articles a
        INNER JOIN public.organization_customer_sale_orders o ON o.id = NEW.order_id
        WHERE a.id = NEW.article_id
          AND a.organization_id = o.organization_id
    ) THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'L''article n''appartient pas à l''organisation de la commande';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ocso_lines_check_article_org ON public.organization_customer_sale_order_lines;
CREATE TRIGGER trg_ocso_lines_check_article_org
    BEFORE INSERT OR UPDATE OF order_id, article_id ON public.organization_customer_sale_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.ocso_lines_check_article_org();

-- Réservation / décrément selon type de commande
CREATE OR REPLACE FUNCTION public.ocso_lines_after_insert_stock_effect()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org uuid;
    v_ff public.customer_sale_fulfillment_enum;
    v_st public.customer_sale_order_status_enum;
    avail integer;
BEGIN
    SELECT o.organization_id, o.fulfillment_type, o.status
    INTO v_org, v_ff, v_st
    FROM public.organization_customer_sale_orders o
    WHERE o.id = NEW.order_id;

    IF v_ff = 'walk_in_offline' THEN
        IF v_st <> 'completed' THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Commande walk-in : statut doit être completed à la création des lignes';
        END IF;
        UPDATE public.organization_articles
        SET
            stock_quantity = stock_quantity - NEW.quantity,
            updated_at = now()
        WHERE id = NEW.article_id
          AND organization_id = v_org
          AND stock_quantity >= NEW.quantity;
        IF NOT FOUND THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Stock insuffisant pour la vente magasin';
        END IF;
        RETURN NEW;
    END IF;

    IF v_ff IN ('pickup', 'delivery') THEN
        IF v_st IN ('completed', 'cancelled') THEN
            RETURN NEW;
        END IF;
        SELECT a.stock_quantity - a.reserved_quantity
        INTO avail
        FROM public.organization_articles a
        WHERE a.id = NEW.article_id
          AND a.organization_id = v_org
        FOR UPDATE;
        IF avail IS NULL THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Article introuvable';
        END IF;
        IF avail < NEW.quantity THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Stock disponible insuffisant (réservations comprises)';
        END IF;
        UPDATE public.organization_articles
        SET
            reserved_quantity = reserved_quantity + NEW.quantity,
            updated_at = now()
        WHERE id = NEW.article_id
          AND organization_id = v_org;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ocso_lines_after_insert_stock ON public.organization_customer_sale_order_lines;
CREATE TRIGGER trg_ocso_lines_after_insert_stock
    AFTER INSERT ON public.organization_customer_sale_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.ocso_lines_after_insert_stock_effect();

-- Libère les réservations à l’annulation
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
            UPDATE public.organization_articles
            SET
                reserved_quantity = reserved_quantity - r_line.quantity,
                updated_at = now()
            WHERE id = r_line.article_id
              AND organization_id = NEW.organization_id
              AND reserved_quantity >= r_line.quantity;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    USING ERRCODE = '23514',
                          MESSAGE = 'Incohérence réservation à l''annulation';
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ocso_order_release_on_cancel ON public.organization_customer_sale_orders;
CREATE TRIGGER trg_ocso_order_release_on_cancel
    AFTER UPDATE OF status ON public.organization_customer_sale_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.ocso_order_release_reservations_on_cancel();

-- ============================
-- reserved_quantity sur organization_articles
-- ============================
ALTER TABLE public.organization_articles
    ADD COLUMN IF NOT EXISTS reserved_quantity integer NOT NULL DEFAULT 0;

ALTER TABLE public.organization_articles DROP CONSTRAINT IF EXISTS organization_articles_reserved_nonneg;
ALTER TABLE public.organization_articles
    ADD CONSTRAINT organization_articles_reserved_nonneg CHECK (reserved_quantity >= 0);

ALTER TABLE public.organization_articles DROP CONSTRAINT IF EXISTS organization_articles_stock_covers_reserved;
ALTER TABLE public.organization_articles
    ADD CONSTRAINT organization_articles_stock_covers_reserved CHECK (stock_quantity >= reserved_quantity);

COMMENT ON COLUMN public.organization_articles.reserved_quantity IS
    'Quantité réservée par des commandes vente client non finalisées (pickup/delivery).';

-- ============================
-- Historique des statuts
-- ============================
CREATE TABLE IF NOT EXISTS public.organization_customer_sale_order_status_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL REFERENCES public.organization_customer_sale_orders (id) ON DELETE CASCADE,
    from_status public.customer_sale_order_status_enum,
    to_status public.customer_sale_order_status_enum NOT NULL,
    note text,
    created_by_user_id uuid REFERENCES auth.users (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ocso_status_events_order
    ON public.organization_customer_sale_order_status_events (order_id, created_at);

-- ============================
-- Tokens QR (hash uniquement)
-- ============================
CREATE TABLE IF NOT EXISTS public.customer_sale_order_receipt_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE REFERENCES public.organization_customer_sale_orders (id) ON DELETE CASCADE,
    secret_hash text NOT NULL,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================
-- RPC : finalisation après scan client (pickup / delivery)
-- ============================
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
                  MESSAGE = 'Commande déjà clôturée';
    END IF;

    FOR r_line IN
        SELECT article_id, quantity
        FROM public.organization_customer_sale_order_lines
        WHERE order_id = p_order_id
    LOOP
        UPDATE public.organization_articles
        SET
            reserved_quantity = reserved_quantity - r_line.quantity,
            stock_quantity = stock_quantity - r_line.quantity,
            updated_at = now()
        WHERE id = r_line.article_id
          AND organization_id = r_order.organization_id
          AND reserved_quantity >= r_line.quantity
          AND stock_quantity >= r_line.quantity;
        GET DIAGNOSTICS updated_cnt = ROW_COUNT;
        IF updated_cnt <> 1 THEN
            RAISE EXCEPTION
                USING ERRCODE = 'P0001',
                      MESSAGE = 'Stock ou réservation incohérente pour l''article';
        END IF;
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

COMMENT ON FUNCTION public.finalize_customer_sale_receipt(uuid, text) IS
    'Libère réservations et décrémente le stock physique ; passe la commande en completed. Appeler après vérif secret QR + JWT côté backend.';

GRANT EXECUTE ON FUNCTION public.finalize_customer_sale_receipt(uuid, text) TO service_role;

-- ============================
-- Helpers RLS
-- ============================
CREATE OR REPLACE FUNCTION public.is_customer_self(p_customer_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.customers c
        WHERE c.id = p_customer_id
          AND c.user_id = auth.uid()
    );
$$;

-- ============================
-- RLS
-- ============================
ALTER TABLE public.customer_params ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_customer_sale_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_customer_sale_order_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_customer_sale_order_status_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_sale_order_receipt_tokens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS customer_params_select_self ON public.customer_params;
CREATE POLICY customer_params_select_self
    ON public.customer_params
    FOR SELECT
    TO authenticated
    USING (public.is_customer_self(customer_id));

DROP POLICY IF EXISTS customer_params_insert_self ON public.customer_params;
CREATE POLICY customer_params_insert_self
    ON public.customer_params
    FOR INSERT
    TO authenticated
    WITH CHECK (public.is_customer_self(customer_id));

DROP POLICY IF EXISTS customer_params_update_self ON public.customer_params;
CREATE POLICY customer_params_update_self
    ON public.customer_params
    FOR UPDATE
    TO authenticated
    USING (public.is_customer_self(customer_id))
    WITH CHECK (public.is_customer_self(customer_id));

DROP POLICY IF EXISTS ocso_select_customer ON public.organization_customer_sale_orders;
CREATE POLICY ocso_select_customer
    ON public.organization_customer_sale_orders
    FOR SELECT
    TO authenticated
    USING (
        customer_id IS NOT NULL
        AND public.is_customer_self(customer_id)
    );

DROP POLICY IF EXISTS ocso_select_member ON public.organization_customer_sale_orders;
CREATE POLICY ocso_select_member
    ON public.organization_customer_sale_orders
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS ocso_lines_select_customer ON public.organization_customer_sale_order_lines;
CREATE POLICY ocso_lines_select_customer
    ON public.organization_customer_sale_order_lines
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_customer_sale_orders o
            WHERE o.id = order_id
              AND o.customer_id IS NOT NULL
              AND public.is_customer_self(o.customer_id)
        )
    );

DROP POLICY IF EXISTS ocso_lines_select_member ON public.organization_customer_sale_order_lines;
CREATE POLICY ocso_lines_select_member
    ON public.organization_customer_sale_order_lines
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_customer_sale_orders o
            WHERE o.id = order_id
              AND public.is_org_member(o.organization_id)
        )
    );

DROP POLICY IF EXISTS ocso_events_select_customer ON public.organization_customer_sale_order_status_events;
CREATE POLICY ocso_events_select_customer
    ON public.organization_customer_sale_order_status_events
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_customer_sale_orders o
            WHERE o.id = order_id
              AND o.customer_id IS NOT NULL
              AND public.is_customer_self(o.customer_id)
        )
    );

DROP POLICY IF EXISTS ocso_events_select_member ON public.organization_customer_sale_order_status_events;
CREATE POLICY ocso_events_select_member
    ON public.organization_customer_sale_order_status_events
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_customer_sale_orders o
            WHERE o.id = order_id
              AND public.is_org_member(o.organization_id)
        )
    );

-- Pas d’accès direct aux tokens pour authenticated (uniquement service_role / backend)
DROP POLICY IF EXISTS receipt_tokens_deny_all ON public.customer_sale_order_receipt_tokens;
CREATE POLICY receipt_tokens_deny_all
    ON public.customer_sale_order_receipt_tokens
    FOR ALL
    TO authenticated
    USING (false)
    WITH CHECK (false);
