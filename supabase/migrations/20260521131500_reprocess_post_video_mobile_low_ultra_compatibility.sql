-- La variante 432x768/24fps peut encore echouer sur certains decodeurs
-- materiels Android. On masque les videos deja preparees pour forcer leur
-- remplacement/retraitement avec une variante ultra compatible :
-- canvas fixe 384x704, padding, 24fps, 600kbps, dimensions multiples de 16.
UPDATE public.organization_article_posts
SET processing_status = 'failed',
    processing_error = 'Video a retraiter avec le format mobile_low ultra compatible.',
    active = false,
    updated_at = now()
WHERE media_kind = 'video'
  AND video_mobile_low_storage_path IS NOT NULL
  AND video_mobile_low_storage_path LIKE '%/processed/mobile-low.mp4';
