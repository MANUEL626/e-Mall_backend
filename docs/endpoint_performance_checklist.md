# Checklist performance endpoints

Objectif : ne pas oublier une famille d'endpoints pendant les optimisations. Le detail complet est dans `guide_endpoint_performance.md`.

Statuts :

- `fait` : optimise cote backend.
- `partiel` : pagination, index ou colonnes ciblees deja en place, mais une RPC peut encore reduire les allers-retours.
- `a faire` : endpoint a auditer/corriger si l'ecran est lent.
- `garder separe` : endpoint simple, detail ou action metier ponctuelle.

## Vente

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/organizations/{organization_id}/articles` | `fait` | RPC articles + stock boutique pour `shop_id`. |
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/articles` | `fait` | RPC `list_shop_articles_with_stock`. |
| `GET /api/v1/organizations/{organization_id}/articles/posts/batch` | `partiel` | Colonnes ciblees + limite 100. |
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/stock-resources` | `partiel` | RPC stock resources si lenteur mesuree. |
| `GET /api/v1/organizations/{organization_id}/customer-sales` | `fait` | RPC ciblee `list_org_customer_sales_with_lines` + fallback + pagination. |
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales` | `fait` | Meme RPC avec filtre boutique. |
| Details, creations, updates, deletes, QR, assignation livraison | `garder separe` | Garder lisible et transactionnel. |

## Location

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/rentals` | `partiel` | Pagination + colonnes ciblees + index. Reste a remplacer le refresh statut ligne par ligne si lenteur. |
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/rentals/proformas` | `partiel` | Pagination + colonnes ciblees + lignes/paiements charges en batch. |
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/rentals/orders` | `partiel` | Pagination + colonnes ciblees + lignes chargees en batch. RPC si tableau lent. |
| Disponibilite, details, PDF/factures, start, return, cancel, payments | `garder separe` | Actions ou details a la demande. |

## Reparation

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/repairs` | `partiel` | Pagination + colonnes ciblees + index. RPC si tableau lent. |
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/repairs/{repair_id}/parts` | `garder separe` | Detail a la demande. |
| Details, creation, edition, transitions, facture, pieces | `garder separe` | Actions metier ponctuelles. |

## Commandes fournisseur

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/organizations/{organization_id}/article-orders` | `fait` | RPC ciblee `list_article_orders_with_lines` + fallback + pagination. |
| `GET /api/v1/organizations/{organization_id}/shops/{shop_id}/article-orders` | `fait` | Meme RPC avec filtre `shop_id`. |
| Detail, creation, reception, annulation | `garder separe` | Garder separe car transactionnel/ponctuel. |

## Customer Flutter

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/customers/products` | `partiel` | Classement personnalise fait. Surveiller index. |
| `GET /api/v1/customers/products/search` | `partiel` | Ajouter index texte/trigram si recherche lente. |
| `GET /api/v1/customers/products/filter` | `partiel` | Verifier index categorie/prix. |
| `GET /api/v1/customers/posts/feed` | `partiel` | Classement personnalise fait. RPC/cache si feed tres consulte. |
| `GET /api/v1/customers/trending-products` | `a faire` | Auditer cout aggregation vues/events. |
| `GET /api/v1/customers/wishlist` | `partiel` | Pagination ajoutee + index. |
| `GET /api/v1/customers/carts` | `partiel` | Pagination ajoutee + chargement deja groupe paniers/lignes/produits. |
| `GET /api/v1/customers/subscriptions` | `partiel` | Pagination ajoutee + index. |
| Actions wishlist, carts, subscriptions, confirm receipt | `garder separe` | Ecritures simples ou transactions. |

## Equipe et organisation

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/members/me` | `partiel` | RPC seulement si dashboard/login lent. |
| `GET /api/v1/members/organizations/{organization_id}/subscribers` | `partiel` | Pagination existante + index abonnements ajoute. |
| `GET /api/v1/organizations/{organization_id}/members` | `partiel` | Pagination + colonnes ciblees ajoutees. |
| `GET /api/v1/organizations/{organization_id}/shops` | `partiel` | Pagination + colonnes ciblees ajoutees. |
| Profile, params, invite, roles, shops create/update, organization patch | `garder separe` | Actions ou petites ressources. |

## Livraison, messages et realtime

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/customer-sales/delivery-assignments` | `partiel` | RPC si lignes/articles trop couteux. |
| `GET /api/v1/messaging/conversations` | `partiel` | Verifier que la RPC dernier message est presente. |
| `GET /api/v1/messaging/conversations/{conversation_id}/messages` | `partiel` | Pagination existante + index `(conversation_id, created_at)`. |
| `GET /api/v1/messaging/organizations/{organization_id}/members` | `partiel` | Pagination ajoutee. Recherche a ajouter si equipe grande. |
| Envoi GPS, tickets websocket, creation conversation, envoi message | `garder separe` | Inserts/actions courtes, Realtime diffuse ensuite. |

## KPI et dashboard

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/organizations/{organization_id}/performance/dashboard-summary` | `partiel` | Profite des RPC inventaire/statuts ; reste monthly/finance/top/trending a fusionner. |
| `GET /api/v1/organizations/{organization_id}/performance/ai-context` | `a faire` | Cache/RPC dedie si appelle plusieurs rapports. |
| `GET /api/v1/organizations/{organization_id}/performance/monthly-summary` | `a faire` | SQL aggregate par periode. |
| `GET /api/v1/organizations/{organization_id}/performance/weekly-sales` | `a faire` | SQL aggregate + index date/statut. |
| `GET /api/v1/organizations/{organization_id}/performance/yearly-summary` | `a faire` | SQL aggregate. |
| `GET /api/v1/organizations/{organization_id}/performance/inventory-summary` | `fait` | RPC aggregate `get_performance_inventory_summary` + fallback. |
| `GET /api/v1/organizations/{organization_id}/performance/top-products` | `a faire` | SQL aggregate + index lignes ventes. |
| `GET /api/v1/organizations/{organization_id}/performance/trending-products` | `a faire` | SQL aggregate/cache. |
| `GET /api/v1/organizations/{organization_id}/performance/financial-summary` | `a faire` | SQL aggregate par periode. |
| `GET /api/v1/organizations/{organization_id}/performance/sales-status` | `fait` | RPC aggregate `get_performance_sales_status_summary` + fallback. |
| Agent IA et capabilities | `garder separe` | Peut consommer le cache KPI. |

## Autres endpoints

| Endpoint | Etat | Action |
|----------|------|--------|
| `GET /api/v1/users/` | `partiel` | Pagination + index `created_at`. |
| `GET /api/v1/admins/` | `partiel` | Pagination + index `created_at`. |
| Abonnement organisation, Stripe, auth customer, share links | `garder separe` | Petites ressources, actions externes ou endpoints publics. |
