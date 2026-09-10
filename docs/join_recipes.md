# Recettes de jointures — Corriger les patterns N+1

But:
- Transformer des rafales de requêtes unitaires (dans des boucles) en une seule requête avec JOIN ou récupération en lot (IN).
- Donner des exemples concrets prêts à adapter.

Comment utiliser:
1) Lancer l’audit:
   - python scripts/audit_sql_joins.py --root . --output join_audit_report.md
2) Ouvrir join_audit_report.md et repérer les “Requête potentielle dans une boucle”.
3) Appliquer une des recettes ci-dessous selon le cas d’usage.

---

## 1. Parent + enfants (ex: commandes + lignes)

Problème (N+1):
- Vous listez des commandes, puis pour chaque commande vous refaites une requête pour ses lignes.

Solution SQL (JOIN + agrégation):
