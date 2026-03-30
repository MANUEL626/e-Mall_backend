-- ============================================================
-- RPC: bootstrap customer profile (atomic find-or-create)
-- ============================================================
CREATE OR REPLACE FUNCTION public.bootstrap_customer_profile(
    p_user_id uuid,
    p_phone text,
    p_email text DEFAULT NULL,
    p_first_name text DEFAULT 'Customer',
    p_last_name text DEFAULT 'User',
    p_username text DEFAULT NULL
)
RETURNS TABLE (
    user_id uuid,
    is_new_customer boolean,
    profile_complete boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_user_exists boolean;
    v_customer_exists boolean;
    v_username text;
    v_first_name text;
    v_last_name text;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'p_user_id est requis';
    END IF;

    IF p_phone IS NULL OR length(trim(p_phone)) = 0 THEN
        RAISE EXCEPTION 'p_phone est requis';
    END IF;

    v_username := COALESCE(NULLIF(trim(p_username), ''), 'cust_' || replace(substr(p_user_id::text, 1, 8), '-', ''));
    v_first_name := COALESCE(NULLIF(trim(p_first_name), ''), 'Customer');
    v_last_name := COALESCE(NULLIF(trim(p_last_name), ''), 'User');

    SELECT EXISTS (SELECT 1 FROM public.users u WHERE u.id = p_user_id) INTO v_user_exists;

    IF NOT v_user_exists THEN
        BEGIN
            INSERT INTO public.users (
                id,
                email,
                first_name,
                last_name,
                phone,
                activity_status,
                profile_picture,
                username
            )
            VALUES (
                p_user_id,
                NULLIF(trim(p_email), ''),
                v_first_name,
                v_last_name,
                trim(p_phone),
                true,
                NULL,
                v_username
            );
        EXCEPTION WHEN unique_violation THEN
            -- Collision de username (possible si stratégie de fallback), on force un suffixe unique.
            v_username := 'cust_' || replace(substr(p_user_id::text, 1, 12), '-', '');
            INSERT INTO public.users (
                id,
                email,
                first_name,
                last_name,
                phone,
                activity_status,
                profile_picture,
                username
            )
            VALUES (
                p_user_id,
                NULLIF(trim(p_email), ''),
                v_first_name,
                v_last_name,
                trim(p_phone),
                true,
                NULL,
                v_username
            )
            ON CONFLICT (id) DO NOTHING;
        END;
    ELSE
        UPDATE public.users
        SET
            phone = COALESCE(users.phone, trim(p_phone)),
            email = COALESCE(users.email, NULLIF(trim(p_email), ''))
        WHERE users.id = p_user_id;
    END IF;

    SELECT EXISTS (SELECT 1 FROM public.customers c WHERE c.user_id = p_user_id) INTO v_customer_exists;

    IF NOT v_customer_exists THEN
        -- Ne pas utiliser ON CONFLICT (user_id) : avec RETURNS TABLE (user_id ...),
        -- PL/pgSQL crée une variable homonyme et "user_id" devient ambigu (42702).
        INSERT INTO public.customers (user_id)
        VALUES (p_user_id)
        ON CONFLICT ON CONSTRAINT customers_user_id_key DO NOTHING;
    END IF;

    RETURN QUERY
    SELECT
        p_user_id,
        NOT v_customer_exists AS is_new_customer,
        (
            u.first_name IS NOT NULL
            AND u.last_name IS NOT NULL
            AND u.username IS NOT NULL
            AND u.first_name <> 'Customer'
            AND u.last_name <> 'User'
            AND u.username NOT LIKE 'cust_%'
        ) AS profile_complete
    FROM public.users u
    WHERE u.id = p_user_id
    LIMIT 1;
END;
$$;

REVOKE ALL ON FUNCTION public.bootstrap_customer_profile(uuid, text, text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bootstrap_customer_profile(uuid, text, text, text, text, text) TO service_role;
