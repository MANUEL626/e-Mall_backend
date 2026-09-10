-- Indexes for generic admin/user list endpoints.

CREATE INDEX IF NOT EXISTS idx_users_created
    ON public.users (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admins_created
    ON public.admins (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_customers_created
    ON public.customers (created_at DESC);
