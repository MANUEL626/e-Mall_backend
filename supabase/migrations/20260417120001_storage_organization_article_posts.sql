-- Bucket public pour médias des posts d'articles : premier segment = organization_id (UUID).

INSERT INTO storage.buckets (id, name, public)
VALUES ('organization-article-posts', 'organization-article-posts', true)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS organization_article_posts_storage_public_read ON storage.objects;
CREATE POLICY organization_article_posts_storage_public_read
    ON storage.objects
    FOR SELECT
    TO public
    USING (bucket_id = 'organization-article-posts');

DROP POLICY IF EXISTS organization_article_posts_storage_member_insert ON storage.objects;
CREATE POLICY organization_article_posts_storage_member_insert
    ON storage.objects
    FOR INSERT
    TO authenticated
    WITH CHECK (
        bucket_id = 'organization-article-posts'
        AND split_part(name, '/', 1) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_org_member(split_part(name, '/', 1)::uuid)
    );

DROP POLICY IF EXISTS organization_article_posts_storage_member_update ON storage.objects;
CREATE POLICY organization_article_posts_storage_member_update
    ON storage.objects
    FOR UPDATE
    TO authenticated
    USING (
        bucket_id = 'organization-article-posts'
        AND split_part(name, '/', 1) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_org_member(split_part(name, '/', 1)::uuid)
    )
    WITH CHECK (
        bucket_id = 'organization-article-posts'
        AND split_part(name, '/', 1) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_org_member(split_part(name, '/', 1)::uuid)
    );

DROP POLICY IF EXISTS organization_article_posts_storage_member_delete ON storage.objects;
CREATE POLICY organization_article_posts_storage_member_delete
    ON storage.objects
    FOR DELETE
    TO authenticated
    USING (
        bucket_id = 'organization-article-posts'
        AND split_part(name, '/', 1) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        AND public.is_org_member(split_part(name, '/', 1)::uuid)
    );
