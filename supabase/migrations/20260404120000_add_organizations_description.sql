-- Description libre de l'organisation (optionnelle).
ALTER TABLE public.organizations
    ADD COLUMN IF NOT EXISTS description text;

COMMENT ON COLUMN public.organizations.description IS
    'Description optionnelle de l''organisation.';
