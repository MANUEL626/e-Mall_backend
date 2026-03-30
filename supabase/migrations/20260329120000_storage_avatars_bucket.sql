-- =============================================================================
-- Storage : bucket public "avatars" pour photos de profil (URL courte vers l’API)
-- Chemin attendu côté app : {user_id}/profile_{timestamp}.{jpg|png|gif}
-- =============================================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('avatars', 'avatars', true)
ON CONFLICT (id) DO NOTHING;

-- Politiques sur storage.objects (RLS déjà activé par Supabase sur cette table)

DROP POLICY IF EXISTS "avatars_public_read" ON storage.objects;
CREATE POLICY "avatars_public_read"
    ON storage.objects
    FOR SELECT
    TO public
    USING (bucket_id = 'avatars');

DROP POLICY IF EXISTS "avatars_authenticated_insert_own_folder" ON storage.objects;
CREATE POLICY "avatars_authenticated_insert_own_folder"
    ON storage.objects
    FOR INSERT
    TO authenticated
    WITH CHECK (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = auth.uid()::text
    );

DROP POLICY IF EXISTS "avatars_authenticated_update_own_folder" ON storage.objects;
CREATE POLICY "avatars_authenticated_update_own_folder"
    ON storage.objects
    FOR UPDATE
    TO authenticated
    USING (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = auth.uid()::text
    )
    WITH CHECK (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = auth.uid()::text
    );

DROP POLICY IF EXISTS "avatars_authenticated_delete_own_folder" ON storage.objects;
CREATE POLICY "avatars_authenticated_delete_own_folder"
    ON storage.objects
    FOR DELETE
    TO authenticated
    USING (
        bucket_id = 'avatars'
        AND split_part(name, '/', 1) = auth.uid()::text
    );
