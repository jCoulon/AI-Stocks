"""Données de recherche (test de nouveaux signaux sur les titres IA), historiques et gratuites :

  data/research/daily/<T>.csv     cours quotidiens ajustés sur 5 ans (Yahoo), + BTC-USD, SMH, QQQ
  data/research/shortvol/<T>.csv  volume vendu à découvert par séance (FINRA Reg SHO, marchés NMS)
  data/research/wiki/<T>.csv      consultations quotidiennes de la page Wikipédia (anglais) de la société
  data/research/wiki/articles.csv page Wikipédia retenue pour chaque titre (à vérifier)

Usage : python scripts/fetch_research_data.py [--out data] [--start 2023-01-01] [--only daily,short,wiki]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_analyzer.providers.yahoo import fetch_daily_adjusted, write_daily_csv  # noqa: E402
from sp500_analyzer.universe import AI_EXTRA, SP500_SAMPLE  # noqa: E402

UA = {"User-Agent": "sp500-analyzer-research/1.0 (github.com/jCoulon/AI-Stocks)"}
FINRA = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day:%Y%m%d}.txt"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch={q}"
WIKI_VIEWS = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
              "{article}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00")
MARKET_EXTRA = ["BTC-USD", "SMH", "QQQ"]
# Pages dont la recherche automatique risque de se tromper.
WIKI_OVERRIDES = {"AI": "C3.ai", "V": "Visa Inc.", "META": "Meta Platforms", "GOOGL": "Google", "IREN": "IREN Limited",
                  "CBRS": "Cerebras", "NBIS": "Nebius Group", "CRWV": "CoreWeave", "PATH": "UiPath",
                  "BBAI": "BigBear.ai", "SOUN": "SoundHound", "CORZ": "Core Scientific", "WULF": "TeraWulf",
                  "CIFR": "Cipher Mining", "APLD": "Applied Digital Corporation", "ARM": "Arm Holdings",
                  "TSM": "TSMC", "MU": "Micron Technology", "SMCI": "Supermicro", "VRT": "Vertiv",
                  "ANET": "Arista Networks", "PLTR": "Palantir Technologies"}


def get(url: str, timeout: float = 30.0, retries: int = 3) -> bytes:
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404) or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(2 * 2 ** attempt)
    raise RuntimeError("inaccessible")


def tickers() -> list[tuple[str, str]]:
    return [(p.security.ticker, p.security.name) for p in SP500_SAMPLE] + [(s.ticker, s.name) for s in AI_EXTRA]


def fetch_daily(out: Path) -> None:
    folder = out / "research" / "daily"
    folder.mkdir(parents=True, exist_ok=True)
    for t in [t for t, _ in tickers()] + MARKET_EXTRA + ["SPX"]:
        try:
            rows = fetch_daily_adjusted(t, years=5)
            write_daily_csv(folder / f"{t}.csv", rows)
            print(f"  cours 5 ans {t:8} {len(rows)} séances")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ cours {t} : {type(e).__name__}: {e}")
        time.sleep(0.5)


def fetch_short_volume(out: Path, start: date, end: date, budget_minutes: float) -> None:
    """Un fichier FINRA par séance (tous les titres) : on ne garde que ceux de l'univers.
    Les séances déjà téléchargées sont conservées (reprise possible)."""
    folder = out / "research" / "shortvol"
    folder.mkdir(parents=True, exist_ok=True)
    wanted = {t.replace(".", "") for t, _ in tickers()}
    done_path = folder / "_jours.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    rows: dict[str, dict[str, str]] = {}
    for t in wanted:
        p = folder / f"{t}.csv"
        if p.exists():
            with open(p, newline="") as f:
                rows[t] = {r["Date"]: ",".join([r["Date"], r["ShortVolume"], r["ShortExemptVolume"], r["TotalVolume"]])
                           for r in csv.DictReader(f)}
        else:
            rows[t] = {}
    t0, day, n = time.monotonic(), start, 0
    while day <= end and time.monotonic() - t0 < budget_minutes * 60:
        if day.weekday() < 5 and day.isoformat() not in done:
            try:
                body = get(FINRA.format(day=day), timeout=60).decode("utf-8", "replace")
                for line in body.splitlines()[1:]:
                    parts = line.split("|")
                    if len(parts) >= 5 and parts[1] in wanted:
                        d = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}"
                        rows[parts[1]][d] = ",".join([d, parts[2], parts[3], parts[4]])
                done.add(day.isoformat())
                n += 1
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    done.add(day.isoformat())  # jour férié : pas de fichier
                else:
                    print(f"  ✗ FINRA {day} : {e}")
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ FINRA {day} : {type(e).__name__}: {e}")
            if n and n % 50 == 0:
                print(f"  FINRA : {n} séances, jusqu'au {day}")
        day += timedelta(days=1)
    for t, by_day in rows.items():
        (folder / f"{t}.csv").write_text("Date,ShortVolume,ShortExemptVolume,TotalVolume\n"
                                         + "".join(by_day[d] + "\n" for d in sorted(by_day)))
    done_path.write_text("\n".join(sorted(done)) + "\n")
    print(f"FINRA : {n} nouvelle(s) séance(s), {len(done)} au total ; dernière date traitée {day - timedelta(days=1)}")


def fetch_wiki(out: Path, start: date, end: date) -> None:
    folder = out / "research" / "wiki"
    folder.mkdir(parents=True, exist_ok=True)
    mapping = []
    for t, name in tickers():
        query = WIKI_OVERRIDES.get(t, name)
        try:
            hits = json.loads(get(WIKI_SEARCH.format(q=urllib.parse.quote(query))))["query"]["search"]
            article = hits[0]["title"] if hits else None
            if not article:
                raise ValueError("aucune page")
            data = json.loads(get(WIKI_VIEWS.format(article=urllib.parse.quote(article.replace(" ", "_"), safe=""),
                                                     start=start, end=end)))
            lines = [f"{it['timestamp'][:4]}-{it['timestamp'][4:6]}-{it['timestamp'][6:8]},{it['views']}"
                     for it in data.get("items", [])]
            (folder / f"{t}.csv").write_text("Date,Views\n" + "\n".join(lines) + "\n")
            mapping.append(f"{t},{article}")
            print(f"  Wikipédia {t:6} « {article} » : {len(lines)} jours")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ Wikipédia {t} ({query}) : {type(e).__name__}: {e}")
        time.sleep(0.3)
    (folder / "articles.csv").write_text("Ticker,Article\n" + "\n".join(mapping) + "\n")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data")
    p.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--only", default="daily,short,wiki")
    p.add_argument("--budget", type=float, default=40.0, help="Minutes maximum pour FINRA")
    args = p.parse_args()
    out, only = Path(args.out), set(args.only.split(","))
    if "daily" in only:
        fetch_daily(out)
    if "wiki" in only:
        fetch_wiki(out, args.start, args.end)
    if "short" in only:
        fetch_short_volume(out, args.start, args.end, args.budget)
    return 0


if __name__ == "__main__":
    sys.exit(main())
