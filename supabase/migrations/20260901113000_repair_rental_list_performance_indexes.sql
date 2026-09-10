-- Indexes for paginated rental/repair list endpoints.
-- Existing status indexes are useful when status is filtered, but these cover
-- the common "all statuses ordered by date" screens.

CREATE INDEX IF NOT EXISTS idx_rental_reservations_org_shop_starts
    ON public.organization_rental_reservations (
        organization_id,
        shop_id,
        starts_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_rental_orders_org_shop_starts
    ON public.organization_rental_orders (
        organization_id,
        shop_id,
        starts_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_rental_proformas_org_shop_created
    ON public.organization_rental_proformas (
        organization_id,
        shop_id,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_repair_requests_org_shop_created
    ON public.organization_repair_requests (
        organization_id,
        shop_id,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_repair_request_parts_org_shop_request_created
    ON public.organization_repair_request_parts (
        organization_id,
        shop_id,
        repair_request_id,
        created_at DESC
    );
