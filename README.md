# e-Mall Backend

Backend FastAPI de la plateforme e-Mall. Le projet sert deux fronts principaux :

- une app customer Flutter : inscription par telephone, catalogue, feed, panier, commandes, suivi, messagerie ;
- un back-office membre Next.js : organisations, boutiques, articles, stock, ventes, livraisons, abonnements, rapports et agent IA.

La base de donnees, l'authentification, le stockage, le temps reel et les policies RLS sont portes par Supabase/Postgres. L'API FastAPI orchestre les workflows metier, les validations, les appels Stripe et les integrations IA.

## Etat Fonctionnel

Les grands blocs deja implementes :

- Auth customer : OTP Supabase cote mobile, bootstrap profil customer via API.
- Profils : `users`, `customers`, `members`, parametres customer/member avec langue, localisation et extra.
- Organisations : inscription membre + organisation, devise par defaut, profil organisation.
- Boutiques : une organisation peut avoir plusieurs boutiques `sales`, `delivery`, `repair`, `rental`.
- Membres boutique : affectation par `shop_ids`, roles boutique, acces via `/members/me`.
- Catalogue marchand : articles, images, devise de vente, stock local par boutique.
- Stocks multi-boutiques : stock separe par boutique, propagation controlee selon le type de boutique.
- Posts articles : image/video, slots illimites, traitement video backend avec `ffmpeg`.
- Catalogue customer : produits, recherche, filtres, feed de posts, liens de partage.
- Wishlist et paniers : paniers groupes par `organization_id + shop_id`.
- Commandes customer : pickup, delivery, vente comptoir, QR, historique, recus.
- Commandes fournisseur : lignes, prix total, prix unitaire calcule, reception qui augmente le stock.
- Livraison : assignation, QR livreur, tracking GPS HTTP existant, guide WebSocket cible.
- Messagerie : conversations directes et messages, Realtime Supabase.
- Abonnements organisation : Freemium, Standard, Premium, droits, restrictions backend.
- Stripe : checkout, Customer Portal, webhooks, factures/recus d'abonnement.
- Performance : dashboard agrege, rapports mensuel/annuel/stock/finance/ventes/tendances.
- Agent IA performance : OpenRouter avec 3 cles et 5 modeles gratuits, fallback OpenAI/Anthropic.
- Reparation/location : domaines MVP par boutique `repair` et `rental`.

## Stack

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic v2
- Supabase Python client
- Postgres/Supabase migrations SQL
- Stripe API HTTP
- OpenRouter, OpenAI et Anthropic optionnels
- Docker / Docker Compose

## Structure Du Projet

```text
.
├── main.py                         # Creation FastAPI, CORS, routers
├── config/
│   ├── supabase_client.py           # Clients Supabase, JWT, service role, erreurs transport
│   └── redirect_urls.py             # URLs autorisees / redirections
├── features/
│   ├── auth/                        # Bootstrap customer apres OTP Supabase
│   ├── users/                       # Profil utilisateur applicatif
│   ├── customers/                   # Catalogue, params, wishlist, paniers, abonnements customer
│   ├── members/                     # Profil membre connecte, params, abonnes boutique
│   ├── organizations/               # Organisations, boutiques, membres d'organisation
│   ├── organization_articles/       # Articles, stock boutique, ressources repair/rental
│   ├── organization_article_posts/  # Posts image/video par article
│   ├── organization_article_orders/ # Commandes fournisseur et reception stock
│   ├── customer_sales/              # Ventes customer, walk-in, livraison, recus, QR
│   ├── messaging/                   # Conversations et messages
│   ├── performance/                 # Rapports, tendances, agent IA
│   ├── organization_subscriptions/  # Plans, droits, Stripe
│   ├── organization_repairs/        # Demandes de reparation
│   ├── organization_rentals/        # Reservations/location
│   ├── share/                       # Liens de partage et App Links
│   └── admin/                       # Routes admin historiques
├── supabase/
│   ├── config.toml
│   └── migrations/                  # Schema, RLS, triggers, RPC, vues analytics
├── guide_*.md                       # Guides metier et integration front
├── docs/                            # Notes historiques
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

Chaque domaine suit globalement le pattern :

- `*_route.py` : endpoints FastAPI, auth HTTP, mapping erreurs ;
- `*_service.py` : logique metier et appels Supabase ;
- `*_models.py` : schemas Pydantic d'entree/sortie.

## Prise En Main Locale

### 1. Preparer l'environnement

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Sous Windows PowerShell :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Renseigner ensuite `.env` avec au minimum :

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_KEY`

### 2. Base Supabase

Le projet peut utiliser :

- un projet Supabase cloud ;
- ou Supabase local via `supabase start`.

Appliquer les migrations :

```bash
supabase db push
```

Les migrations couvrent le schema initial, les buckets Storage, les policies RLS, la messagerie, les articles, les ventes, les abonnements, les rapports, les boutiques et les domaines reparation/location.

### 3. Lancer l'API

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Ou avec Docker :

```bash
docker compose up --build
```

L'API est ensuite disponible sur :

- API : `http://localhost:8000`
- Swagger : `http://localhost:8000/docs`
- OpenAPI JSON : `http://localhost:8000/openapi.json`

## Variables D'Environnement

Voir [.env.example](.env.example).

Groupes principaux :

- Supabase : `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`
- Securite interne : `INTERNAL_API_BEARER`, `CUSTOMER_SALE_QR_PEPPER`
- Liens de partage : `SHARE_BASE_URL`, `SHARE_APP_SCHEME`, Android/iOS store IDs
- Video : `FFMPEG_BINARY`, `FFPROBE_BINARY`
- Agent IA : `OPENROUTER_API_KEY_1..3`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Stripe : `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, URLs success/cancel/portal

La `SUPABASE_SERVICE_KEY` ne doit jamais etre exposee aux fronts. Elle est reservee au backend.

## Authentification Et Profils

### Customer Flutter

1. Le front Flutter utilise Supabase Auth pour envoyer et verifier l'OTP telephone.
2. Apres obtention du JWT Supabase, il appelle :
   - `POST /api/v1/auth/customer/bootstrap`
   - puis optionnellement `PATCH /api/v1/auth/customer/profile`
3. Les routes customer utilisent `Authorization: Bearer <supabase_access_token>`.

Guide detaille : [guide_flutter.md](guide_flutter.md).

### Membre / Marchand Next.js

L'inscription membre + organisation passe par :

```text
POST /api/v1/organizations/register-with-member
```

L'API cree :

- le profil `public.users` ;
- la ligne `members` ;
- l'organisation ;
- la boutique par defaut ;
- l'abonnement Freemium actif.

Apres inscription, le front se connecte avec Supabase `signInWithPassword`, puis appelle :

```text
GET /api/v1/members/me
```

Cette reponse contient les organisations du membre et les boutiques accessibles. C'est la source principale pour le switch multi-boutiques.

Guide detaille : [guide_member_nextjs.md](guide_member_nextjs.md).

## Architecture Organisation / Boutique

Le modele cible est :

- `organizations` : entite administrative, facturation, abonnement, rapports consolides ;
- `organization_shops` : unite operationnelle avec `shop_type` ;
- `organization_shop_members` : affectation des membres aux boutiques ;
- `organization_shop_article_stocks` : stock local par boutique.

Types de boutiques :

- `sales` : vente, catalogue, commandes, stock de produits vendus ;
- `delivery` : livraison / logistique ;
- `repair` : reparation, demandes, consommables et outils ;
- `rental` : location, biens louables et reservations.

Regles importantes :

- le type choisi a l'inscription devient le `shop_type` de la boutique par defaut ;
- `organizations.org_type` reste present pour compatibilite mais n'est plus la source cible ;
- quand un admin cree une boutique, il est affecte automatiquement a cette boutique en `shop_admin` ;
- les workflows operationnels doivent utiliser un `shop_id`.

Guide d'architecture : [guide_structure_organisation.md](guide_structure_organisation.md).

## Endpoints Principaux

La reference exhaustive est Swagger et les guides front. Vue d'ensemble :

### Auth / profils

```text
POST  /api/v1/auth/customer/bootstrap
PATCH /api/v1/auth/customer/profile
GET   /api/v1/customers/me
PATCH /api/v1/customers/me
GET   /api/v1/customers/me/params
PATCH /api/v1/customers/me/params
GET   /api/v1/members/me
PATCH /api/v1/members/me/profile
GET   /api/v1/members/me/params
PATCH /api/v1/members/me/params
```

### Organisations, boutiques et membres

```text
POST  /api/v1/organizations/register-with-member
PATCH /api/v1/organizations/{organization_id}
GET   /api/v1/organizations/{organization_id}/shops
POST  /api/v1/organizations/{organization_id}/shops
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}
PATCH /api/v1/organizations/{organization_id}/shops/{shop_id}
POST  /api/v1/organizations/{organization_id}/members/invite
GET   /api/v1/organizations/{organization_id}/members
PATCH /api/v1/organizations/{organization_id}/members/{member_id}
```

L'ajout d'un membre a une boutique se fait via `shop_ids` a l'invitation ou via le `PATCH` membre.

### Articles, stock et posts

```text
GET    /api/v1/organizations/{organization_id}/articles?shop_id=...
POST   /api/v1/organizations/{organization_id}/shops/{shop_id}/articles
GET    /api/v1/organizations/{organization_id}/shops/{shop_id}/articles
PATCH  /api/v1/organizations/{organization_id}/shops/{shop_id}/articles/{article_id}
PATCH  /api/v1/organizations/{organization_id}/shops/{shop_id}/articles/{article_id}/stock
GET    /api/v1/organizations/{organization_id}/shops/{shop_id}/stock-resources
POST   /api/v1/organizations/{organization_id}/shops/{shop_id}/stock-resources
GET    /api/v1/organizations/{organization_id}/articles/{article_id}/posts
PUT    /api/v1/organizations/{organization_id}/articles/{article_id}/posts/{slot}
DELETE /api/v1/organizations/{organization_id}/articles/{article_id}/posts/{slot}
```

### Customer catalogue, panier et commandes

```text
GET    /api/v1/customers/products
GET    /api/v1/customers/products/search
GET    /api/v1/customers/products/filter
GET    /api/v1/customers/trending-products
GET    /api/v1/customers/posts/feed
GET    /api/v1/customers/wishlist
POST   /api/v1/customers/wishlist/items
DELETE /api/v1/customers/wishlist/items/{organization_article_id}
GET    /api/v1/customers/carts
POST   /api/v1/customers/carts/items
PATCH  /api/v1/customers/carts/items/{line_id}
DELETE /api/v1/customers/carts/items/{line_id}
POST   /api/v1/customer-sales
GET    /api/v1/customer-sales
GET    /api/v1/customer-sales/{order_id}/receipt
POST   /api/v1/customer-sales/{order_id}/confirm-receipt
```

### Ventes marchand et livraison

```text
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales
POST  /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales/walk-in
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales/{order_id}
PATCH /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales/{order_id}/status
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales/{order_id}/receipt
POST  /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales/{order_id}/assign-delivery
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/customer-sales/{order_id}/delivery-qr
GET   /api/v1/customer-sales/delivery-assignments
POST  /api/v1/customer-sales/{order_id}/delivery-track
```

Guide ventes : [guide_sales.md](guide_sales.md). Guide evolution livraison WebSocket : [guide_livraison.md](guide_livraison.md).

### Commandes fournisseur

```text
GET  /api/v1/organizations/{organization_id}/shops/{shop_id}/article-orders
POST /api/v1/organizations/{organization_id}/shops/{shop_id}/article-orders
GET  /api/v1/organizations/{organization_id}/shops/{shop_id}/article-orders/{order_id}
POST /api/v1/organizations/{organization_id}/shops/{shop_id}/article-orders/{order_id}/receive
POST /api/v1/organizations/{organization_id}/shops/{shop_id}/article-orders/{order_id}/cancel
```

La creation recoit `total_price` par ligne ; l'API calcule `unit_price`. Le stock augmente uniquement a la reception.

### Reparation et location

```text
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/repairs
POST  /api/v1/organizations/{organization_id}/shops/{shop_id}/repairs
PATCH /api/v1/organizations/{organization_id}/shops/{shop_id}/repairs/{repair_id}/status
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/repairs/{repair_id}/parts
POST  /api/v1/organizations/{organization_id}/shops/{shop_id}/repairs/{repair_id}/parts
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/rentals
GET   /api/v1/organizations/{organization_id}/shops/{shop_id}/rentals/availability
POST  /api/v1/organizations/{organization_id}/shops/{shop_id}/rentals
PATCH /api/v1/organizations/{organization_id}/shops/{shop_id}/rentals/{reservation_id}/status
```

### Abonnements organisation et Stripe

```text
GET  /api/v1/organization-subscriptions/plans
GET  /api/v1/organization-subscriptions/organizations/{organization_id}
GET  /api/v1/organization-subscriptions/organizations/{organization_id}/entitlements
POST /api/v1/organization-subscriptions/organizations/{organization_id}/checkout
POST /api/v1/organization-subscriptions/organizations/{organization_id}/portal
GET  /api/v1/organization-subscriptions/organizations/{organization_id}/invoices
POST /api/v1/stripe/webhook
```

Plans :

- Freemium : catalogue de base, stock simple, ventes comptoir, 1 membre.
- Standard : articles/commandes illimites, pickup/livraison, dashboard de ventes.
- Premium : GPS temps reel, roles avances, messagerie equipe/client, support prioritaire, IA.

Guide : [guide_abonnement.md](guide_abonnement.md).

### Performance et IA

```text
GET  /api/v1/organizations/{organization_id}/performance/dashboard-summary
GET  /api/v1/organizations/{organization_id}/performance/monthly-summary
GET  /api/v1/organizations/{organization_id}/performance/weekly-sales
GET  /api/v1/organizations/{organization_id}/performance/yearly-summary
GET  /api/v1/organizations/{organization_id}/performance/inventory-summary
GET  /api/v1/organizations/{organization_id}/performance/by-activity
GET  /api/v1/organizations/{organization_id}/performance/top-products
GET  /api/v1/organizations/{organization_id}/performance/trending-products
GET  /api/v1/organizations/{organization_id}/performance/financial-summary
GET  /api/v1/organizations/{organization_id}/performance/sales-status
GET  /api/v1/organizations/{organization_id}/performance/ai-context
GET  /api/v1/organizations/{organization_id}/performance/agent/capabilities
POST /api/v1/organizations/{organization_id}/performance/agent
```

Guide : [guide_performance.md](guide_performance.md).

### Messagerie

```text
POST /api/v1/messaging/conversations
GET  /api/v1/messaging/conversations
GET  /api/v1/messaging/conversations/{conversation_id}/messages
POST /api/v1/messaging/conversations/{conversation_id}/messages
```

Le temps reel se fait avec Supabase Realtime cote front.

## Base De Donnees Et Migrations

Les migrations Supabase sont dans [supabase/migrations](supabase/migrations).

Themes couverts :

- schema initial : utilisateurs, admins, membres, organisations ;
- auth customer et bootstrap RPC ;
- buckets Storage `avatars`, articles et posts ;
- articles, stock, posts, video processing ;
- messagerie et RPC des derniers messages ;
- wishlist, paniers, abonnements customer ;
- ventes customer, QR, historique, livraison et tracking ;
- devises, commandes fournisseur, prix lignes ;
- performance, vues analytics, tendances, agregats ;
- abonnements organisation, plans, Stripe monthly/yearly ;
- index de performance ;
- boutiques, membres boutique, stock boutique ;
- catalogue customer avec contexte boutique ;
- reparation/location ;
- deprecation progressive des champs legacy.

## Stock Et Donnees Metier A Ne Pas Confondre

- `organization_articles` represente le catalogue de vente de l'organisation.
- `organization_shop_article_stocks` porte le stock reel par boutique.
- Les boutiques `repair` et `rental` utilisent des ressources de stock dediees via `stock-resources`.
- Les ventes customer decrementent le stock de la boutique cible.
- Les commandes fournisseur augmentent le stock seulement au moment de la reception.
- Les anciennes colonnes de stock dans `organization_articles` restent pour compatibilite, mais les nouveaux ecrans doivent utiliser `shop_id`.

## Restrictions Abonnement

Les restrictions sont appliquees cote backend, pas seulement dans le front. Les feature gates couvrent notamment :

- nombre de membres ;
- articles actifs ;
- posts ;
- commandes fournisseur ;
- pickup/livraison ;
- assignation livreur ;
- GPS ;
- rapports avances et IA.

Le front doit lire les droits effectifs via :

```text
GET /api/v1/organization-subscriptions/organizations/{organization_id}/entitlements
```

## Realtime

Supabase Realtime est utilise pour les mises a jour de tables :

- articles ;
- posts ;
- commandes customer ;
- tracking livraison existant ;
- messages.

Pour le GPS live livreur a grande echelle, [guide_livraison.md](guide_livraison.md) recommande une architecture WebSocket dediee.

## Guides Importants

- [guide_flutter.md](guide_flutter.md) : integration Flutter customer.
- [guide_member_nextjs.md](guide_member_nextjs.md) : integration Next.js back-office.
- [guide_structure_organisation.md](guide_structure_organisation.md) : architecture multi-boutiques.
- [guide_abonnement.md](guide_abonnement.md) : plans, restrictions, Stripe.
- [guide_performance.md](guide_performance.md) : rapports, tendances, agent IA.
- [guide_livraison.md](guide_livraison.md) : diagnostic livraison et cible WebSocket.
- [guide_sales.md](guide_sales.md) : ventes client, QR, statuts, stock.
- [guide_new_post_video_flux_backend.md](guide_new_post_video_flux_backend.md) : traitement video backend.
- [guide_new_post_video_flux_nextjs_member.md](guide_new_post_video_flux_nextjs_member.md) : integration posts cote membre.

## Verification Rapide

Compiler les modules Python :

```bash
python -m py_compile main.py
python -m py_compile features/organizations/organizations_service.py
```

Verifier le demarrage :

```bash
uvicorn main:app --reload
```

Puis ouvrir :

```text
http://localhost:8000/docs
```

## Points D'Attention

- Ne jamais exposer la `SUPABASE_SERVICE_KEY` aux fronts.
- Les fronts doivent envoyer le JWT Supabase dans `Authorization: Bearer ...`.
- Les nouveaux workflows operationnels doivent toujours utiliser `shop_id`.
- Pour eviter les lenteurs, le front doit preferer `dashboard-summary` aux appels performance separes quand il affiche un dashboard complet.
- Apres creation d'une boutique, rafraichir `/api/v1/members/me` pour mettre a jour le switcher boutique.
- Les guides front doivent etre mis a jour en meme temps que tout changement d'endpoint.
