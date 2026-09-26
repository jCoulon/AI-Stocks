"""Point d'entrée en ligne de commande."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .agents.base import TaskRecord
from .orchestrator import OrchestrationError, Orchestrator
from .providers.mock import MockDataProvider
from .report import render_html, render_stock_sheets, render_text, render_trace, to_json


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sp500-analyzer",
        description="Analyse des mouvements des actions du S&P 500 (cours, news, réseaux sociaux, macro). "
                    "Outil d'analyse, pas un conseil financier.",
    )
    p.add_argument("-t", "--ticker", action="append", default=[],
                   help="Limiter l'analyse à ce titre et afficher son détail (répétable)")
    p.add_argument("--detail", action="append", default=[], help="Afficher le détail d'un titre (répétable)")
    p.add_argument("-s", "--stock", action="append", default=[],
                   help="Analyse par action : n'afficher que la fiche complète de ce titre (répétable)")
    p.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 25),
                   help="Dernière séance des données simulées (AAAA-MM-JJ, défaut 2026-09-25)")
    p.add_argument("--seed", type=int, default=42, help="Graine des données simulées")
    p.add_argument("--json", metavar="FICHIER", help="Exporter le rapport complet en JSON")
    p.add_argument("--html", metavar="FICHIER", help="Exporter un rapport HTML autonome")
    p.add_argument("--no-color", action="store_true", help="Désactiver les couleurs du terminal")
    p.add_argument("--llm", action="store_true",
                   help="Activer l'agent rédacteur (Claude) pour une synthèse en langage naturel "
                        "(nécessite 'pip install anthropic' et une clé API)")
    p.add_argument("--trace", action="store_true", help="Afficher le journal d'exécution des agents")
    p.add_argument("-v", "--verbose", action="store_true", help="Suivre l'avancement des agents en direct")
    p.add_argument("--workers", type=int, default=8, help="Nombre d'agents exécutés en parallèle (défaut 8)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider = MockDataProvider(as_of=args.as_of, seed=args.seed)

    known = {s.ticker for s in provider.universe()}
    unknown = [t for t in args.ticker + args.detail + args.stock if t.upper() not in known]
    if unknown:
        print(f"Titre(s) inconnu(s) : {', '.join(unknown)}. Disponibles : {', '.join(sorted(known))}",
              file=sys.stderr)
        return 2

    def progress(rec: TaskRecord) -> None:
        if args.verbose or rec.status == "failed":
            extra = f" — {rec.error}" if rec.error else ""
            print(f"[{rec.status:>7}] {rec.agent:<16} {rec.task_id}{extra}", file=sys.stderr)

    orchestrator = Orchestrator(provider, use_llm=args.llm, max_workers=args.workers, listener=progress)
    try:
        report = orchestrator.run(focus=(args.ticker + args.stock) or None)
    except OrchestrationError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        for r in e.records:
            if r.status != "done":
                print(f"  {r.task_id} [{r.status}] {r.error}", file=sys.stderr)
        return 1
    color = sys.stdout.isatty() and not args.no_color
    if args.stock and not args.ticker:
        print(render_stock_sheets(report, args.stock, color=color))
    else:
        print(render_text(report, color=color, detail=args.ticker + args.detail + args.stock))
    if args.trace:
        print(render_trace(report, verbose=args.verbose))
    if args.llm and not report.narrative:
        writer = next((r for r in report.trace if r["agent"] == "redacteur"), None)
        print(f"Agent rédacteur indisponible : {writer['error'] if writer else 'non exécuté'}", file=sys.stderr)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(to_json(report))
        print(f"Rapport JSON écrit dans {args.json}")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(report))
        print(f"Rapport HTML écrit dans {args.html}")
    return 0
