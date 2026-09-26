"""Télécharge de vrais cours (Yahoo Finance) : intraday 10 min sur une période + quotidien ajusté.

Usage : python scripts/fetch_market_data.py --start 2026-09-01 [--end 2026-09-25] [--out data]
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


def main() -> int:
    today_ny = datetime.now(ZoneInfo("America/New_York")).date()
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 1))
    p.add_argument("--end", type=date.fromisoformat, default=today_ny)
    p.add_argument("--out", default="data")
    p.add_argument("--daily-years", type=int, default=2)
    args = p.parse_args()
    errors = download_all(args.out, args.start, args.end, args.daily_years)
    for e in errors:
        print(f"  ✗ {e}", file=sys.stderr)
    files = list(Path(args.out).rglob("*.csv"))
    print(f"{len(files)} fichiers CSV dans {args.out}/ ({len(errors)} erreur(s)), période {args.start} → {args.end}")
    return 0 if files else 1


if __name__ == "__main__":
    sys.exit(main())
