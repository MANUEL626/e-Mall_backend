-- Points GPS pour suivi livraison (temps réel via Supabase Realtime sur cette table).

CREATE TABLE IF NOT EXISTS public.customer_sale_delivery_track_points (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL
        REFERENCES public.organization_customer_sale_orders (id) ON DELETE CASCADE,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    accuracy_meters double precision,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT csd_tp_lat_range CHECK (
        latitude >= -90::double precision
        AND latitude <= 90::double precision
    ),
    CONSTRAINT csd_tp_lon_range CHECK (
        longitude >= -180::double precision
        AND longitude <= 180::double precision
    )
);

CREATE INDEX IF NOT EXISTS idx_csd_tp_order_recorded
    ON public.customer_sale_delivery_track_points (order_id, recorded_at);

COMMENT ON TABLE public.customer_sale_delivery_track_points IS
    'Historique de positions pour une commande livraison ; lecture client / org / livreur assigné (RLS).';

-- Garde : uniquement commandes livraison non clôturées.
CREATE OR REPLACE FUNCTION public.csd_track_points_order_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_ff public.customer_sale_fulfillment_enum;
    v_st public.customer_sale_order_status_enum;
BEGIN
    SELECT o.fulfillment_type, o.status
    INTO v_ff, v_st
    FROM public.organization_customer_sale_orders o
    WHERE o.id = NEW.order_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            USING ERRCODE = '23503',
                  MESSAGE = 'Commande introuvable pour le point de suivi';
    END IF;
    IF v_ff IS DISTINCT FROM 'delivery'::public.customer_sale_fulfillment_enum THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'Le suivi GPS est réservé aux commandes en livraison';
    END IF;
    IF v_st IN (
        'cancelled'::public.customer_sale_order_status_enum,
        'completed'::public.customer_sale_order_status_enum
    ) THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'Commande terminée : envoi de position impossible';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_csd_track_points_order_guard
    ON public.customer_sale_delivery_track_points;
CREATE TRIGGER trg_csd_track_points_order_guard
    BEFORE INSERT ON public.customer_sale_delivery_track_points
    FOR EACH ROW
    EXECUTE FUNCTION public.csd_track_points_order_guard();

ALTER TABLE public.customer_sale_delivery_track_points ENABLE ROW LEVEL SECURITY;

-- Lecture : client propriétaire, membre org, ou livreur assigné à la commande.
DROP POLICY IF EXISTS csd_tp_select_parties ON public.customer_sale_delivery_track_points;
CREATE POLICY csd_tp_select_parties
    ON public.customer_sale_delivery_track_points
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_customer_sale_orders o
            WHERE o.id = order_id
              AND (
                  (
                      o.customer_id IS NOT NULL
                      AND public.is_customer_self(o.customer_id)
                  )
                  OR public.is_org_member(o.organization_id)
                  OR (
                      o.assigned_delivery_member_id IS NOT NULL
                      AND EXISTS (
                          SELECT 1
                          FROM public.members m
                          WHERE m.id = o.assigned_delivery_member_id
                            AND m.user_id = auth.uid()
                      )
                  )
              )
        )
    );

-- Écriture : uniquement le livreur assigné (membre actif).
DROP POLICY IF EXISTS csd_tp_insert_assigned_driver ON public.customer_sale_delivery_track_points;
CREATE POLICY csd_tp_insert_assigned_driver
    ON public.customer_sale_delivery_track_points
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.organization_customer_sale_orders o
            INNER JOIN public.members m
                ON m.id = o.assigned_delivery_member_id
            WHERE o.id = order_id
              AND o.fulfillment_type = 'delivery'::public.customer_sale_fulfillment_enum
              AND o.status NOT IN (
                  'cancelled'::public.customer_sale_order_status_enum,
                  'completed'::public.customer_sale_order_status_enum
              )
              AND m.user_id = auth.uid()
              AND m.activity_status IS TRUE
        )
    );

GRANT SELECT, INSERT ON public.customer_sale_delivery_track_points TO authenticated;

-- Realtime (INSERT / broadcast pour abonnés autorisés par RLS).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'public'
          AND tablename = 'customer_sale_delivery_track_points'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.customer_sale_delivery_track_points;
    END IF;
END $$;
