"""Chaînes d'options (API publique Nasdaq, secours Yahoo) : prix du « straddle » à la monnaie
(call + put au prix d'exercice le plus proche du cours) pour chaque échéance proche.

Le straddle mesure le mouvement que le marché des options anticipe d'ici l'échéance, dans un sens
ou dans l'autre : mouvement absolu attendu ≈ prix du straddle / cours. C'est une photographie du
jour ; l'historique (data/options/history.csv) se construit à chaque collecte.

Fichiers : <dossier>/options/<TICKER>.json (dernier relevé) et <dossier>/options/history.csv.
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .fundamentals import NASDAQ_API, NASDAQ_HEADERS, _num

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], 1)}
HORIZON_DAYS = 75
HISTORY_FIELDS = ["Fetched", "Ticker", "Spot", "Expiry", "Strike", "Straddle", "Source"]


def _parse_group_date(text: str, today: date) -> Optional[date]:
    """« October 2, 2026 », « Oct 2 » (année déduite) ou « 2026-10-02 »."""
    t = (text or "").strip()
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", t):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?", t):
        month = MONTHS.get(m[1].lower())
        if not month:
            return None
        year = int(m[3]) if m[3] else today.year
        d = date(year, month, int(m[2]))
        if not m[3] and d < today - timedelta(days=7):
            d = date(year + 1, month, int(m[2]))
        return d
    return None


def _price(bid, ask, last) -> Optional[float]:
    b, a, lt = _num(bid), _num(ask), _num(last)
    if b and a and a >= b > 0:
        return (a + b) / 2
    return lt if lt and lt > 0 else None


def parse_nasdaq_chain(payload: dict, today: date) -> list[dict]:
    """Lignes (échéance, prix d'exercice, prix call, prix put) de /quote/<sym>/option-chain.
    Les lignes d'en-tête de groupe (« expirygroup ») donnent la date d'échéance des suivantes."""
    rows = (((payload.get("data") or {}).get("table") or {}).get("rows")) or []
    out, group = [], None
    for r in rows:
        if r.get("expirygroup"):
            group = _parse_group_date(r["expirygroup"], today) or group
        strike = _num(r.get("strike"))
        if strike is None:
            continue
        expiry = _parse_group_date(r.get("expiryDate") or "", today) or group
        call = _price(r.get("c_Bid"), r.get("c_Ask"), r.get("c_Last"))
        put = _price(r.get("p_Bid"), r.get("p_Ask"), r.get("p_Last"))
        if expiry and call and put:
            out.append({"expiry": expiry, "strike": strike, "call": call, "put": put})
    return out


def parse_yahoo_chain(payload: dict) -> tuple[Optional[float], list[dict]]:
    res = (((payload.get("optionChain") or {}).get("result")) or [None])[0] or {}
    spot = (res.get("quote") or {}).get("regularMarketPrice")
    out = []
    for block in res.get("options") or []:
        expiry = datetime.utcfromtimestamp(block["expirationDate"]).date() if block.get("expirationDate") else None
        puts = {p.get("strike"): p for p in block.get("puts") or []}
        for c in block.get("calls") or []:
            p = puts.get(c.get("strike"))
            if not p or expiry is None:
                continue
            call = _price(c.get("bid"), c.get("ask"), c.get("lastPrice"))
            put = _price(p.get("bid"), p.get("ask"), p.get("lastPrice"))
            if call and put:
                out.append({"expiry": expiry, "strike": float(c["strike"]), "call": call, "put": put})
    return spot, out


def atm_straddles(rows: list[dict], spot: float) -> list[dict]:
    """Pour chaque échéance : straddle au prix d'exercice le plus proche du cours."""
    by_exp: dict[date, list[dict]] = {}
    for r in rows:
        by_exp.setdefault(r["expiry"], []).append(r)
    out = []
    for exp in sorted(by_exp):
        best = min(by_exp[exp], key=lambda r: abs(r["strike"] - spot))
        if abs(best["strike"] / spot - 1) > 0.1:  # aucun prix d'exercice proche du cours
            continue
        out.append({"expiry": exp.isoformat(), "strike": best["strike"], "straddle": best["call"] + best["put"],
                    "move": (best["call"] + best["put"]) / spot})
    return out


def nasdaq_url(ticker: str, today: date) -> str:
    q = urllib.parse.urlencode({"assetclass": "stocks", "limit": 1000, "fromdate": today.isoformat(),
                                "todate": (today + timedelta(days=HORIZON_DAYS)).isoformat(),
                                "excode": "oprac", "callput": "callput", "money": "at", "type": "all"})
    return f"{NASDAQ_API}/quote/{urllib.parse.quote(ticker)}/option-chain?{q}"


def download_options(out_dir: Path, spots: dict[str, float], today: Optional[date] = None, pause: float = 0.6,
                     log=print, get=None) -> list[str]:
    """Relevé des straddles à la monnaie des échéances des 75 prochains jours."""
    today = today or date.today()
    folder = out_dir / "options"
    folder.mkdir(parents=True, exist_ok=True)
    if get is None:
        opener = urllib.request.build_opener()
        opener.addheaders = list(NASDAQ_HEADERS.items())
        get = lambda url: opener.open(url, timeout=30).read().decode("utf-8", "replace")  # noqa: E731
    hist_path = folder / "history.csv"
    history = []
    if hist_path.exists():
        with open(hist_path, newline="", encoding="utf-8") as f:
            history = [r for r in csv.DictReader(f) if r["Fetched"] != today.isoformat() or r["Ticker"] not in spots]
    errors, failures = [], 0
    for i, (ticker, spot) in enumerate(spots.items()):
        try:
            raw = get(nasdaq_url(ticker, today))
            if i == 0:  # échantillon brut, pour vérifier le format de l'API
                (folder / "_echantillon.json").write_text(raw[:30000], encoding="utf-8")
            rows = parse_nasdaq_chain(json.loads(raw), today)
            straddles = atm_straddles(rows, spot)
            if not straddles:
                raise ValueError(f"aucun straddle exploitable ({len(rows)} lignes)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"Options {ticker} (Nasdaq) : {type(e).__name__}: {str(e)[:120]}")
            failures += 1
            if failures == 5 and failures == len(errors):
                errors.append("Options : Nasdaq ne renvoie rien d'exploitable — arrêt")
                return errors
            continue
        snap = {"ticker": ticker, "fetched": today.isoformat(), "source": "Nasdaq", "spot": spot, "straddles": straddles}
        (folder / f"{ticker}.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
        history += [{"Fetched": today.isoformat(), "Ticker": ticker, "Spot": f"{spot:.4f}", "Expiry": s["expiry"],
                     "Strike": f"{s['strike']:.2f}", "Straddle": f"{s['straddle']:.4f}", "Source": "Nasdaq"}
                    for s in straddles]
        log(f"  options {ticker:6} {len(straddles)} échéance(s), 1re {straddles[0]['expiry']} ±{straddles[0]['move']:.1%}")
        time.sleep(pause)
    with open(hist_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        w.writeheader()
        w.writerows(sorted(history, key=lambda r: (r["Fetched"], r["Ticker"], r["Expiry"])))
    return errors


def load_options(root: Path, ticker: str) -> Optional[dict]:
    path = root / "options" / f"{ticker}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def implied_event_move(snap: dict, event_day: date, as_of: date, hist_daily_vol: Optional[float]) -> Optional[dict]:
    """Mouvement attendu par les options pour l'événement seul.

    Straddle de la 1re échéance après l'événement ≈ mouvement absolu attendu jusqu'à l'échéance
    (E|X| = σ·√(2/π) pour une loi normale). On en retire la variance des séances ordinaires
    (volatilité implicite de l'échéance précédant l'événement, sinon historique) pour isoler la
    part de l'événement, ramenée en mouvement absolu attendu."""
    k = (2 / 3.141592653589793) ** 0.5
    rows = sorted(snap.get("straddles") or [], key=lambda s: s["expiry"])
    after = next((s for s in rows if date.fromisoformat(s["expiry"]) >= event_day), None)
    if after is None:
        return None
    exp = date.fromisoformat(after["expiry"])
    n = max(1, _trading_days(as_of, exp))
    before = [s for s in rows if date.fromisoformat(s["expiry"]) < event_day and date.fromisoformat(s["expiry"]) > as_of]
    daily = None
    if before:
        b = before[-1]
        nb = max(1, _trading_days(as_of, date.fromisoformat(b["expiry"])))
        daily = (b["move"] / k) / nb ** 0.5
    elif hist_daily_vol:
        daily = hist_daily_vol
    total_var = (after["move"] / k) ** 2
    event_var = total_var - (n - 1) * (daily or 0) ** 2
    # Variance de l'événement nulle ou négative : cotations incohérentes entre échéances (souvent des
    # derniers cours périmés hors séance) -> non exploitable plutôt qu'un « 0 % » trompeur.
    return {"expiry": after["expiry"], "total_move": after["move"], "days": n,
            "event_move": k * event_var ** 0.5 if event_var > 0 else None,
            "daily_source": "implicite" if before else "historique", "fetched": snap.get("fetched")}


def _trading_days(a: date, b: date) -> int:
    """Séances entre a (exclu) et b (inclus), week-ends exclus (jours fériés ignorés)."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n
