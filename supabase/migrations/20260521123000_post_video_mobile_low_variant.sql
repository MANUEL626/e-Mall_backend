-- Variante video ultra compatible pour le feed mobile.

ALTER TABLE public.organization_article_posts
    ADD COLUMN IF NOT EXISTS video_mobile_low_storage_path text;

UPDATE public.organization_article_posts
SET processing_status = 'failed',
    processing_error = 'Video a retraiter en variante mobile_low',
    active = false
WHERE media_kind = 'video'
  AND video_mobile_low_storage_path IS NULL;

DROP VIEW IF EXISTS public.customer_article_post_feed;

CREATE VIEW public.customer_article_post_feed AS
SELECT
    p.slot,
    p.media_kind,
    COALESCE(p.video_mobile_low_storage_path, p.media_storage_path) AS media_storage_path,
    p.video_mobile_low_storage_path,
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
      OR (
          p.processing_status = 'ready'
          AND p.video_mobile_low_storage_path IS NOT NULL
      )
  );

COMMENT ON VIEW public.customer_article_post_feed IS
    'Posts actifs pour le feed customer. Les videos utilisent la variante mobile_low ultra compatible.';

GRANT SELECT ON public.customer_article_post_feed TO service_role;
