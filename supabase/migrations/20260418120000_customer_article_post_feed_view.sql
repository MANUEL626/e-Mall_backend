-- Vue lecture seule pour le feed customer : posts actifs + article actif (jointure).

CREATE OR REPLACE VIEW public.customer_article_post_feed AS
SELECT
    p.slot,
    p.media_kind,
    p.media_storage_path,
    p.caption,
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
  AND a.active IS TRUE;

COMMENT ON VIEW public.customer_article_post_feed IS
    'Posts promotionnels actifs rattachés à des articles actifs (pagination côté API customer).';

GRANT SELECT ON public.customer_article_post_feed TO service_role;
