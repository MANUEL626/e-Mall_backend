-- Fix Storage policies for organization profile images in the public avatars bucket.
--
-- This migration is intentionally separate from
-- 20260522120000_organization_profile_and_member_params.sql because that migration
-- may already be marked as applied remotely. Supabase will not replay edited
-- migration files; a new migration is required.

CREATE OR REPLACE FUNCTION public.is_active_organization_member(target_organization_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.members m
        WHERE m.user_id = auth.uid()
          AND m.organization_id = target_organization_id
          AND m.activity_status IS TRUE
    );
$$;

REVOKE ALL ON FUNCTION public.is_active_organization_member(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_active_organization_member(uuid) TO authenticated;

DROP POLICY IF EXISTS "avatars_org_members_insert_profile" ON storage.objects;
CREATE POLICY "avatars_org_members_insert_profile"
    ON storage.objects
    FOR INSERT
    TO authenticated
    WITH CHECK (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND split_part(name, '/', 2) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_active_organization_member(split_part(name, '/', 2)::uuid)
    );

DROP POLICY IF EXISTS "avatars_org_members_update_profile" ON storage.objects;
CREATE POLICY "avatars_org_members_update_profile"
    ON storage.objects
    FOR UPDATE
    TO authenticated
    USING (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND split_part(name, '/', 2) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_active_organization_member(split_part(name, '/', 2)::uuid)
    )
    WITH CHECK (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND split_part(name, '/', 2) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_active_organization_member(split_part(name, '/', 2)::uuid)
    );

DROP POLICY IF EXISTS "avatars_org_members_delete_profile" ON storage.objects;
CREATE POLICY "avatars_org_members_delete_profile"
    ON storage.objects
    FOR DELETE
    TO authenticated
    USING (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = 'organizations'
        AND split_part(name, '/', 2) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_active_organization_member(split_part(name, '/', 2)::uuid)
    );
