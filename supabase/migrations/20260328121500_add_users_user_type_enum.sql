-- Type d'utilisateur applicatif (customer / admin / member).
-- Colonne absente du schéma initial ; ajoutée après premier db push.

DO $$
BEGIN
    CREATE TYPE public.user_type_enum AS ENUM ('customer', 'admin', 'member');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS user_type public.user_type_enum NOT NULL DEFAULT 'customer';

COMMENT ON COLUMN public.users.user_type IS
    'Rôle applicatif : customer (achat), admin (plateforme), member (personnel org.)';

-- Prénom / nom optionnels à la création (ex. bootstrap téléphone avant complétion du profil).
ALTER TABLE public.users
    ALTER COLUMN first_name DROP NOT NULL,
    ALTER COLUMN last_name DROP NOT NULL;

COMMENT ON COLUMN public.users.first_name IS 'Optionnel jusqu''à finalisation du profil.';
COMMENT ON COLUMN public.users.last_name IS 'Optionnel jusqu''à finalisation du profil.';
