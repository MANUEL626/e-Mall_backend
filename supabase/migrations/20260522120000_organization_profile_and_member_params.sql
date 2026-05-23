-- Profil organisation + parametres membre.

ALTER TABLE public.organizations
ADD COLUMN IF NOT EXISTS profile_picture text,
ADD COLUMN IF NOT EXISTS countries text[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN public.organizations.profile_picture IS
    'Image de profil de l''organisation. Peut etre une URL publique ou un chemin Storage.';

COMMENT ON COLUMN public.organizations.countries IS
    'Liste de pays au format ISO 3166-1 alpha-2 majuscule, ex: TG, NG, BJ.';

CREATE OR REPLACE FUNCTION public.text_array_is_iso_alpha2(items text[])
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT items IS NOT NULL
       AND COALESCE(bool_and(code ~ '^[A-Z]{2}$'), true)
    FROM unnest(items) AS item(code);
$$;

DO $$
BEGIN
    ALTER TABLE public.organizations
        ADD CONSTRAINT organizations_countries_iso_alpha2_check
        CHECK (public.text_array_is_iso_alpha2(countries));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.member_params (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    locale text NOT NULL DEFAULT 'fr',
    extra jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT member_params_locale_check CHECK (locale IN ('fr', 'en', 'de', 'zh'))
);

COMMENT ON TABLE public.member_params IS
    'Parametres personnels des membres, dont la langue du back-office.';

COMMENT ON COLUMN public.member_params.locale IS
    'Langue membre: fr, en, de, zh.';

CREATE OR REPLACE FUNCTION public.touch_member_params_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_member_params_updated_at ON public.member_params;
CREATE TRIGGER trg_member_params_updated_at
    BEFORE UPDATE ON public.member_params
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_member_params_updated_at();

ALTER TABLE public.member_params ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS member_params_select_self ON public.member_params;
CREATE POLICY member_params_select_self
    ON public.member_params
    FOR SELECT
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS member_params_insert_self ON public.member_params;
CREATE POLICY member_params_insert_self
    ON public.member_params
    FOR INSERT
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS member_params_update_self ON public.member_params;
CREATE POLICY member_params_update_self
    ON public.member_params
    FOR UPDATE
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Storage avatars : autoriser les membres actifs a gerer les images de profil
-- d'une organisation sous organizations/{organization_id}/...
DROP POLICY IF EXISTS "avatars_org_members_insert_profile" ON storage.objects;
CREATE POLICY "avatars_org_members_insert_profile"
    ON storage.objects
    FOR INSERT
    TO authenticated
    WITH CHECK (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND EXISTS (
            SELECT 1
            FROM public.members m
            WHERE m.user_id = auth.uid()
              AND m.organization_id::text = split_part(name, '/', 2)
              AND m.activity_status IS TRUE
        )
    );

DROP POLICY IF EXISTS "avatars_org_members_update_profile" ON storage.objects;
CREATE POLICY "avatars_org_members_update_profile"
    ON storage.objects
    FOR UPDATE
    TO authenticated
    USING (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND EXISTS (
            SELECT 1
            FROM public.members m
            WHERE m.user_id = auth.uid()
              AND m.organization_id::text = split_part(name, '/', 2)
              AND m.activity_status IS TRUE
        )
    )
    WITH CHECK (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND EXISTS (
            SELECT 1
            FROM public.members m
            WHERE m.user_id = auth.uid()
              AND m.organization_id::text = split_part(name, '/', 2)
              AND m.activity_status IS TRUE
        )
    );

DROP POLICY IF EXISTS "avatars_org_members_delete_profile" ON storage.objects;
CREATE POLICY "avatars_org_members_delete_profile"
    ON storage.objects
    FOR DELETE
    TO authenticated
    USING (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND EXISTS (
            SELECT 1
            FROM public.members m
            WHERE m.user_id = auth.uid()
              AND m.organization_id::text = split_part(name, '/', 2)
              AND m.activity_status IS TRUE
        )
    );
