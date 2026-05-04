-- Posts promotionnels par article (max 3 emplacements par article : slot 1–3).

DO $$
BEGIN
    CREATE TYPE public.article_post_media_kind_enum AS ENUM ('image', 'video');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.organization_article_posts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_article_id uuid NOT NULL
        REFERENCES public.organization_articles (id) ON DELETE CASCADE,
    slot smallint NOT NULL,
    media_kind public.article_post_media_kind_enum NOT NULL,
    media_storage_path text NOT NULL,
    caption text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organization_article_posts_slot_range CHECK (slot >= 1 AND slot <= 3),
    CONSTRAINT organization_article_posts_media_path_nonempty CHECK (
        length(trim(media_storage_path)) > 0
    ),
    CONSTRAINT organization_article_posts_caption_len CHECK (
        caption IS NULL OR char_length(caption) <= 500
    ),
    CONSTRAINT organization_article_posts_unique_article_slot UNIQUE (organization_article_id, slot)
);

COMMENT ON TABLE public.organization_article_posts IS
    'Contenus promo (image/vidéo + légende) par article ; au plus une ligne par (article, slot 1–3).';

COMMENT ON COLUMN public.organization_article_posts.media_storage_path IS
    'Chemin objet dans le bucket Storage `organization-article-posts` (préfixe organization_id).';

CREATE INDEX IF NOT EXISTS idx_organization_article_posts_article
    ON public.organization_article_posts (organization_article_id);

DROP TRIGGER IF EXISTS trg_organization_article_posts_updated_at ON public.organization_article_posts;
CREATE TRIGGER trg_organization_article_posts_updated_at
    BEFORE UPDATE ON public.organization_article_posts
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_organization_articles_updated_at();

ALTER TABLE public.organization_article_posts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS organization_article_posts_select_member ON public.organization_article_posts;
CREATE POLICY organization_article_posts_select_member
    ON public.organization_article_posts
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_articles oa
            WHERE oa.id = organization_article_id
              AND public.is_org_member(oa.organization_id)
        )
    );

DROP POLICY IF EXISTS organization_article_posts_insert_member ON public.organization_article_posts;
CREATE POLICY organization_article_posts_insert_member
    ON public.organization_article_posts
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.organization_articles oa
            WHERE oa.id = organization_article_id
              AND public.is_org_member(oa.organization_id)
        )
    );

DROP POLICY IF EXISTS organization_article_posts_update_member ON public.organization_article_posts;
CREATE POLICY organization_article_posts_update_member
    ON public.organization_article_posts
    FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_articles oa
            WHERE oa.id = organization_article_id
              AND public.is_org_member(oa.organization_id)
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.organization_articles oa
            WHERE oa.id = organization_article_id
              AND public.is_org_member(oa.organization_id)
        )
    );

DROP POLICY IF EXISTS organization_article_posts_delete_member ON public.organization_article_posts;
CREATE POLICY organization_article_posts_delete_member
    ON public.organization_article_posts
    FOR DELETE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.organization_articles oa
            WHERE oa.id = organization_article_id
              AND public.is_org_member(oa.organization_id)
        )
    );
