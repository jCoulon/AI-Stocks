"""Télécharge de vraies news (GDELT), dépôts SEC (EDGAR) et séries macro (FRED).

Usage : python scripts/fetch_news_macro.py [--start 2026-01-01] [--out data] [--extra IREN]
Lancé par le workflow GitHub Actions « News et macro réelles ». Les news GDELT ne remontent
qu'à ~3 mois : la date de début des news est ramenée automatiquement dans cette limite.
Variable d'environnement SEC_USER_AGENT : identité déclarée à la SEC (« Nom contact@domaine »),
exigée par ses règles d'accès.
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_analyzer.providers.realnews import (  # noqa: E402
    GDELT_MAX_DAYS, MARKET, download_macro, download_news, download_sec,
)
from sp500_analyzer.providers.googlenews import download_google_news  # noqa: E402
from sp500_analyzer.universe import SP500_SAMPLE  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # progression visible dans les logs du workflow
    today = datetime.now(ZoneInfo("America/New_York")).date()
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=today)
    p.add_argument("--out", default="data")
    p.add_argument("--extra", default="", help="Titres supplémentaires, séparés par des virgules (ex. IREN)")
    p.add_argument("--only", default="google,news,sec,macro",
                   help="Sources à télécharger (google = Google News, news = GDELT, sec, macro)")
    p.add_argument("--budget", type=float, default=60.0, help="News : durée maximale en minutes")
    args = p.parse_args()
    out = Path(args.out)
    tickers = [s.security.ticker for s in SP500_SAMPLE]
    tickers += [t.strip().upper() for t in args.extra.split(",") if t.strip() and t.strip().upper() not in tickers]
    only = {s.strip() for s in args.only.split(",")}
    errors = []
    if "macro" in only:
        print("Macro (FRED)…")
        errors += download_macro(out, args.start)
    if "sec" in only:
        print("Dépôts SEC (EDGAR)…")
        agent = os.environ.get("SEC_USER_AGENT") or "AI-Stocks research tool (github.com/jCoulon/AI-Stocks)"
        errors += download_sec(out, tickers, args.start, agent)
    if "google" in only:
        print(f"News financières (Google News) du {args.start} au {args.end}…")
        errors += download_google_news(out, tickers + [MARKET], args.start, args.end, budget_minutes=args.budget,
                                       today=today)
    if "news" in only:
        news_start = max(args.start, today - timedelta(days=GDELT_MAX_DAYS))
        print(f"News (GDELT) du {news_start} au {args.end}…")
        errors += download_news(out, tickers + [MARKET], news_start, args.end, budget_minutes=args.budget,
                                today=today)
    for e in errors:
        print(f"  ✗ {e}", file=sys.stderr)
    dirs = {"google": "news/google", "news": "news", "sec": "sec", "macro": "macro"}
    files = [f for d in only if d in dirs for f in (out / dirs[d]).glob("*.csv")] if out.exists() else []
    print(f"{len(files)} fichiers ({', '.join(sorted(only))}), {len(errors)} erreur(s).")
    return 0 if files else 1


if __name__ == "__main__":
    sys.exit(main())
