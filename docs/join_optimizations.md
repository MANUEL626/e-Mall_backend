# Audit des requêtes — Optimisation par jointures et embeddings (Supabase/PostgREST)

Objectif:
- Réduire les allers/retours et le coût réseau en groupant les lectures liées (éviter N+1).
- Uniformiser les sélections imbriquées (embeddings) pour livrer des réponses complètes et cohérentes.
- S’appuyer sur PostgREST/Supabase: `select` avec ressources embarquées, vues SQL et RPC si nécessaire.

Contenu:
- Méthodologie d’audit (automatique + revue manuelle)
- Règles générales (indexes, RLS, pagination)
- Patterns d’embedding (avec exemples)
- Requêtes candidates par domaines fonctionnels
- Suivi d’actions et checklist de validation

---

## 1) Méthodologie d’audit

1. Scan automatique du code:
   - Utiliser le script tools/scan_queries.py pour extraire les appels `supabase.table(...).select(...)`, `from_(...)`, `rpc(...)`.
   - Classer par fichier/table et repérer les chaînes d’appels fragmentées (plusieurs requêtes consécutives pour enrichir le même objet).
2. Revue manuelle:
   - Identifier les endpoints qui listent des entités principales (commandes, articles, conversations) puis chargent leurs détails dans des boucles (N+1).
   - Vérifier les champs fréquemment “rejoints” (articles, images, stock, membres, profil client, derniers messages/points GPS).
3. Proposition d’optimisation:
   - Fusionner les lectures en une seule requête avec `select` imbriqué (embedding) quand c’est supporté.
   - Sinon, créer une vue SQL ou une RPC pour agréger/joiner côté base, avec indexation adéquate.

Commande suggérée (depuis la racine du projet):
- Rapport texte:
  python tools/scan_queries.py
- Rapport JSON:
  python tools/scan_queries.py --json > queries.json

---

## 2) Règles générales

- Préférer l’embedding PostgREST pour des relations 1—N et N—1 simples:
  - select="*, related_table(*), other:alias_table!fk_name(*)"
- Paginer systématiquement les listes (range/limit) et ordonner par un index trié.
- Ajouter des indexes sur les colonnes de jointure/filtrage:
  - FKs: organization_id, shop_id, customer_id, article_id, order_id, conversation_id, created_at.
- RLS (Row Level Security):
  - Vérifier que les embeddings n’exposent pas de colonnes interdites; restreindre les colonnes avec `select` explicite.
- Agrégations (compte, last_message, last_location, unread_count, total_amount):
  - Utiliser vues matérialisées ou RPC si l’embedding seul ne couvre pas le besoin efficacement.

---

## 3) Patterns d’embedding — Exemples Supabase (Python)

- Liste articles d’une boutique (avec images et stock):
  supabase.table("organization_articles").select(
      "id,title,price,shop_id,"
      "organization_article_images(url,position),"
      "organization_article_stocks(quantity,updated_at)"
  ).eq("shop_id", shop_id).order("updated_at", desc=True).range(0, 49)

- Commandes client par boutique (avec lignes + article minimal):
  supabase.table("organization_customer_sales").select(
      "id,status,total_amount,currency,created_at,"
      "organization_customer_sale_order_lines("
          "id,quantity,unit_price,article_id,"
          "organization_articles(id,title,thumbnail_url)"
      "),"
      "customer_profile(id,display_name,phone)"
  ).eq("shop_id", shop_id).order("created_at", desc=True).range(0, 49)

- Conversations avec dernier message (recommandé: vue/RPC):
  # soit une vue v_conversations_with_last_message
  supabase.table("v_conversations_with_last_message").select("*").eq("member_id", member_id).range(0, 49)

- Dernière position de livraison (recommandé: vue/RPC pour limiter à 1 point/commande):
  supabase.rpc("get_last_delivery_points", {"order_ids": order_ids})

Remarque: pour des limites/ordres au niveau des tables imbriquées, privilégier une vue/RPC; les limites par sous-sélection restent limitées côté PostgREST.

---

## 4) Requêtes candidates par domaine

A. Catalogue / Articles d’organisation
- Objectif: éviter 3 requêtes (articles, images, stock) → 1 requête avec embeddings.
- Embeddings cibles:
  - organization_article_images(url, position)
  - organization_article_stocks(quantity, updated_at)
  - optionnel: catégories/tags si existants (article_categories(*))
- Indexes: (shop_id), (organization_id, updated_at), FKs article_id sur images/stock.

B. Commandes clients (liste + détail)
- Objectif: fusionner chargement commande + lignes + article (title/thumbnail) + profil client.
- Embeddings cibles:
  - organization_customer_sale_order_lines(id, quantity, unit_price, organization_articles(id, title, thumbnail_url))
  - customer_profile(id, display_name, phone)
- “Last delivery point”:
  - Utiliser une vue matérialisée v_customer_sales_last_point(order_id, latitude, longitude, captured_at) et l’embarquer, ou un RPC `get_last_delivery_points`.

C. Articles — Stocks en vue “magasin”
- Objectif: tableau stock avec article+alertes en une passe.
- Embeddings cibles:
  - organization_articles(id, title, sku)
  - organization_article_stocks(quantity, min_threshold, updated_at)
- Ajouter un index (shop_id, updated_at DESC) pour le tri.

D. Commandes fournisseur (organization_article_orders)
- Objectif: éviter N+1 sur lignes→article/supplier.
- Embeddings cibles:
  - organization_article_order_lines(id, quantity, unit_cost, organization_articles(id, title, sku))
  - supplier_organization(id, name) si relation
- Vue de synthèse:
  - v_article_orders_with_totals(order_id, total_lines, total_amount) pour les listes.

E. Messagerie
- Objectif: conversations avec dernier message et compteur non-lus sans 2-3 allers/retours.
- Recommandé:
  - Vue SQL v_conversations_with_last_message (conversation_id, last_message_id, content, sent_at, sender_id)
  - Vue/func unread_count par conversation (index sur (conversation_id, is_read=false))
- Embedding minimum (si non-vue):
  - messages(order(created_at.desc), limit:1) → souvent mieux via vue.

F. Membres / Organisations / Abonnements
- Embeddings cibles:
  - organization_members(member_id, role, organization(id, name))
  - organization_subscription(plan(id, name), rights(*))
- Indexes: (member_id, organization_id), (organization_id, plan_id).

G. Réparations / Locations
- Détail des tickets avec client et article loué:
  - customer_profile(id, display_name), rental_item(id, title, sku)
- Historique:
  - Préférer une vue agrégée pour compte/états.

H. Performance / Analytics
- Rapports (mensuels/financiers) → privilégier vues matérialisées et/ou tables d’agrégats calculées par jobs:
  - v_sales_monthly(org_id, shop_id, month, revenue, orders, aov)
- Les écrans consomment ces vues (une seule requête) plutôt que recalculer à la volée.

---

## 5) Plan d’action (proposé)

1) Identifier top endpoints “liste + enrichissements” (catalogue, ventes par boutique, conversations).
2) Remplacer N+1 par une seule requête avec `select` imbriqué (si possible).
3) Créer 2-3 vues clés:
   - v_conversations_with_last_message (+ unread_count via jointure)
   - v_customer_sales_last_point
   - v_article_orders_with_totals
4) Indexer les colonnes de filtrage et tri utilisées par ces vues.
5) Tester sur échantillons de données réelles (latences P95/P99).
6) Sécuriser: restreindre les colonnes des embeddings à ce qui est autorisé (RLS).

---

## 6) Checklist de validation

- [ ] Chaque liste paginée (limit/range) avec ordre indexé
- [ ] Aucune boucle côté serveur/clients qui déclenche des lectures article-par-article
- [ ] Embeddings limités aux champs nécessaires (pas de surcharge réseau)
- [ ] Index présents pour FKs et filtres courants
- [ ] Vues/RPC testées et couvertes par RLS
- [ ] P95 latence < 200–300 ms pour listes principales en prod

---

## 7) Suivi

- Lancer `python tools/scan_queries.py` et trier les résultats par modules.
- Pour chaque requête candidate, ouvrir un ticket “Fusion via embedding/vues” et lier la MR correspondante.
- Mesurer avant/après (latence et volume octets) pour valider le gain.
