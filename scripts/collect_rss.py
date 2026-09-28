"""Collecte les flux RSS de news (Yahoo Finance, Nasdaq) dans data/news/rss/ et les messages
StockTwits dans data/social/stocktwits/.

Usage : python scripts/collect_rss.py [--out data] [--extra IREN]
Lancé plusieurs fois par jour par le workflow « News RSS et FinBERT » : les flux ne gardent que
les derniers titres, la collecte répétée construit l'historique.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_analyzer.providers.realnews import MARKET  # noqa: E402
from sp500_analyzer.providers.rss import collect_rss  # noqa: E402
from sp500_analyzer.providers.reddit import collect_reddit  # noqa: E402
from sp500_analyzer.providers.stocktwits import collect_stocktwits  # noqa: E402
from sp500_analyzer.universe import SP500_SAMPLE  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data")
    p.add_argument("--extra", default="", help="Titres supplémentaires, séparés par des virgules (ex. IREN)")
    p.add_argument("--only", default="rss,stocktwits,reddit", help="Sources : rss, stocktwits, reddit")
    args = p.parse_args()
    tickers = [s.security.ticker for s in SP500_SAMPLE]
    tickers += [t.strip().upper() for t in args.extra.split(",") if t.strip() and t.strip().upper() not in tickers]
    only = {s.strip() for s in args.only.split(",")}
    failed_all = True
    if "rss" in only:
        errors = collect_rss(Path(args.out), tickers + [MARKET])
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print(f"RSS : {len(tickers) + 1} titres collectés, {len(errors)} flux en échec.")
        failed_all &= len(errors) >= 2 * (len(tickers) + 1)
    if "stocktwits" in only:
        errors = collect_stocktwits(Path(args.out), tickers)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print(f"StockTwits : {len(tickers)} titres, {len(errors)} en échec.")
        failed_all &= len(errors) >= len(tickers)
    if "reddit" in only:
        errors = collect_reddit(Path(args.out), tickers)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print(f"Reddit : {len(tickers)} titres, {len(errors)} erreur(s).")
        failed_all &= len(errors) >= 2
    return 1 if failed_all else 0  # échec seulement si toutes les sources ont échoué


if __name__ == "__main__":
    sys.exit(main())
