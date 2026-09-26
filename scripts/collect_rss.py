"""Collecte les flux RSS de news par action (Yahoo Finance, Nasdaq) dans data/news/rss/.

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
from sp500_analyzer.universe import SP500_SAMPLE  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data")
    p.add_argument("--extra", default="", help="Titres supplémentaires, séparés par des virgules (ex. IREN)")
    args = p.parse_args()
    tickers = [s.security.ticker for s in SP500_SAMPLE]
    tickers += [t.strip().upper() for t in args.extra.split(",") if t.strip() and t.strip().upper() not in tickers]
    errors = collect_rss(Path(args.out), tickers + [MARKET])
    for e in errors:
        print(f"  ✗ {e}", file=sys.stderr)
    print(f"RSS : {len(tickers) + 1} titres collectés, {len(errors)} flux en échec.")
    return 0 if len(errors) < 2 * (len(tickers) + 1) else 1  # échec seulement si tous les flux échouent


if __name__ == "__main__":
    sys.exit(main())
