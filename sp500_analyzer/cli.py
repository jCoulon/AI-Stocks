"""Point d'entrée en ligne de commande."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .engine import run_analysis
from .providers.mock import MockDataProvider
from .report import render_html, render_text, to_json


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sp500-analyzer",
        description="Analyse des mouvements des actions du S&P 500 (cours, news, réseaux sociaux, macro). "
                    "Outil d'analyse, pas un conseil financier.",
    )
    p.add_argument("-t", "--ticker", action="append", default=[],
                   help="Limiter l'analyse à ce titre et afficher son détail (répétable)")
    p.add_argument("--detail", action="append", default=[], help="Afficher le détail d'un titre (répétable)")
    p.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 25),
                   help="Dernière séance des données simulées (AAAA-MM-JJ, défaut 2026-09-25)")
    p.add_argument("--seed", type=int, default=42, help="Graine des données simulées")
    p.add_argument("--json", metavar="FICHIER", help="Exporter le rapport complet en JSON")
    p.add_argument("--html", metavar="FICHIER", help="Exporter un rapport HTML autonome")
    p.add_argument("--no-color", action="store_true", help="Désactiver les couleurs du terminal")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider = MockDataProvider(as_of=args.as_of, seed=args.seed)

    known = {s.ticker for s in provider.universe()}
    unknown = [t for t in args.ticker + args.detail if t.upper() not in known]
    if unknown:
        print(f"Titre(s) inconnu(s) : {', '.join(unknown)}. Disponibles : {', '.join(sorted(known))}",
              file=sys.stderr)
        return 2

    report = run_analysis(provider, args.ticker or None)
    color = sys.stdout.isatty() and not args.no_color
    print(render_text(report, color=color, detail=args.ticker + args.detail))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(to_json(report))
        print(f"Rapport JSON écrit dans {args.json}")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(report))
        print(f"Rapport HTML écrit dans {args.html}")
    return 0
