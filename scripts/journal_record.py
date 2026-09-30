"""Enregistre dans le journal les prévisions de l'outil pour la dernière séance disponible.

Usage : python scripts/journal_record.py [--out data]
Lancé par le workflow « Données de marché réelles » après la collecte des cours et des options.
"""

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_analyzer.analysis.besttry import screen  # noqa: E402
from sp500_analyzer.analysis.journal import record  # noqa: E402
from sp500_analyzer.analysis.watchlist import assess  # noqa: E402
from sp500_analyzer.orchestrator import Orchestrator  # noqa: E402
from sp500_analyzer.providers.events import load_events  # noqa: E402
from sp500_analyzer.providers.fundamentals import load_fundamentals  # noqa: E402
from sp500_analyzer.providers.realdata import RealDataProvider  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data")
    args = p.parse_args()
    root = Path(args.out)
    provider = RealDataProvider(root, universe="tout")
    report = Orchestrator(provider).run()
    labels = {t.security.ticker: (t.short.label, t.medium.label) for t in report.tickers}
    rows, _, _ = screen(provider, root, 60, labels)
    events = {}
    for r in sorted(rows, key=lambda r: r.days):  # prochain catalyseur de chaque titre
        events.setdefault(r.ticker, r)
    views = {}
    for t in report.tickers:
        ev = (load_events(root, t.security.ticker) or {}).get("next_earnings")
        nxt = (date.fromisoformat(ev["date"]), "Résultats") if ev else None
        views[t.security.ticker] = assess(t, load_fundamentals(root, t.security.ticker), nxt, report.as_of,
                                          report.macro_summary)
    n = record(root, report.as_of, report, views, events, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    with_implied = sum(1 for e in events.values() if e.implied_move is not None)
    print(f"Journal : {n} prévisions enregistrées pour la séance du {report.as_of} "
          f"({len(events)} catalyseur(s), dont {with_implied} avec mouvement anticipé par les options)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
