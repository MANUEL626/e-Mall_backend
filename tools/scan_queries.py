#!/usr/bin/env python3
"""
Scan heuristique des appels Supabase (table/from_/select/rpc) pour lister les requêtes
candidates à une consolidation via embeddings/jointures.

Usage:
  python tools/scan_queries.py            # rapport texte
  python tools/scan_queries.py --json     # rapport JSON

Limites:
- Basé sur des expressions régulières, il peut rater des cas complexes ou du code construit dynamiquement.
- Adapte les patterns si besoin selon le style de code du projet.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class QueryHit:
    file: str
    line: int
    table: Optional[str] = None
    select: Optional[str] = None
    filters: Optional[str] = None
    raw: str = ""


TABLE_CHAIN_RE = re.compile(
    r"""
    \.\s*(?:table|from_)      # supabase.table(...) ou supabase.from_(...)
    \(\s*['"](?P<table>[^'"]+)['"]\s*\)
    (?P<chain>(?:\s*\.\s*[a-zA-Z_]+\s*\([^()]*\))*)   # séquence d'appels chaînés simple
    """,
    re.VERBOSE | re.DOTALL,
)

SELECT_RE = re.compile(r"\.\s*select\s*\(\s*([rbu]?['\"])(?P<select>.*?)(?<!\\)\1\s*\)", re.DOTALL)
FILTERS_RE = re.compile(r"\.\s*(eq|in|neq|like|ilike|gte|lte|gt|lt|is_)\s*\([^)]*\)")
RPC_RE = re.compile(r"\.\s*rpc\s*\(\s*['\"](?P<func>[^'\"]+)['\"]\s*,?\s*([^)]*)\)")

IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules",
}


def scan_file(path: str) -> List[QueryHit]:
    hits: List[QueryHit] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (UnicodeDecodeError, FileNotFoundError):
        return hits

    # table/from_ chaînes
    for m in TABLE_CHAIN_RE.finditer(text):
        table = m.group("table")
        chain = m.group("chain") or ""
        select_match = SELECT_RE.search(chain)
        filters = "; ".join(sorted(set(x.group(0) for x in FILTERS_RE.finditer(chain)))) or None
        select = select_match.group("select") if select_match else None

        # approx line number
        start = m.start()
        line = text.count("\n", 0, start) + 1
        raw = text[m.start(): m.end()]
        hits.append(QueryHit(file=path, line=line, table=table, select=select, filters=filters, raw=raw))

    # RPC directes
    for m in RPC_RE.finditer(text):
        func = m.group("func")
        start = m.start()
        line = text.count("\n", 0, start) + 1
        raw = text[m.start(): m.end()]
        hits.append(QueryHit(file=path, line=line, table=f"rpc:{func}", select=None, filters=None, raw=raw))

    return hits


def scan_tree(root: str) -> List[QueryHit]:
    results: List[QueryHit] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            results.extend(scan_file(full))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, default=".", help="Racine du projet à scanner")
    parser.add_argument("--json", action="store_true", help="Sortie JSON (stdout)")
    args = parser.parse_args()

    hits = scan_tree(args.root)

    if args.json:
        print(json.dumps([asdict(h) for h in hits], ensure_ascii=False, indent=2))
        return

    # Rapport texte
    print(f"Requêtes détectées: {len(hits)}\n")
    for h in hits:
        print(f"- {h.file}:{h.line}")
        print(f"  table: {h.table}")
        if h.select:
            # normaliser en une seule ligne courte
            one = " ".join(h.select.split())
            print(f"  select: {one[:160]}{'…' if len(one) > 160 else ''}")
        if h.filters:
            print(f"  filters: {h.filters}")
        # extrait brut tronqué
        snippet = " ".join(h.raw.split())
        print(f"  raw: {snippet[:180]}{'…' if len(snippet) > 180 else ''}")
        print()
    print("Conseil: rechercher des séquences proche-lignes qui effectuent plusieurs requêtes sur la même entité → candidates à fusionner via embeddings/vues.")


if __name__ == "__main__":
    main()
