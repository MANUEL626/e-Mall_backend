-- ============================
-- ENUM TYPES
-- ============================
DO $$
BEGIN
    CREATE TYPE organization_type_enum AS ENUM ('delivery', 'sales');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE member_type_enum AS ENUM ('admin', 'supervisor', 'member');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE member_role_enum AS ENUM ('sales_management', 'delivery_management');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- ============================
-- TABLE users
-- ============================
CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email text UNIQUE,
    first_name varchar(50) NOT NULL,
    last_name varchar(50) NOT NULL,
    phone varchar(20) UNIQUE,
    activity_status boolean NOT NULL DEFAULT true,
    profile_picture text,
    username varchar(50) UNIQUE NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================
-- TABLE organizations
-- ============================
CREATE TABLE IF NOT EXISTS organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    org_type organization_type_enum NOT NULL,
    created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================
-- TABLE admins
-- ============================
CREATE TABLE IF NOT EXISTS admins (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================
-- TABLE customers
-- ============================
CREATE TABLE IF NOT EXISTS customers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================
-- TABLE members
-- ============================
CREATE TABLE IF NOT EXISTS members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    member_type member_type_enum NOT NULL DEFAULT 'member',
    member_role member_role_enum NOT NULL,
    activity_status boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_members_user_org UNIQUE (user_id, organization_id)
);

-- ============================
-- TRIGGER: default member on organization creation
-- ============================
CREATE OR REPLACE FUNCTION create_default_member_for_org()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO members (user_id, organization_id, member_type, member_role)
    VALUES (NEW.created_by, NEW.id, 'admin', 'sales_management')
    ON CONFLICT (user_id, organization_id) DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_org_default_member ON organizations;
CREATE TRIGGER trg_org_default_member
AFTER INSERT ON organizations
FOR EACH ROW
EXECUTE FUNCTION create_default_member_for_org();

-- ============================
-- ENABLE ROW LEVEL SECURITY
-- ============================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE admins ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE members ENABLE ROW LEVEL SECURITY;

-- ============================
-- POLICIES (RLS)
-- ============================
-- Policies can be added in a dedicated migration once auth/authorization rules are finalized.
