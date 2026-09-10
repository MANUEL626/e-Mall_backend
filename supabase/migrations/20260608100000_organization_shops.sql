-- Structure boutique : une organisation peut avoir plusieurs points operationnels.
-- Le type d'activite devient porte par la boutique. organizations.org_type reste
-- conserve pour compatibilite pendant la migration.

ALTER TYPE public.organization_type_enum ADD VALUE IF NOT EXISTS 'repair';
ALTER TYPE public.organization_type_enum ADD VALUE IF NOT EXISTS 'rental';

DO $$
BEGIN
    CREATE TYPE public.organization_shop_type_enum AS ENUM (
        'sales',
        'delivery',
        'repair',
        'rental'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE public.organization_shop_status_enum AS ENUM (
        'active',
        'inactive',
        'archived'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE public.organization_shop_role_enum AS ENUM (
        'shop_admin',
        'sales_staff',
        'stock_manager',
        'delivery_staff',
        'repair_staff',
        'rental_staff',
        'viewer'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.organization_shops (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    name text NOT NULL,
    code text,
    description text,
    shop_type public.organization_shop_type_enum NOT NULL,
    status public.organization_shop_status_enum NOT NULL DEFAULT 'active',
    is_default boolean NOT NULL DEFAULT false,
    country text,
    city text,
    address text,
    longitude double precision,
    latitude double precision,
    phone text,
    email text,
    profile_picture text,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id uuid REFERENCES public.users (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_shops_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT organization_shops_code_not_blank CHECK (
        code IS NULL OR btrim(code) <> ''
    ),
    CONSTRAINT organization_shops_settings_object CHECK (
        jsonb_typeof(settings) = 'object'
    ),
    CONSTRAINT organization_shops_lat_range CHECK (
        latitude IS NULL OR (latitude >= -90 AND latitude <= 90)
    ),
    CONSTRAINT organization_shops_lon_range CHECK (
        longitude IS NULL OR (longitude >= -180 AND longitude <= 180)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_shops_org_code
    ON public.organization_shops (organization_id, lower(code))
    WHERE code IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_shops_default
    ON public.organization_shops (organization_id)
    WHERE is_default IS TRUE;

CREATE INDEX IF NOT EXISTS idx_organization_shops_org
    ON public.organization_shops (organization_id);

CREATE INDEX IF NOT EXISTS idx_organization_shops_org_type_status
    ON public.organization_shops (organization_id, shop_type, status);

CREATE OR REPLACE FUNCTION public.create_default_shop_for_org()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO public.organization_shops (
        organization_id,
        name,
        code,
        shop_type,
        status,
        is_default,
        created_by_user_id
    )
    VALUES (
        NEW.id,
        'Boutique principale',
        'default',
        NEW.org_type::text::public.organization_shop_type_enum,
        'active'::public.organization_shop_status_enum,
        true,
        NEW.created_by
    )
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_org_default_shop ON public.organizations;
CREATE TRIGGER trg_org_default_shop
    AFTER INSERT ON public.organizations
    FOR EACH ROW
    EXECUTE FUNCTION public.create_default_shop_for_org();

CREATE OR REPLACE FUNCTION public.touch_organization_shops_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_shops_updated_at
    ON public.organization_shops;
CREATE TRIGGER trg_organization_shops_updated_at
    BEFORE UPDATE ON public.organization_shops
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_shops_updated_at();

CREATE TABLE IF NOT EXISTS public.organization_shop_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES public.organizations (id) ON DELETE CASCADE,
    shop_id uuid NOT NULL REFERENCES public.organization_shops (id) ON DELETE CASCADE,
    member_id uuid NOT NULL REFERENCES public.members (id) ON DELETE CASCADE,
    shop_role public.organization_shop_role_enum NOT NULL DEFAULT 'viewer',
    activity_status boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_organization_shop_members_shop_member UNIQUE (shop_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_organization_shop_members_org
    ON public.organization_shop_members (organization_id);

CREATE INDEX IF NOT EXISTS idx_organization_shop_members_shop_active
    ON public.organization_shop_members (shop_id, activity_status);

CREATE INDEX IF NOT EXISTS idx_organization_shop_members_member_active
    ON public.organization_shop_members (member_id, activity_status);

CREATE OR REPLACE FUNCTION public.touch_organization_shop_members_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_shop_members_updated_at
    ON public.organization_shop_members;
CREATE TRIGGER trg_organization_shop_members_updated_at
    BEFORE UPDATE ON public.organization_shop_members
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_shop_members_updated_at();

CREATE OR REPLACE FUNCTION public.organization_shop_members_check_same_org()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_shop_org uuid;
    v_member_org uuid;
BEGIN
    SELECT organization_id
    INTO v_shop_org
    FROM public.organization_shops
    WHERE id = NEW.shop_id;

    SELECT organization_id
    INTO v_member_org
    FROM public.members
    WHERE id = NEW.member_id;

    IF v_shop_org IS NULL OR v_member_org IS NULL OR v_shop_org <> v_member_org THEN
        RAISE EXCEPTION
            USING ERRCODE = '23514',
                  MESSAGE = 'La boutique et le membre doivent appartenir a la meme organisation';
    END IF;

    NEW.organization_id := v_shop_org;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_organization_shop_members_same_org
    ON public.organization_shop_members;
CREATE TRIGGER trg_organization_shop_members_same_org
    BEFORE INSERT OR UPDATE OF shop_id, member_id
    ON public.organization_shop_members
    FOR EACH ROW
    EXECUTE FUNCTION public.organization_shop_members_check_same_org();

CREATE OR REPLACE FUNCTION public.assign_existing_members_to_default_shop()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.is_default IS TRUE THEN
        INSERT INTO public.organization_shop_members (
            organization_id,
            shop_id,
            member_id,
            shop_role,
            activity_status
        )
        SELECT
            m.organization_id,
            NEW.id,
            m.id,
            CASE
                WHEN m.member_type IN ('admin', 'supervisor')
                    THEN 'shop_admin'::public.organization_shop_role_enum
                WHEN m.member_role = 'delivery_management'
                    THEN 'delivery_staff'::public.organization_shop_role_enum
                ELSE 'sales_staff'::public.organization_shop_role_enum
            END,
            m.activity_status
        FROM public.members m
        WHERE m.organization_id = NEW.organization_id
        ON CONFLICT (shop_id, member_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_default_shop_assign_existing_members
    ON public.organization_shops;
CREATE TRIGGER trg_default_shop_assign_existing_members
    AFTER INSERT ON public.organization_shops
    FOR EACH ROW
    EXECUTE FUNCTION public.assign_existing_members_to_default_shop();

CREATE OR REPLACE FUNCTION public.assign_member_to_default_shop()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_shop_id uuid;
BEGIN
    SELECT id
    INTO v_shop_id
    FROM public.organization_shops
    WHERE organization_id = NEW.organization_id
      AND is_default IS TRUE
    LIMIT 1;

    IF v_shop_id IS NOT NULL THEN
        INSERT INTO public.organization_shop_members (
            organization_id,
            shop_id,
            member_id,
            shop_role,
            activity_status
        )
        VALUES (
            NEW.organization_id,
            v_shop_id,
            NEW.id,
            CASE
                WHEN NEW.member_type IN ('admin', 'supervisor')
                    THEN 'shop_admin'::public.organization_shop_role_enum
                WHEN NEW.member_role = 'delivery_management'
                    THEN 'delivery_staff'::public.organization_shop_role_enum
                ELSE 'sales_staff'::public.organization_shop_role_enum
            END,
            NEW.activity_status
        )
        ON CONFLICT (shop_id, member_id) DO NOTHING;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_members_assign_default_shop ON public.members;
CREATE TRIGGER trg_members_assign_default_shop
    AFTER INSERT ON public.members
    FOR EACH ROW
    EXECUTE FUNCTION public.assign_member_to_default_shop();

CREATE OR REPLACE FUNCTION public.is_shop_member(p_shop_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.organization_shop_members osm
        INNER JOIN public.members m ON m.id = osm.member_id
        WHERE osm.shop_id = p_shop_id
          AND osm.activity_status = true
          AND m.activity_status = true
          AND m.user_id = auth.uid()
    )
    OR EXISTS (
        SELECT 1
        FROM public.organization_shops s
        WHERE s.id = p_shop_id
          AND public.is_org_member(s.organization_id)
    );
$$;

CREATE OR REPLACE FUNCTION public.can_manage_shop(p_shop_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.organization_shops s
        INNER JOIN public.members m
            ON m.organization_id = s.organization_id
        WHERE s.id = p_shop_id
          AND m.user_id = auth.uid()
          AND m.activity_status = true
          AND m.member_type IN ('admin', 'supervisor')
    )
    OR EXISTS (
        SELECT 1
        FROM public.organization_shop_members osm
        INNER JOIN public.members m ON m.id = osm.member_id
        WHERE osm.shop_id = p_shop_id
          AND osm.activity_status = true
          AND osm.shop_role = 'shop_admin'
          AND m.activity_status = true
          AND m.user_id = auth.uid()
    );
$$;

COMMENT ON FUNCTION public.is_shop_member(uuid) IS
    'Vrai si l utilisateur connecte est membre actif de la boutique ou membre actif de l organisation.';

CREATE OR REPLACE FUNCTION public.can_manage_organization(p_organization_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.members m
        WHERE m.organization_id = p_organization_id
          AND m.user_id = auth.uid()
          AND m.activity_status = true
          AND m.member_type IN ('admin', 'supervisor')
    );
$$;

COMMENT ON FUNCTION public.can_manage_organization(uuid) IS
    'Vrai si l utilisateur connecte est admin ou supervisor actif de l organisation.';

COMMENT ON FUNCTION public.can_manage_shop(uuid) IS
    'Vrai si l utilisateur connecte peut administrer la boutique.';

-- Backfill : boutique par defaut pour chaque organisation existante.
INSERT INTO public.organization_shops (
    organization_id,
    name,
    code,
    shop_type,
    status,
    is_default,
    created_by_user_id
)
SELECT
    o.id,
    'Boutique principale',
    'default',
    o.org_type::text::public.organization_shop_type_enum,
    'active'::public.organization_shop_status_enum,
    true,
    o.created_by
FROM public.organizations o
WHERE NOT EXISTS (
    SELECT 1
    FROM public.organization_shops s
    WHERE s.organization_id = o.id
      AND s.is_default IS TRUE
);

-- Backfill : affecter les membres existants a la boutique par defaut.
INSERT INTO public.organization_shop_members (
    organization_id,
    shop_id,
    member_id,
    shop_role,
    activity_status
)
SELECT
    m.organization_id,
    s.id,
    m.id,
    CASE
        WHEN m.member_type IN ('admin', 'supervisor')
            THEN 'shop_admin'::public.organization_shop_role_enum
        WHEN m.member_role = 'delivery_management'
            THEN 'delivery_staff'::public.organization_shop_role_enum
        ELSE 'sales_staff'::public.organization_shop_role_enum
    END,
    m.activity_status
FROM public.members m
INNER JOIN public.organization_shops s
    ON s.organization_id = m.organization_id
   AND s.is_default IS TRUE
ON CONFLICT (shop_id, member_id) DO NOTHING;

ALTER TABLE public.organization_shops ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_shop_members ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_shops_select_member ON public.organization_shops;
CREATE POLICY organization_shops_select_member
    ON public.organization_shops
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_shops_insert_org_manager ON public.organization_shops;
CREATE POLICY organization_shops_insert_org_manager
    ON public.organization_shops
    FOR INSERT
    TO authenticated
    WITH CHECK (public.can_manage_organization(organization_id));

DROP POLICY IF EXISTS organization_shops_update_manager ON public.organization_shops;
CREATE POLICY organization_shops_update_manager
    ON public.organization_shops
    FOR UPDATE
    TO authenticated
    USING (public.can_manage_shop(id))
    WITH CHECK (public.can_manage_shop(id));

DROP POLICY IF EXISTS organization_shop_members_select_org_member
    ON public.organization_shop_members;
CREATE POLICY organization_shop_members_select_org_member
    ON public.organization_shop_members
    FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS organization_shop_members_insert_org_manager
    ON public.organization_shop_members;
CREATE POLICY organization_shop_members_insert_org_manager
    ON public.organization_shop_members
    FOR INSERT
    TO authenticated
    WITH CHECK (public.can_manage_organization(organization_id));

DROP POLICY IF EXISTS organization_shop_members_update_org_manager
    ON public.organization_shop_members;
CREATE POLICY organization_shop_members_update_org_manager
    ON public.organization_shop_members
    FOR UPDATE
    TO authenticated
    USING (public.can_manage_organization(organization_id))
    WITH CHECK (public.can_manage_organization(organization_id));

GRANT SELECT, INSERT, UPDATE ON public.organization_shops TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.organization_shop_members TO authenticated;
GRANT ALL ON public.organization_shops TO service_role;
GRANT ALL ON public.organization_shop_members TO service_role;

COMMENT ON TABLE public.organization_shops IS
    'Boutiques / points operationnels rattaches a une organisation.';

COMMENT ON TABLE public.organization_shop_members IS
    'Affectation operationnelle des membres a une boutique.';
