"""Derniers cours de symboles quelconques (Yahoo Finance, symboles exacts : .TO, .V, .DE, OTC...).

Usage : python scripts/fetch_quotes.py --symbols SXGC.TO,NBIS,AIXA.DE [--out data/quotes/latest.csv]
Cours non ajustés (comparables à un prix de recommandation), avec la date et la devise de cotation.
"""

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=10d&interval=1d"
UA = {"User-Agent": "Mozilla/5.0 (sp500-analyzer research)"}


def quote(symbol: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(URL.format(s=urllib.parse.quote(symbol)), headers=UA),
                                timeout=30) as r:
        res = json.loads(r.read().decode("utf-8"))["chart"]["result"][0]
    meta = res["meta"]
    closes = res["indicators"]["quote"][0]["close"]
    days = [datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in res["timestamp"]]
    hist = [(d, c) for d, c in zip(days, closes) if c is not None]
    return {"Symbol": symbol, "Price": meta.get("regularMarketPrice"),
            "MarketTime": datetime.fromtimestamp(meta.get("regularMarketTime", 0), timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "Currency": meta.get("currency", ""), "LastClose": hist[-1][1] if hist else None,
            "LastCloseDate": hist[-1][0] if hist else "", "PrevClose": hist[-2][1] if len(hist) > 1 else None,
            "PrevCloseDate": hist[-2][0] if len(hist) > 1 else ""}


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True)
    p.add_argument("--out", default="data/quotes/latest.csv")
    args = p.parse_args()
    rows, errors = [], []
    for s in dict.fromkeys(x.strip() for x in args.symbols.split(",") if x.strip()):
        for attempt in range(3):
            try:
                rows.append(quote(s))
                print(f"  {s:10} {rows[-1]['Price']} {rows[-1]['Currency']} ({rows[-1]['MarketTime']} UTC)")
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    errors.append(f"{s}: {type(e).__name__}: {e}")
                    print(f"  ✗ {s} : {e}")
                time.sleep(2 * (attempt + 1))
        time.sleep(0.4)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Symbol", "Price", "MarketTime", "Currency", "LastClose", "LastCloseDate",
                                          "PrevClose", "PrevCloseDate"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} cours, {len(errors)} erreur(s) -> {out}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
