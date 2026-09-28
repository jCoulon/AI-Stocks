"""Données fondamentales du jour (Yahoo Finance, module quoteSummary) : objectifs de cours des
analystes, croissance, marges, valorisation, trésorerie, vente à découvert.

Ce sont des **photographies à la date du téléchargement**, pas un historique point-in-time :
elles servent à décrire un titre (écran d'asymétrie), jamais au backtest.
Fichiers : <dossier>/fundamentals/<TICKER>.json.
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from .yahoo import yahoo_symbol

QUOTE_SUMMARY = ("https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
                 "?modules=price,financialData,defaultKeyStatistics,summaryDetail&crumb={crumb}")
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                         "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"}

# Champ retenu -> (module, clé Yahoo)
FIELDS: dict[str, tuple[str, str]] = {
    "market_cap": ("price", "marketCap"),
    "price": ("financialData", "currentPrice"),
    "target_mean": ("financialData", "targetMeanPrice"),
    "target_high": ("financialData", "targetHighPrice"),
    "target_low": ("financialData", "targetLowPrice"),
    "analysts": ("financialData", "numberOfAnalystOpinions"),
    "recommendation": ("financialData", "recommendationMean"),  # 1 = achat fort ... 5 = vente
    "revenue": ("financialData", "totalRevenue"),
    "revenue_growth": ("financialData", "revenueGrowth"),  # glissement annuel du dernier trimestre
    "gross_margin": ("financialData", "grossMargins"),
    "operating_margin": ("financialData", "operatingMargins"),
    "free_cash_flow": ("financialData", "freeCashflow"),
    "cash": ("financialData", "totalCash"),
    "debt": ("financialData", "totalDebt"),
    "ev_to_revenue": ("defaultKeyStatistics", "enterpriseToRevenue"),
    "short_float": ("defaultKeyStatistics", "shortPercentOfFloat"),
    "forward_pe": ("summaryDetail", "forwardPE"),
    "high_52w": ("summaryDetail", "fiftyTwoWeekHigh"),
    "low_52w": ("summaryDetail", "fiftyTwoWeekLow"),
}


def extract(payload: dict) -> dict[str, Optional[float]]:
    """Champs utiles d'une réponse quoteSummary (valeurs brutes, None si absentes)."""
    result = ((payload.get("quoteSummary") or {}).get("result") or [None])[0]
    if not result:
        err = (payload.get("quoteSummary") or {}).get("error") or payload.get("finance", {}).get("error")
        raise ValueError(f"Yahoo quoteSummary : {err}")
    out: dict[str, Optional[float]] = {}
    for name, (module, key) in FIELDS.items():
        v = (result.get(module) or {}).get(key)
        if isinstance(v, dict):
            v = v.get("raw")
        out[name] = float(v) if isinstance(v, (int, float)) else None
    return out


def yahoo_opener(attempts: int = 4, wait: float = 20.0, sleep=time.sleep) -> tuple[Callable[[str], str], str]:
    """Session Yahoo (cookie + « crumb » exigés par quoteSummary depuis 2023), avec nouvelles
    tentatives espacées : Yahoo répond souvent 429 aux serveurs partagés."""
    last: Exception = RuntimeError("inaccessible")
    for i in range(attempts):
        try:
            return _yahoo_session()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts - 1:
                sleep(wait * 2 ** i)
    raise last


def _yahoo_session() -> tuple[Callable[[str], str], str]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = list(HEADERS.items())

    def get(url: str) -> str:
        with opener.open(url, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    try:
        get(COOKIE_URL)  # répond souvent 404, mais dépose le cookie
    except Exception:  # noqa: BLE001
        pass
    crumb = get(CRUMB_URL).strip()
    if not crumb or "<" in crumb:
        raise ValueError("Yahoo : jeton (crumb) introuvable")
    return get, crumb


def download_fundamentals(out_dir: Path, tickers: list[str], pause: float = 0.8, log=print,
                          session=None, today: Optional[date] = None) -> list[str]:
    folder = out_dir / "fundamentals"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        get, crumb = session or yahoo_opener()
    except Exception as e:  # noqa: BLE001
        return [f"Fondamentaux : session Yahoo impossible ({type(e).__name__}: {e})"]
    errors = []
    for ticker in tickers:
        url = QUOTE_SUMMARY.format(symbol=urllib.parse.quote(yahoo_symbol(ticker)), crumb=urllib.parse.quote(crumb))
        try:
            data = extract(json.loads(get(url)))
        except Exception as e:  # noqa: BLE001
            errors.append(f"Fondamentaux {ticker} : {type(e).__name__}: {str(e)[:120]}")
            continue
        data_out = {"ticker": ticker, "fetched": (today or date.today()).isoformat(), **data}
        (folder / f"{ticker}.json").write_text(json.dumps(data_out, indent=1), encoding="utf-8")
        log(f"  fondamentaux {ticker:6} objectif moyen {data['target_mean']}, croissance {data['revenue_growth']}")
        time.sleep(pause)
    return errors


def load_fundamentals(root: Path, ticker: str) -> Optional[dict]:
    path = root / "fundamentals" / f"{ticker}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
