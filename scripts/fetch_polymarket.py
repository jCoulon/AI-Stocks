"""Polymarket : téléchargement des marchés résolus et de leurs ordres, analyse des portefeuilles,
puis suivi des derniers ordres des meilleurs portefeuilles.

  python scripts/fetch_polymarket.py [--out data] [--days 90] [--markets 250]   analyse complète
  python scripts/fetch_polymarket.py --monitor                                  suivi seul (rapide)
Résultat : data/polymarket/report.json (lu par l'application et par --polymarket).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_analyzer.analysis.polymarket import build_report, monitor_rows  # noqa: E402
from sp500_analyzer.providers.polymarket import (  # noqa: E402
    fetch_leaderboard, fetch_market_trades, fetch_markets_by_id, fetch_resolved_markets, fetch_wallet_trades, get_json,
)


def monitor(report: dict, log=print) -> None:
    wallets = {s["wallet"]: s for s in report.get("top", [])}
    recent = []
    for w in wallets:
        try:
            recent += fetch_wallet_trades(w, 100)
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ suivi {w[:10]} : {type(e).__name__}: {e}")
        time.sleep(0.3)
    now = datetime.now(timezone.utc)
    ids = sorted({t.condition_id for t in recent if now.timestamp() - t.ts < 7 * 86400})
    markets = fetch_markets_by_id(ids) if ids else {}
    report["monitor"] = monitor_rows(recent, markets, wallets, now)
    report["monitor_at"] = now.strftime("%Y-%m-%d %H:%M")
    log(f"Suivi : {len(report['monitor'])} ordre(s) récent(s) de {len(wallets)} portefeuille(s) sur des marchés ouverts")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--markets", type=int, default=250)
    p.add_argument("--min-volume", type=float, default=20_000)
    p.add_argument("--max-volume", type=float, default=3_000_000)
    p.add_argument("--pages", type=int, default=4, help="Pages de 500 ordres par marché")
    p.add_argument("--budget", type=float, default=35.0, help="Minutes maximum pour les ordres")
    p.add_argument("--monitor", action="store_true", help="Suivi seul, à partir du rapport existant")
    args = p.parse_args()
    folder = Path(args.out) / "polymarket"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "report.json"

    if args.monitor:
        if not path.exists():
            print("Pas de rapport : lancez d'abord l'analyse complète.")
            return 1
        report = json.loads(path.read_text())
        monitor(report)
        path.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        return 0

    now = datetime.now(timezone.utc)
    markets = fetch_resolved_markets(now - timedelta(days=args.days), now, args.min_volume, args.max_volume,
                                     args.markets)
    print(f"{len(markets)} marchés résolus retenus")
    if not markets:
        return 1
    # Échantillon brut, pour vérifier les champs de l'API.
    first = get_json(f"https://data-api.polymarket.com/trades?market={markets[0].condition_id}&limit=2")
    (folder / "_echantillon.json").write_text(json.dumps({"market": markets[0].__dict__ | {"end": str(markets[0].end)},
                                                         "trades": first}, indent=1, default=str, ensure_ascii=False))
    trades, t0 = [], time.monotonic()
    for i, m in enumerate(markets, 1):
        if time.monotonic() - t0 > args.budget * 60:
            print(f"Budget atteint : {i - 1} marchés sur {len(markets)}")
            markets = markets[:i - 1]
            break
        try:
            got = fetch_market_trades(m.condition_id, args.pages)
            trades += got
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ ordres {m.question[:50]} : {type(e).__name__}: {e}")
            continue
        if i % 10 == 0:
            print(f"  {i}/{len(markets)} marchés, {len(trades)} ordres")
        time.sleep(0.2)
    report = build_report({m.condition_id: m for m in markets}, trades, now)
    try:
        report["leaderboard"] = fetch_leaderboard("MONTH", 50)
    except Exception as e:  # noqa: BLE001
        report["leaderboard"] = []
        print(f"  ✗ classement public : {e}")
    monitor(report)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    p_ = report["persistence"]
    print(f"Rapport : {report['markets']} marchés, {report['orders']} ordres, {report['wallets']} portefeuilles ; "
          f"persistance {p_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
