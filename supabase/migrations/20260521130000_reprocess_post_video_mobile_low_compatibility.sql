-- La variante mobile_low 512x912/30fps peut encore echouer sur certains
-- decodeurs materiels Android. On masque les videos deja preparees pour
-- forcer leur remplacement/retraitement avec la variante plus conservatrice :
-- max 432x768, 24fps, bitrate plus bas, dimensions multiples de 16.
UPDATE public.organization_article_posts
SET processing_status = 'failed',
    processing_error = 'Video a retraiter avec le format mobile_low compatibilite renforcee.',
    active = false,
    updated_at = now()
WHERE media_kind = 'video'
  AND video_mobile_low_storage_path IS NOT NULL
  AND video_mobile_low_storage_path LIKE '%/processed/mobile-low.mp4';
