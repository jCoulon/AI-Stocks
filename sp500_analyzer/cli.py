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
    p.add_argument("--backtest", action="store_true",
                   help="Backtest point-in-time des facteurs de recherche (≈ 3 ans d'historique) puis quitter")
    p.add_argument("--backtest-periode", metavar="DEBUT:FIN",
                   help="Backtest de l'outil complet sur une période, ex. 2026-09-01:2026-09-25 (septembre)")
    p.add_argument("--cours", metavar="DOSSIER",
                   help="Utiliser de vrais cours : fichiers CSV <TICKER>.csv et SPX.csv (format Stooq / Yahoo)")
    p.add_argument("--donnees", metavar="DOSSIER",
                   help="Utiliser toutes les données réelles du dossier (cours daily/, news/, sec/, macro/)")
    p.add_argument("--telecharger-cours", metavar="DOSSIER",
                   help="Télécharger les cours quotidiens depuis Stooq dans ce dossier puis quitter")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.telecharger_cours:
        from .providers.csv_prices import download_stooq

        errors = download_stooq(args.telecharger_cours)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print(f"Cours enregistrés dans {args.telecharger_cours} ({len(errors)} erreur(s)).")
        return 1 if errors else 0

    if args.donnees:
        from .providers.realdata import RealDataProvider

        try:
            provider = RealDataProvider(args.donnees)
        except (OSError, ValueError) as e:
            print(f"Erreur de lecture des données : {e}", file=sys.stderr)
            return 2
        print(f"Données réelles : {provider.coverage()}", file=sys.stderr)
    elif args.cours:
        from .providers.csv_prices import CsvPriceProvider

        try:
            provider = CsvPriceProvider(args.cours)
        except (OSError, ValueError) as e:
            print(f"Erreur de lecture des cours : {e}", file=sys.stderr)
            return 2
        if provider.missing:
            print(f"Titres sans fichier de cours (ignorés) : {', '.join(provider.missing)}", file=sys.stderr)
    else:
        history = 300
        if args.backtest_periode:
            # Historique couvrant la période + ~13 mois avant son début (indicateurs sur 252 séances).
            try:
                start = date.fromisoformat(args.backtest_periode.split(":")[0])
                history = max(400, int((args.as_of - start).days * 5 / 7) + 290)
            except ValueError:
                pass  # l'erreur de format est signalée plus bas
        provider = MockDataProvider(as_of=args.as_of, seed=args.seed, history=history)

    known = {s.ticker for s in provider.universe()}
    unknown = [t for t in args.ticker + args.detail + args.stock if t.upper() not in known]
    if unknown:
        print(f"Titre(s) inconnu(s) : {', '.join(unknown)}. Disponibles : {', '.join(sorted(known))}",
              file=sys.stderr)
        return 2

    if args.backtest_periode:
        from .analysis.period_backtest import render_period_backtest, run_period_backtest

        try:
            start_s, end_s = args.backtest_periode.split(":")
            start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
            sessions = sum(1 for d in provider.trading_days() if start <= d <= end)
            horizons = (1, 5, 21) if sessions >= 60 else (1, 5)
            report = run_period_backtest(provider, start, end, horizons=horizons,
                                         progress=lambda d: print(f"  analyse au {d.isoformat()}…", file=sys.stderr))
        except ValueError as e:
            print(f"Période invalide : {e}", file=sys.stderr)
            return 2
        print(render_period_backtest(report))
        return 0

    if args.backtest:
        from .analysis.backtest import render_backtest, run_backtest

        bt_provider = MockDataProvider(as_of=args.as_of, seed=args.seed, history=800)
        print(render_backtest(run_backtest(bt_provider), simulated=True))
        return 0

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
