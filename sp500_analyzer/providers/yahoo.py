"""Téléchargement de vrais cours depuis l'API publique de graphiques de Yahoo Finance.

- Intraday : barres de 5 minutes (Yahoo ne les conserve que ~60 jours), agrégées en barres
  de 10 minutes sur la séance régulière de New York (9h30-16h00, 39 barres par jour).
- Quotidien : historique ajusté des dividendes et divisions (Open/High/Low/Close multipliés
  par Adj Close / Close), au format lu par CsvPriceProvider.

API non officielle et sans clé : à réserver à un usage personnel de recherche, avec un
débit raisonnable (pause entre les requêtes, nouvelles tentatives espacées en cas de refus).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from ..universe import INDEX, SP500_SAMPLE

NEW_YORK = ZoneInfo("America/New_York")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
INDEX_FILE = "SPX"
SESSION_OPEN = (9, 30)
SESSION_CLOSE = (16, 0)


@dataclass(frozen=True)
class IntradayBar:
    start: datetime  # début de la barre, heure de New York
    open: float
    high: float
    low: float
    close: float
    volume: int


def yahoo_symbol(ticker: str) -> str:
    return "^GSPC" if ticker in (INDEX.ticker, INDEX_FILE) else ticker.replace(".", "-")


def _get_json(url: str, retries: int = 4, timeout: float = 30.0) -> dict:
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sp500-analyzer research)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            retryable = not isinstance(e, urllib.error.HTTPError) or e.code in (429, 500, 502, 503, 504)
            if attempt == retries or not retryable:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("inaccessible")  # pour les vérificateurs de types


def parse_chart(payload: dict) -> list[tuple[datetime, float, float, float, float, int, Optional[float]]]:
    """(horodatage UTC, open, high, low, close, volume, adjclose) ; lignes incomplètes ignorées."""
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(f"Yahoo : {chart['error'].get('description', chart['error'])}")
    result = (chart.get("result") or [None])[0]
    if not result or not result.get("timestamp"):
        return []
    q = result["indicators"]["quote"][0]
    adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    rows = []
    for i, ts in enumerate(result["timestamp"]):
        o, h, lo, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c):
            continue
        rows.append((datetime.fromtimestamp(ts, tz=timezone.utc), o, h, lo, c, int(v or 0),
                     adj[i] if adj else None))
    return rows


def resample_10min(rows) -> list[IntradayBar]:
    """Agrège des barres de 5 minutes en barres de 10 minutes alignées sur 9h30, 9h40…"""
    buckets: dict[datetime, list] = {}
    for ts, o, h, lo, c, v, _ in rows:
        local = ts.astimezone(NEW_YORK)
        open_dt = local.replace(hour=SESSION_OPEN[0], minute=SESSION_OPEN[1], second=0, microsecond=0)
        close_dt = local.replace(hour=SESSION_CLOSE[0], minute=SESSION_CLOSE[1], second=0, microsecond=0)
        if not (open_dt <= local < close_dt):
            continue  # hors séance régulière
        slot = open_dt + timedelta(minutes=10 * ((local - open_dt).seconds // 600))
        buckets.setdefault(slot, []).append((local, o, h, lo, c, v))
    bars = []
    for slot in sorted(buckets):
        parts = sorted(buckets[slot])
        bars.append(IntradayBar(slot, parts[0][1], max(p[2] for p in parts), min(p[3] for p in parts),
                                parts[-1][4], sum(p[5] for p in parts)))
    return bars


def fetch_intraday_10min(ticker: str, start: date, end: date) -> list[IntradayBar]:
    p1 = int(datetime.combine(start, datetime.min.time(), NEW_YORK).timestamp())
    p2 = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), NEW_YORK).timestamp())
    url = (CHART_URL.format(symbol=urllib.request.quote(yahoo_symbol(ticker)))
           + f"?period1={p1}&period2={p2}&interval=5m&includePrePost=false")
    return [b for b in resample_10min(parse_chart(_get_json(url))) if start <= b.start.date() <= end]


def fetch_daily_adjusted(ticker: str, years: int = 2):
    url = (CHART_URL.format(symbol=urllib.request.quote(yahoo_symbol(ticker)))
           + f"?range={years}y&interval=1d&events=div%2Csplit")
    out = []
    for ts, o, h, lo, c, v, adj in parse_chart(_get_json(url)):
        k = adj / c if adj and c else 1.0
        out.append((ts.astimezone(NEW_YORK).date(), o * k, h * k, lo * k, c * k, v))
    return out


def write_intraday_csv(path: Path, bars: list[IntradayBar]) -> None:
    lines = ["Datetime,Open,High,Low,Close,Volume"]
    lines += [f"{b.start.strftime('%Y-%m-%d %H:%M')},{b.open:.4f},{b.high:.4f},{b.low:.4f},{b.close:.4f},{b.volume}"
              for b in bars]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_daily_csv(path: Path, rows) -> None:
    lines = ["Date,Open,High,Low,Close,Volume"]
    lines += [f"{d.isoformat()},{o:.4f},{h:.4f},{lo:.4f},{c:.4f},{v}" for d, o, h, lo, c, v in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def download_all(out_dir: str | Path, start: date, end: date, daily_years: int = 2,
                 pause: float = 0.6, extra: tuple[str, ...] = ()) -> list[str]:
    """Télécharge intraday 10 min (start..end) et quotidien ajusté pour l'univers, le S&P 500
    et d'éventuels titres supplémentaires hors univers (`extra`, ex. ("IREN",))."""
    out = Path(out_dir)
    intraday_dir = out / "intraday_10min" / f"{start:%Y-%m}"
    daily_dir = out / "daily"
    intraday_dir.mkdir(parents=True, exist_ok=True)
    daily_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    tickers = [p.security.ticker for p in SP500_SAMPLE] + [INDEX_FILE]
    tickers += [t.upper() for t in extra if t.upper() not in tickers]
    for ticker in tickers:
        try:
            bars = fetch_intraday_10min(ticker, start, end)
            if not bars:
                errors.append(f"{ticker} : aucune barre intraday")
            else:
                write_intraday_csv(intraday_dir / f"{ticker}.csv", bars)
            time.sleep(pause)
            write_daily_csv(daily_dir / f"{ticker}.csv", fetch_daily_adjusted(ticker, daily_years))
            time.sleep(pause)
        except Exception as e:  # noqa: BLE001 — on continue avec les autres titres
            errors.append(f"{ticker} : {type(e).__name__}: {e}")
    return errors
