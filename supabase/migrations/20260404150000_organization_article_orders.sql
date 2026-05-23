-- Commandes d'approvisionnement d'articles : lignes commandées, réception avec écart + motif,
-- ajout au stock = quantité réceptionnée (trigger).

DO $$
BEGIN
    CREATE TYPE public.article_order_status_enum AS ENUM ('open', 'received', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.touch_organization_article_orders_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_article_orders_block_cancel_if_received()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'cancelled'::public.article_order_status_enum
       AND OLD.status IS DISTINCT FROM 'cancelled'::public.article_order_status_enum THEN
        IF EXISTS (
            SELECT 1
            FROM public.organization_article_order_lines l
            WHERE l.order_id = NEW.id
              AND l.quantity_received IS NOT NULL
        ) THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Impossible d''annuler une commande déjà réceptionnée';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- L'article doit appartenir à la même organisation que la commande.
CREATE OR REPLACE FUNCTION public.organization_article_order_lines_check_article_org()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.organization_articles a
        INNER JOIN public.organization_article_orders o ON o.id = NEW.order_id
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

-- Date de réception lors du premier renseignement de quantité réceptionnée.
CREATE OR REPLACE FUNCTION public.organization_article_order_lines_set_received_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.quantity_received IS NOT NULL AND NEW.received_at IS NULL THEN
            NEW.received_at := now();
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.quantity_received IS NULL
           AND NEW.quantity_received IS NOT NULL
           AND NEW.received_at IS NULL THEN
            NEW.received_at := now();
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- Ajoute au stock la variation de quantité réceptionnée (delta si correction ultérieure).
CREATE OR REPLACE FUNCTION public.organization_article_order_lines_apply_received_stock()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org_id uuid;
    v_status public.article_order_status_enum;
    delta integer;
    updated_count integer;
BEGIN
    SELECT o.organization_id, o.status
    INTO v_org_id, v_status
    FROM public.organization_article_orders o
    WHERE o.id = NEW.order_id;

    IF v_status = 'cancelled'::public.article_order_status_enum THEN
        IF TG_OP = 'INSERT' AND NEW.quantity_received IS NOT NULL THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Réception impossible sur une commande annulée';
        END IF;
        IF TG_OP = 'UPDATE'
           AND NEW.quantity_received IS DISTINCT FROM OLD.quantity_received
           AND NEW.quantity_received IS NOT NULL THEN
            RAISE EXCEPTION
                USING ERRCODE = '23514',
                      MESSAGE = 'Réception impossible sur une commande annulée';
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.quantity_received IS NOT NULL AND NEW.quantity_received <> 0 THEN
            UPDATE public.organization_articles
            SET
                stock_quantity = stock_quantity + NEW.quantity_received,
                updated_at = now()
            WHERE id = NEW.article_id
              AND organization_id = v_org_id;
            GET DIAGNOSTICS updated_count = ROW_COUNT;
            IF updated_count <> 1 THEN
                RAISE EXCEPTION
                    USING ERRCODE = '23503',
                          MESSAGE = 'Article introuvable pour cette organisation';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        delta :=
            COALESCE(NEW.quantity_received, 0) - COALESCE(OLD.quantity_received, 0);
        IF delta <> 0 THEN
            UPDATE public.organization_articles
            SET
                stock_quantity = stock_quantity + delta,
                updated_at = now()
            WHERE id = NEW.article_id
              AND organization_id = v_org_id;
            GET DIAGNOSTICS updated_count = ROW_COUNT;
            IF updated_count <> 1 THEN
                RAISE EXCEPTION
                    USING ERRCODE = '23503',
                          MESSAGE = 'Article introuvable pour cette organisation';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    RETURN NEW;
END;
$$;

-- Passe la commande en « received » quand chaque ligne a une quantité réceptionnée renseignée.
CREATE OR REPLACE FUNCTION public.organization_article_order_lines_sync_order_status()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    total_lines integer;
    lines_with_reception integer;
BEGIN
    SELECT
        count(*)::integer,
        count(*) FILTER (WHERE quantity_received IS NOT NULL)::integer
    INTO total_lines, lines_with_reception
    FROM public.organization_article_order_lines
    WHERE order_id = NEW.order_id;

    IF total_lines > 0 AND total_lines = lines_with_reception THEN
        UPDATE public.organization_article_orders
        SET
            status = 'received'::public.article_order_status_enum,
            updated_at = now()
        WHERE id = NEW.order_id
          AND status = 'open'::public.article_order_status_enum;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.organization_article_order_lines_touch_parent_order()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE public.organization_article_orders
    SET updated_at = now()
    WHERE id = COALESCE(NEW.order_id, OLD.order_id);
    RETURN COALESCE(NEW, OLD);
END;
$$;

-- Retire du stock ce qui avait été ajouté lors de la suppression d'une ligne réceptionnée.
CREATE OR REPLACE FUNCTION public.organization_article_order_lines_revert_stock_on_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org_id uuid;
    updated_count integer;
BEGIN
    IF OLD.quantity_received IS NOT NULL AND OLD.quantity_received <> 0 THEN
        SELECT o.organization_id
        INTO v_org_id
        FROM public.organization_article_orders o
        WHERE o.id = OLD.order_id;

        UPDATE public.organization_articles
        SET
            stock_quantity = stock_quantity - OLD.quantity_received,
            updated_at = now()
        WHERE id = OLD.article_id
          AND organization_id = v_org_id;
        GET DIAGNOSTICS updated_count = ROW_COUNT;
        IF updated_count <> 1 THEN
            RAISE EXCEPTION
                USING ERRCODE = '23503',
                      MESSAGE = 'Impossible d''ajuster le stock à la suppression de la ligne';
        END IF;
    END IF;
    RETURN OLD;
END;
$$;

CREATE TABLE IF NOT EXISTS public.organization_article_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    status public.article_order_status_enum NOT NULL DEFAULT 'open',
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.organization_article_orders IS
    'Commande fournisseur interne : réception met à jour le stock des articles.';

CREATE TABLE IF NOT EXISTS public.organization_article_order_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL REFERENCES public.organization_article_orders (id) ON DELETE CASCADE,
    article_id uuid NOT NULL REFERENCES public.organization_articles (id) ON DELETE RESTRICT,
    quantity_ordered integer NOT NULL,
    quantity_received integer,
    shortage_reason text,
    received_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_article_order_lines_qty_ordered_pos CHECK (quantity_ordered > 0),
    CONSTRAINT organization_article_order_lines_qty_received_nonneg CHECK (
        quantity_received IS NULL OR quantity_received >= 0
    ),
    CONSTRAINT organization_article_order_lines_received_le_ordered CHECK (
        quantity_received IS NULL OR quantity_received <= quantity_ordered
    ),
    CONSTRAINT organization_article_order_lines_shortage_reason CHECK (
        quantity_received IS NULL
        OR quantity_received >= quantity_ordered
        OR (
            shortage_reason IS NOT NULL
            AND btrim(shortage_reason) <> ''
        )
    ),
    CONSTRAINT uq_organization_article_order_lines_order_article UNIQUE (order_id, article_id)
);

COMMENT ON COLUMN public.organization_article_order_lines.quantity_received IS
    'Renseigné à la réception ; ajoutée au stock (peut être < commandée : casse, perte, etc.).';

COMMENT ON COLUMN public.organization_article_order_lines.shortage_reason IS
    'Obligatoire si quantité réceptionnée < quantité commandée (ex. casse en route).';

DROP TRIGGER IF EXISTS trg_organization_article_orders_updated_at ON public.organization_article_orders;
CREATE TRIGGER trg_organization_article_orders_updated_at
    BEFORE UPDATE ON public.organization_article_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_article_orders_updated_at();

DROP TRIGGER IF EXISTS trg_organization_article_orders_block_cancel_if_received ON public.organization_article_orders;
CREATE TRIGGER trg_organization_article_orders_block_cancel_if_received
    BEFORE UPDATE OF status ON public.organization_article_orders
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_orders_block_cancel_if_received();

DROP TRIGGER IF EXISTS trg_order_lines_check_article_org ON public.organization_article_order_lines;
CREATE TRIGGER trg_order_lines_check_article_org
    BEFORE INSERT OR UPDATE OF order_id, article_id ON public.organization_article_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_order_lines_check_article_org();

DROP TRIGGER IF EXISTS trg_order_lines_set_received_at ON public.organization_article_order_lines;
CREATE TRIGGER trg_order_lines_set_received_at
    BEFORE INSERT OR UPDATE OF quantity_received ON public.organization_article_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_order_lines_set_received_at();

DROP TRIGGER IF EXISTS trg_order_lines_apply_received_stock ON public.organization_article_order_lines;
CREATE TRIGGER trg_order_lines_apply_received_stock
    AFTER INSERT OR UPDATE OF quantity_received, article_id, order_id ON public.organization_article_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_order_lines_apply_received_stock();

DROP TRIGGER IF EXISTS trg_order_lines_sync_order_status ON public.organization_article_order_lines;
CREATE TRIGGER trg_order_lines_sync_order_status
    AFTER INSERT OR UPDATE OF quantity_received ON public.organization_article_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_order_lines_sync_order_status();

DROP TRIGGER IF EXISTS trg_order_lines_touch_parent_order ON public.organization_article_order_lines;
CREATE TRIGGER trg_order_lines_touch_parent_order
    AFTER INSERT OR UPDATE OR DELETE ON public.organization_article_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_order_lines_touch_parent_order();

DROP TRIGGER IF EXISTS trg_order_lines_revert_stock_on_delete ON public.organization_article_order_lines;
CREATE TRIGGER trg_order_lines_revert_stock_on_delete
    BEFORE DELETE ON public.organization_article_order_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_article_order_lines_revert_stock_on_delete();

CREATE INDEX IF NOT EXISTS idx_organization_article_orders_org
    ON public.organization_article_orders (organization_id);

CREATE INDEX IF NOT EXISTS idx_organization_article_orders_org_status
    ON public.organization_article_orders (organization_id, status);

CREATE INDEX IF NOT EXISTS idx_organization_article_order_lines_order
    ON public.organization_article_order_lines (order_id);

ALTER TABLE public.organization_article_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_article_order_lines ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_article_orders_select_member ON public.organization_article_orders;
CREATE POLICY organization_article_orders_select_member
    ON public.organization_article_orders
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_article_orders_insert_member ON public.organization_article_orders;
CREATE POLICY organization_article_orders_insert_member
    ON public.organization_article_orders
    FOR INSERT
    TO authenticated
    WITH CHECK (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_article_orders_update_member ON public.organization_article_orders;
CREATE POLICY organization_article_orders_update_member
    ON public.organization_article_orders
    FOR UPDATE
    TO authenticated
    USING (public.is_org_member(organization_id))
    WITH CHECK (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_article_orders_delete_member ON public.organization_article_orders;
CREATE POLICY organization_article_orders_delete_member
    ON public.organization_article_orders
    FOR DELETE
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_article_order_lines_select_member ON public.organization_article_order_lines;
CREATE POLICY organization_article_order_lines_select_member
    ON public.organization_article_order_lines
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_article_orders o
            WHERE o.id = order_id
              AND public.is_org_member(o.organization_id)
        )
    );

DROP POLICY IF EXISTS organization_article_order_lines_insert_member ON public.organization_article_order_lines;
CREATE POLICY organization_article_order_lines_insert_member
    ON public.organization_article_order_lines
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.organization_article_orders o
            WHERE o.id = order_id
              AND public.is_org_member(o.organization_id)
        )
    );

DROP POLICY IF EXISTS organization_article_order_lines_update_member ON public.organization_article_order_lines;
CREATE POLICY organization_article_order_lines_update_member
    ON public.organization_article_order_lines
    FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_article_orders o
            WHERE o.id = order_id
              AND public.is_org_member(o.organization_id)
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.organization_article_orders o
            WHERE o.id = order_id
              AND public.is_org_member(o.organization_id)
        )
    );

DROP POLICY IF EXISTS organization_article_order_lines_delete_member ON public.organization_article_order_lines;
CREATE POLICY organization_article_order_lines_delete_member
    ON public.organization_article_order_lines
    FOR DELETE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_article_orders o
            WHERE o.id = order_id
              AND public.is_org_member(o.organization_id)
        )
    );

-- Réception atomique : toutes les lignes mises à jour dans la même transaction (stock cohérent).
CREATE OR REPLACE FUNCTION public.receive_organization_article_order(
    p_order_id uuid,
    p_organization_id uuid,
    p_lines jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    elem jsonb;
    lid uuid;
    qr integer;
    sr text;
    qo integer;
    rec_line public.organization_article_order_lines%ROWTYPE;
    n_expected integer;
    n_payload integer;
    v_status public.article_order_status_enum;
    v_org uuid;
BEGIN
    SELECT o.status, o.organization_id
    INTO v_status, v_org
    FROM public.organization_article_orders o
    WHERE o.id = p_order_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'Commande introuvable';
    END IF;

    IF v_org <> p_organization_id THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'Organisation incorrecte pour cette commande';
    END IF;

    IF v_status <> 'open'::public.article_order_status_enum THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'La commande n''est pas ouverte';
    END IF;

    SELECT count(*)::integer
    INTO n_expected
    FROM public.organization_article_order_lines
    WHERE order_id = p_order_id;

    n_payload := jsonb_array_length(p_lines);

    IF n_expected = 0 OR n_expected <> n_payload THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'Le nombre d''entrées de réception doit correspondre aux lignes de la commande';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.organization_article_order_lines l
        WHERE l.order_id = p_order_id
          AND l.quantity_received IS NOT NULL
    ) THEN
        RAISE EXCEPTION
            USING ERRCODE = 'P0001',
                  MESSAGE = 'Cette commande a déjà été réceptionnée';
    END IF;

    FOR elem IN SELECT * FROM jsonb_array_elements(p_lines)
    LOOP
        lid := (elem ->> 'line_id')::uuid;
        SELECT *
        INTO rec_line
        FROM public.organization_article_order_lines
        WHERE id = lid
          AND order_id = p_order_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                USING ERRCODE = 'P0001',
                  MESSAGE = format('Ligne de commande inconnue : %s', lid);
        END IF;

        qo := rec_line.quantity_ordered;
        qr := (elem ->> 'quantity_received')::integer;

        IF qr < 0 OR qr > qo THEN
            RAISE EXCEPTION
                USING ERRCODE = 'P0001',
                  MESSAGE = format(
                      'Quantité reçue invalide pour la ligne %s (commandé : %s)',
                      lid,
                      qo
                  );
        END IF;

        IF qr < qo THEN
            sr := nullif(btrim(elem ->> 'shortage_reason'), '');
            IF sr IS NULL THEN
                RAISE EXCEPTION
                    USING ERRCODE = 'P0001',
                          MESSAGE = 'Motif obligatoire lorsque la quantité reçue est inférieure à la commande';
            END IF;
        END IF;
    END LOOP;

    FOR elem IN SELECT * FROM jsonb_array_elements(p_lines)
    LOOP
        lid := (elem ->> 'line_id')::uuid;
        qo := (
            SELECT l.quantity_ordered
            FROM public.organization_article_order_lines l
            WHERE l.id = lid
              AND l.order_id = p_order_id
        );
        qr := (elem ->> 'quantity_received')::integer;

        IF qr < qo THEN
            sr := btrim(elem ->> 'shortage_reason');
        ELSE
            sr := NULL;
        END IF;

        UPDATE public.organization_article_order_lines
        SET
            quantity_received = qr,
            shortage_reason = sr
        WHERE id = lid
          AND order_id = p_order_id;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION public.receive_organization_article_order(uuid, uuid, jsonb) IS
    'Réceptionne toutes les lignes en une transaction ; déclenche mise à jour du stock.';

GRANT EXECUTE ON FUNCTION public.receive_organization_article_order(uuid, uuid, jsonb) TO service_role;
