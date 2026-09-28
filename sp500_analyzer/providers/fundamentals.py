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


# ------------------------------------------------ source de secours : API publique Nasdaq
NASDAQ_API = "https://api.nasdaq.com/api"
NASDAQ_HEADERS = {**HEADERS, "Accept": "application/json, text/plain, */*",
                  "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


def _num(v) -> Optional[float]:
    """« $46,743,000 », « (1,234) », « 12.5% », « -- » -> nombre (None si absent)."""
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    t = v.strip().replace("$", "").replace(",", "").replace("%", "")
    neg = t.startswith("(") and t.endswith(")")
    try:
        x = float(t.strip("()"))
    except ValueError:
        return None
    return -x if neg else x


def _row(table: dict, *labels: str) -> list[Optional[float]]:
    """Valeurs (en dollars) d'une ligne d'un tableau financier Nasdaq, exprimé en milliers."""
    for r in (table or {}).get("rows") or []:
        if (r.get("value1") or "").strip().lower() in {l.lower() for l in labels}:
            keys = sorted((k for k in r if k != "value1"), key=lambda k: int(k[5:]))
            return [None if (x := _num(r[k])) is None else x * 1000 for k in keys]
    return []


def nasdaq_fundamentals(ticker: str, get: Callable[[str], str]) -> dict[str, Optional[float]]:
    """Mêmes champs que extract(), depuis l'API publique de nasdaq.com (sans clé)."""
    sym = urllib.parse.quote(ticker.lower())
    out: dict[str, Optional[float]] = {k: None for k in FIELDS}
    target = (json.loads(get(f"{NASDAQ_API}/analyst/{sym}/targetprice")).get("data") or {}).get("consensusOverview") or {}
    out.update(target_mean=_num(target.get("priceTarget")), target_high=_num(target.get("highPriceTarget")),
               target_low=_num(target.get("lowPriceTarget")))
    votes = [_num(target.get(k)) for k in ("buy", "hold", "sell")]
    out["analysts"] = sum(v for v in votes if v) or None
    summary = (json.loads(get(f"{NASDAQ_API}/quote/{sym}/summary?assetclass=stocks")).get("data") or {})
    out["market_cap"] = _num(((summary.get("summaryData") or {}).get("MarketCap") or {}).get("value"))
    quarterly = json.loads(get(f"{NASDAQ_API}/company/{sym}/financials?frequency=2")).get("data") or {}
    annual = json.loads(get(f"{NASDAQ_API}/company/{sym}/financials?frequency=1")).get("data") or {}
    rev_q = [x for x in _row(quarterly.get("incomeStatementTable"), "Total Revenue") if x is not None]
    rev_y = [x for x in _row(annual.get("incomeStatementTable"), "Total Revenue") if x is not None]
    if len(rev_q) == 4:
        out["revenue"] = sum(rev_q)  # 4 derniers trimestres
    if len(rev_y) >= 2 and rev_y[1]:
        out["revenue_growth"] = rev_y[0] / rev_y[1] - 1  # dernier exercice sur un an
    bs = quarterly.get("balanceSheetTable")
    cash = [(_row(bs, "Cash and Cash Equivalents") or [None])[0], (_row(bs, "Short-Term Investments") or [None])[0]]
    debt = [(_row(bs, "Long-Term Debt") or [None])[0],
            (_row(bs, "Short-Term Debt / Current Portion of Long-Term Debt") or [None])[0]]
    out["cash"] = sum(x for x in cash if x) if any(cash) else None
    out["debt"] = sum(x for x in debt if x) if any(debt) else None
    cf = quarterly.get("cashFlowTable")
    ocf, capex = _row(cf, "Net Cash Flow-Operating"), _row(cf, "Capital Expenditures")
    if len(ocf) == 4 and len(capex) == 4 and None not in ocf + capex:
        out["free_cash_flow"] = sum(ocf) + sum(capex)  # dépenses d'investissement négatives
    if out["market_cap"] and out["revenue"]:
        ev = out["market_cap"] + (out["debt"] or 0) - (out["cash"] or 0)
        out["ev_to_revenue"] = ev / out["revenue"]
    return out


def download_fundamentals(out_dir: Path, tickers: list[str], pause: float = 0.8, log=print,
                          session=None, today: Optional[date] = None, nasdaq_get=None) -> list[str]:
    """Fondamentaux depuis Yahoo, ou depuis Nasdaq si Yahoo refuse la session (fréquent sur
    les serveurs partagés comme ceux de GitHub)."""
    folder = out_dir / "fundamentals"
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        get, crumb = session or yahoo_opener()
        source = "Yahoo Finance"
    except Exception as e:  # noqa: BLE001
        errors.append(f"Fondamentaux : session Yahoo impossible ({type(e).__name__}: {e}) — secours Nasdaq")
        get, crumb, source = None, "", "Nasdaq"
    if get is None:
        if nasdaq_get is None:
            opener = urllib.request.build_opener()
            opener.addheaders = list(NASDAQ_HEADERS.items())
            nasdaq_get = lambda url: opener.open(url, timeout=30).read().decode("utf-8", "replace")  # noqa: E731
    failures = 0
    for ticker in tickers:
        try:
            if source == "Nasdaq":
                data = nasdaq_fundamentals(ticker, nasdaq_get)
            else:
                url = QUOTE_SUMMARY.format(symbol=urllib.parse.quote(yahoo_symbol(ticker)),
                                           crumb=urllib.parse.quote(crumb))
                data = extract(json.loads(get(url)))
        except Exception as e:  # noqa: BLE001
            errors.append(f"Fondamentaux {ticker} ({source}) : {type(e).__name__}: {str(e)[:120]}")
            failures += 1
            if failures == 3 and failures == len(errors) - (source == "Nasdaq"):
                errors.append(f"Fondamentaux : {source} refuse les requêtes — arrêt")
                return errors
            continue
        data_out = {"ticker": ticker, "fetched": (today or date.today()).isoformat(), "source": source, **data}
        (folder / f"{ticker}.json").write_text(json.dumps(data_out, indent=1), encoding="utf-8")
        log(f"  fondamentaux {ticker:6} ({source}) objectif moyen {data['target_mean']}, "
            f"croissance {data['revenue_growth']}, VE/CA {data['ev_to_revenue']}")
        time.sleep(pause)
    return errors


def load_fundamentals(root: Path, ticker: str) -> Optional[dict]:
    path = root / "fundamentals" / f"{ticker}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
