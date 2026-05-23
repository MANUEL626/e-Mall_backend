-- Pipeline media pour posts video : original, version feed transcodee, miniature et statut.

ALTER TABLE public.organization_article_posts
    ADD COLUMN IF NOT EXISTS original_media_storage_path text,
    ADD COLUMN IF NOT EXISTS thumbnail_storage_path text,
    ADD COLUMN IF NOT EXISTS processing_status text NOT NULL DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS processing_error text,
    ADD COLUMN IF NOT EXISTS media_width integer,
    ADD COLUMN IF NOT EXISTS media_height integer,
    ADD COLUMN IF NOT EXISTS media_duration_seconds numeric,
    ADD COLUMN IF NOT EXISTS media_size_bytes bigint;

UPDATE public.organization_article_posts
SET original_media_storage_path = media_storage_path
WHERE original_media_storage_path IS NULL;

UPDATE public.organization_article_posts
SET thumbnail_storage_path = media_storage_path
WHERE thumbnail_storage_path IS NULL
  AND media_kind = 'image';

-- Les anciennes videos pointent vers l'original brut. On les masque tant
-- qu'elles n'ont pas ete republiees ou retraitees par le pipeline.
UPDATE public.organization_article_posts
SET processing_status = 'failed',
    processing_error = 'Video originale a retraiter pour compatibilite mobile',
    active = false
WHERE media_kind = 'video'
  AND media_storage_path = original_media_storage_path
  AND thumbnail_storage_path IS NULL;

DO $$
BEGIN
    ALTER TABLE public.organization_article_posts
        ADD CONSTRAINT organization_article_posts_processing_status_check
        CHECK (processing_status IN ('pending', 'processing', 'ready', 'failed'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DROP VIEW IF EXISTS public.customer_article_post_feed;

CREATE VIEW public.customer_article_post_feed AS
SELECT
    p.slot,
    p.media_kind,
    p.media_storage_path,
    p.thumbnail_storage_path,
    p.caption,
    p.processing_status,
    p.media_width,
    p.media_height,
    p.media_duration_seconds,
    a.id AS organization_article_id,
    a.organization_id,
    a.name,
    a.category,
    a.unit_sale_price,
    a.stock_status,
    a.primary_image_storage_path,
    a.additional_image_storage_paths,
    a.description,
    p.created_at AS post_created_at
FROM public.organization_article_posts p
INNER JOIN public.organization_articles a ON a.id = p.organization_article_id
WHERE p.active IS TRUE
  AND a.active IS TRUE
  AND (
      p.media_kind = 'image'
      OR p.processing_status = 'ready'
  );

COMMENT ON VIEW public.customer_article_post_feed IS
    'Posts promotionnels actifs rattaches a des articles actifs. Les videos ne sont exposees que lorsqu elles sont pretes.';

GRANT SELECT ON public.customer_article_post_feed TO service_role;
