-- Phase 7 : nettoyage compatibilite.
-- Les colonnes historiques restent presentes pour les anciens ecrans et les vues
-- de transition, mais les nouveaux workflows doivent utiliser les boutiques et
-- organization_shop_article_stocks.

COMMENT ON COLUMN public.organizations.org_type IS
    'DEPRECATED phase 7: conserve pour compatibilite. La source metier du type d activite est organization_shops.shop_type.';

COMMENT ON COLUMN public.organization_articles.stock_quantity IS
    'DEPRECATED phase 7: stock direct conserve pour compatibilite avec la boutique par defaut. Lire/ecrire le stock via organization_shop_article_stocks.';

COMMENT ON COLUMN public.organization_articles.reserved_quantity IS
    'DEPRECATED phase 7: reservation directe conservee pour compatibilite avec la boutique par defaut. Utiliser organization_shop_article_stocks.reserved_quantity.';

COMMENT ON COLUMN public.organization_articles.alert_quantity IS
    'DEPRECATED phase 7: seuil direct conserve pour compatibilite avec la boutique par defaut. Utiliser organization_shop_article_stocks.alert_quantity.';

COMMENT ON COLUMN public.organization_articles.stock_status IS
    'DEPRECATED phase 7: statut direct conserve pour compatibilite avec la boutique par defaut. Utiliser organization_shop_article_stocks.stock_status.';
