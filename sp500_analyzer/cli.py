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
    p.add_argument("--univers", choices=["sp500", "ia", "tout"], default=None,
                   help="Univers analysé avec des données réelles : sp500 (défaut), ia (focus IA) ou tout")
    p.add_argument("--asymetrie", action="store_true",
                   help="Écran d'asymétrie du focus IA (potentiel vs risque) ; nécessite --donnees")
    p.add_argument("--best-try", action="store_true",
                   help="Écran « Best try » : titres ayant un catalyseur daté prochainement (résultats, lock-up...) ; "
                        "nécessite --donnees")
    p.add_argument("--surveillance", nargs="?", const="", metavar="TITRES",
                   help="Liste de surveillance : conditions d'entrée des titres suivis ; « --surveillance FIGR,AIP » "
                        "remplace la liste enregistrée (~/.sp500_analyzer/watchlist.json)")
    p.add_argument("--journal", action="store_true",
                   help="Journal des prévisions : notes des avis, de la grille d'entrée et des mouvements attendus "
                        "(historique vs options) une fois l'horizon écoulé ; nécessite --donnees")
    p.add_argument("--polymarket", action="store_true",
                   help="Écran Polymarket (meilleurs portefeuilles, marchés sous-évalués, suivi) depuis data/polymarket")
    p.add_argument("--horizon", type=int, default=60, help="Horizon de l'écran « Best try », en jours (défaut 60)")
    p.add_argument("--telecharger-cours", metavar="DOSSIER",
                   help="Télécharger les cours quotidiens depuis Stooq dans ce dossier puis quitter")
    return p


def _asymmetry(provider, args) -> int:
    from pathlib import Path

    from .analysis.asymmetry import build_row, render_asymmetry, score_rows
    from .providers.fundamentals import load_fundamentals
    from .universe import AI_THEME

    try:
        report = Orchestrator(provider, max_workers=args.workers).run()
        labels = {t.security.ticker: (t.short.label, t.medium.label) for t in report.tickers}
    except OrchestrationError as e:
        print(f"Analyse des agents indisponible ({e}) : écran sans avis", file=sys.stderr)
        labels = {}
    rows = []
    for sec in provider.universe():
        bars = provider.price_history(sec.ticker)
        if len(bars) < 30:
            continue
        row = build_row(sec.ticker, sec.name, AI_THEME.get(sec.ticker, sec.sector), bars,
                        load_fundamentals(Path(args.donnees), sec.ticker))
        row.short_label, row.medium_label = labels.get(sec.ticker, ("", ""))
        rows.append(row)
    print(render_asymmetry(score_rows(rows)))
    return 0


def _best_try(provider, args) -> int:
    from .analysis.besttry import render_besttry, screen

    try:
        report = Orchestrator(provider, max_workers=args.workers).run()
        labels = {t.security.ticker: (t.short.label, t.medium.label) for t in report.tickers}
    except OrchestrationError as e:
        print(f"Analyse des agents indisponible ({e}) : écran sans avis", file=sys.stderr)
        labels = {}
    rows, market, _ = screen(provider, args.donnees, args.horizon, labels)
    print(render_besttry(rows, provider.as_of, args.horizon, market))
    return 0


def _watchlist(provider, args) -> int:
    from datetime import date as _date
    from pathlib import Path

    from .analysis.watchlist import assess, load_watchlist, render_text, save_watchlist
    from .providers.events import load_events
    from .providers.fundamentals import load_fundamentals

    tickers = save_watchlist(args.surveillance.split(",")) if args.surveillance else load_watchlist()
    report = Orchestrator(provider, max_workers=args.workers).run()
    by = {t.security.ticker: t for t in report.tickers}
    root = Path(args.donnees) if args.donnees else None
    views = []
    for tk in tickers:
        if tk not in by:
            continue
        ev = (load_events(root, tk) or {}).get("next_earnings") if root else None
        nxt = (_date.fromisoformat(ev["date"]), "Résultats") if ev else None
        views.append(assess(by[tk], load_fundamentals(root, tk) if root else None, nxt, report.as_of,
                            report.macro_summary))
    print(render_text(views, [t for t in tickers if t not in by], report.as_of))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.journal:
        from pathlib import Path

        from .analysis.journal import read, render_text as render_journal, score
        from .providers.csv_prices import CsvPriceProvider

        root = Path(args.donnees or "data")
        try:
            prices = CsvPriceProvider(root / "daily", universe="tout")
            closes = {s.ticker: [(b.day, b.close) for b in prices.price_history(s.ticker)] for s in prices.universe()}
        except (OSError, ValueError):
            closes = {}
        print(render_journal(score(read(root), closes)))
        return 0

    if args.polymarket:
        import json
        from pathlib import Path

        from .analysis.polymarket import render_text as render_polymarket

        path = Path(args.donnees or "data") / "polymarket" / "report.json"
        if not path.exists():
            print(f"Pas de rapport Polymarket ({path}) : lancez le workflow « Polymarket »", file=sys.stderr)
            return 2
        print(render_polymarket(json.loads(path.read_text(encoding="utf-8"))))
        return 0

    if args.telecharger_cours:
        from .providers.csv_prices import download_stooq

        errors = download_stooq(args.telecharger_cours)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print(f"Cours enregistrés dans {args.telecharger_cours} ({len(errors)} erreur(s)).")
        return 1 if errors else 0

    if (args.asymetrie or args.best_try) and not args.donnees:
        print("Les écrans d'asymétrie et « Best try » nécessitent des données réelles : ajoutez --donnees data",
              file=sys.stderr)
        return 2
    universe = args.univers or ("ia" if args.asymetrie else "tout" if (args.best_try or (args.surveillance is not None
                                                                                          and args.donnees)) else "sp500")
    if universe != "sp500" and not (args.donnees or args.cours):
        print("Les univers « ia » et « tout » nécessitent des données réelles (--donnees ou --cours)", file=sys.stderr)
        return 2

    if args.donnees:
        from .providers.realdata import RealDataProvider

        try:
            provider = RealDataProvider(args.donnees, universe=universe)
        except (OSError, ValueError) as e:
            print(f"Erreur de lecture des données : {e}", file=sys.stderr)
            return 2
        print(f"Données réelles : {provider.coverage()}", file=sys.stderr)
    elif args.cours:
        from .providers.csv_prices import CsvPriceProvider

        try:
            provider = CsvPriceProvider(args.cours, universe=universe)
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

    if args.asymetrie:
        return _asymmetry(provider, args)
    if args.best_try:
        return _best_try(provider, args)
    if args.surveillance is not None:
        return _watchlist(provider, args)

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
