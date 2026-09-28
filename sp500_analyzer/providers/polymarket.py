"""Données publiques de Polymarket (sans clé) : marchés résolus (Gamma API), ordres passés sur ces
marchés et dernières transactions de portefeuilles suivis (Data API).

  gamma-api.polymarket.com/markets   marchés : question, date de fin, issues, prix finaux (1 / 0)
  data-api.polymarket.com/trades     ordres : portefeuille (proxyWallet), côté, issue, prix, taille,
                                     horodatage ; par marché (market=) ou par portefeuille (user=)
  data-api.polymarket.com/v1/leaderboard  classement public par gains (facultatif)

Les portefeuilles sont des adresses publiques pseudonymes : l'outil les analyse comme telles et ne
cherche pas à identifier leurs propriétaires.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (sp500-analyzer research; public data)", "Accept": "application/json"}


@dataclass(frozen=True)
class Market:
    condition_id: str
    question: str
    slug: str
    end: Optional[datetime]
    outcomes: tuple[str, ...]
    winner: Optional[int]        # index de l'issue gagnante (None : non résolu ou annulé)
    volume: float
    category: str
    prices: tuple[float, ...] = ()  # derniers prix (marché ouvert) ou prix finaux


@dataclass(frozen=True)
class Trade:
    ts: int                      # horodatage Unix (secondes)
    wallet: str
    name: str
    condition_id: str
    outcome_index: int
    side: str                    # BUY | SELL
    price: float                 # prix de l'issue échangée (0-1)
    size: float                  # nombre de parts
    title: str = ""


def get_json(url: str, retries: int = 3, timeout: float = 30.0, sleep=time.sleep):
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        sleep(delay)
        delay *= 2
    raise RuntimeError("inaccessible")


def _list(v) -> list:
    """Les champs outcomes / outcomePrices sont des listes encodées en chaîne JSON."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip().startswith("["):
        try:
            return json.loads(v)
        except ValueError:
            return []
    return []


def _date(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_market(m: dict) -> Optional[Market]:
    cid = m.get("conditionId") or m.get("condition_id")
    outcomes = tuple(str(o) for o in _list(m.get("outcomes")))
    if not cid or len(outcomes) != 2:
        return None
    try:
        prices = tuple(float(p) for p in _list(m.get("outcomePrices")))
    except (TypeError, ValueError):
        prices = ()
    winner = None
    if m.get("closed") and len(prices) == 2 and max(prices) >= 0.99 and min(prices) <= 0.01:
        winner = prices.index(max(prices))
    events = m.get("events") or [{}]
    category = m.get("category") or (events[0] or {}).get("category") or ""
    if not category:
        tags = (events[0] or {}).get("tags") or m.get("tags") or []
        category = next((t.get("label", "") for t in tags if isinstance(t, dict) and t.get("label")), "")
    return Market(cid, m.get("question") or "", m.get("slug") or "", _date(m.get("endDate")), outcomes, winner,
                  float(m.get("volumeNum") or m.get("volume") or 0), category or "Autre", prices)


def parse_trade(t: dict) -> Optional[Trade]:
    try:
        return Trade(int(t["timestamp"]), str(t["proxyWallet"]).lower(), t.get("pseudonym") or t.get("name") or "",
                     t["conditionId"], int(t["outcomeIndex"]), str(t["side"]).upper(), float(t["price"]),
                     float(t["size"]), t.get("title") or "")
    except (KeyError, TypeError, ValueError):
        return None


def fetch_resolved_markets(start: datetime, end: datetime, min_volume: float, max_volume: float, limit: int,
                           get: Callable = get_json, log=print) -> list[Market]:
    """Marchés binaires clos entre start et end, par volume décroissant, résolus nettement."""
    out, offset = [], 0
    while len(out) < limit and offset < 5000:
        q = urllib.parse.urlencode({"closed": "true", "limit": 100, "offset": offset, "order": "volumeNum",
                                    "ascending": "false", "end_date_min": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "end_date_max": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "volume_num_min": min_volume, "volume_num_max": max_volume})
        page = get(f"{GAMMA}/markets?{q}")
        if not page:
            break
        for m in page:
            mk = parse_market(m)
            if mk and mk.winner is not None:
                out.append(mk)
        offset += 100
        log(f"  Polymarket : {len(out)} marchés résolus retenus (page {offset // 100})")
    return out[:limit]


def fetch_market_trades(condition_id: str, max_pages: int = 4, get: Callable = get_json, pause: float = 0.2,
                        sleep=time.sleep) -> list[Trade]:
    """Ordres « preneurs » (qui franchissent le carnet) d'un marché, les plus récents d'abord."""
    out = []
    for page in range(max_pages):
        rows = get(f"{DATA}/trades?market={condition_id}&limit=500&offset={page * 500}")
        trades = [t for t in (parse_trade(r) for r in rows or []) if t]
        out += trades
        if len(rows or []) < 500:
            break
        sleep(pause)
    return out


def fetch_wallet_trades(wallet: str, limit: int = 100, get: Callable = get_json) -> list[Trade]:
    rows = get(f"{DATA}/trades?user={wallet}&limit={limit}&takerOnly=false")
    return [t for t in (parse_trade(r) for r in rows or []) if t]


def fetch_markets_by_id(condition_ids: list[str], get: Callable = get_json) -> dict[str, Market]:
    out = {}
    for i in range(0, len(condition_ids), 20):
        q = "&".join(f"condition_ids={urllib.parse.quote(c)}" for c in condition_ids[i:i + 20])
        for m in get(f"{GAMMA}/markets?{q}&limit=20") or []:
            mk = parse_market(m)
            if mk:
                out[mk.condition_id] = mk
    return out


def fetch_leaderboard(period: str = "MONTH", limit: int = 50, get: Callable = get_json) -> list[dict]:
    rows = get(f"{DATA}/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit={limit}")
    return [{"wallet": str(r.get("proxyWallet", "")).lower(), "name": r.get("userName") or "",
             "pnl": float(r.get("pnl") or 0), "volume": float(r.get("vol") or 0)} for r in rows or []]
