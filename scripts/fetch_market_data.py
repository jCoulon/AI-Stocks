"""Télécharge de vrais cours (Yahoo Finance) : intraday 10 min sur une période + quotidien ajusté.

Usage : python scripts/fetch_market_data.py --start 2026-09-01 [--end 2026-09-25] [--out data] [--extra IREN]
Lancé par le workflow GitHub Actions « Données de marché réelles » (les runners ont accès à
Internet), qui enregistre ensuite les fichiers CSV dans le dépôt.
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_analyzer.providers.yahoo import download_all  # noqa: E402
from sp500_analyzer.providers.fundamentals import download_fundamentals  # noqa: E402
from sp500_analyzer.providers.events import download_events  # noqa: E402
from sp500_analyzer.providers.options import download_options  # noqa: E402
from sp500_analyzer.universe import EXTRA_TICKERS, SP500_SAMPLE  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    today_ny = datetime.now(ZoneInfo("America/New_York")).date()
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 1))
    p.add_argument("--end", type=date.fromisoformat, default=today_ny)
    p.add_argument("--out", default="data")
    p.add_argument("--daily-years", type=int, default=2)
    p.add_argument("--extra", default="", help="Titres supplémentaires hors univers, séparés par des virgules (ex. IREN)")
    args = p.parse_args()
    # Titres du focus IA hors S&P 500 toujours inclus, plus ceux passés en argument.
    extra = tuple(dict.fromkeys(EXTRA_TICKERS + [t.strip().upper() for t in args.extra.split(",") if t.strip()]))
    # Fondamentaux du jour (objectifs d'analystes, croissance, valorisation) : écran d'asymétrie.
    # En premier : Yahoo limite plus volontiers une session ouverte après une rafale de requêtes.
    tickers = [p.security.ticker for p in SP500_SAMPLE] + list(extra)
    errors = download_fundamentals(Path(args.out), tickers)
    # Calendrier des résultats (prochaine publication + dates passées) : écran « Best try ».
    errors += download_events(Path(args.out), tickers)
    errors += download_all(args.out, args.start, args.end, args.daily_years, extra=extra)
    # Options (straddles à la monnaie) : mouvement anticipé par le marché autour des catalyseurs.
    spots = {}
    for t in tickers:
        path = Path(args.out) / "daily" / f"{t}.csv"
        if path.exists():
            last = path.read_text(encoding="utf-8").strip().splitlines()[-1].split(",")
            spots[t] = float(last[4])
    errors += download_options(Path(args.out), spots)
    for e in errors:
        print(f"  ✗ {e}", file=sys.stderr)
    files = list(Path(args.out).rglob("*.csv"))
    print(f"{len(files)} fichiers CSV dans {args.out}/ ({len(errors)} erreur(s)), période {args.start} → {args.end}")
    return 0 if files else 1


if __name__ == "__main__":
    sys.exit(main())
