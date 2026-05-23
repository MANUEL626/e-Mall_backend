-- Les premieres variantes mobile_low ont pu etre generees avec des dimensions
-- non alignees sur 16 (ex. 540x304). Certains decodeurs materiels Android
-- reconfigurent alors les buffers en lecture et peuvent echouer.
--
-- On masque ces videos deja pretes pour forcer leur remplacement/retraitement
-- avec le nouveau pipeline FFmpeg (max 512x912, dimensions multiples de 16).
UPDATE public.organization_article_posts
SET processing_status = 'failed',
    processing_error = 'Video a retraiter avec le nouveau format mobile_low compatible Android.',
    active = false,
    updated_at = now()
WHERE media_kind = 'video'
  AND video_mobile_low_storage_path IS NOT NULL
  AND video_mobile_low_storage_path LIKE '%/processed/mobile-low.mp4';
