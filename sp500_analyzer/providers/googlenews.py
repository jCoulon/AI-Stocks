"""Historique de news financières par action via le flux RSS de recherche de Google News.

Le flux accepte les opérateurs de recherche (guillemets, OR, after:/before:) et renvoie jusqu'à
100 titres par requête, chacun avec sa source d'origine. Trois filtres ne gardent que
l'actualité financière :
  1. la requête exige le nom de l'entreprise ET un terme boursier (stock, shares, earnings...) ;
  2. seules les sources connues (NEWS_DOMAINS, avec leur fiabilité) sont conservées ;
  3. le ton de chaque titre est ensuite noté par FinBERT (voir finbert.py).

Flux public destiné aux lecteurs RSS, pas une API officielle : rythme modéré (une requête
toutes les quelques secondes), usage de recherche personnel.
Fichiers : <dossier>/news/google/<TICKER>.csv (+ fenetres/ et couverture.csv, comme GDELT).
"""

from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from .realnews import (
    GDELT_QUERIES, MARKET, NEW_YORK, download_windows, http_get, news_windows, source_for_domain,
)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
GOOGLE_PAUSE = 3.0
FINANCE_TERMS = "(stock OR shares OR earnings OR revenue OR analyst OR guidance OR investors)"
MARKET_QUERY = '("Wall Street" OR "S&P 500" OR "stock market" OR "Federal Reserve" OR "Treasury yields")'
# Requêtes Google propres à certains titres : le terme boursier obligatoire écarte déjà les
# homonymes, un nom plus large ramène donc plus d'articles pertinents qu'avec GDELT.
GOOGLE_NAMES = {"AMZN": '"Amazon"', "CAT": '"Caterpillar"', "V": '("Visa Inc" OR "Visa shares" OR "Visa stock" OR "Visa earnings")'}
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                                 "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"}


def google_query(ticker: str, start: date, end: date) -> str:
    """Requête financière d'un titre sur [start, end) : entreprise ET terme boursier."""
    base = MARKET_QUERY if ticker == MARKET else f"{GOOGLE_NAMES.get(ticker, GDELT_QUERIES[ticker])} {FINANCE_TERMS}"
    # before: est exclusif et after: inclusif côté Google : [start, end)
    return f"{base} after:{(start - timedelta(days=1)).isoformat()} before:{end.isoformat()}"


def parse_google_rss(body: str) -> list[tuple[datetime, str, str, str, str]]:
    """(publication heure de New York, source, domaine, titre, url) des titres de sources connues.

    Google suffixe chaque titre par « - Nom de la source » et indique le site d'origine dans
    <source url="...">. Les titres d'autres sources sont écartés."""
    root = ET.fromstring(body.strip().encode("utf-8"))
    rows = []
    for item in root.iter("item"):
        src = item.find("source")
        domain = urllib.parse.urlparse(src.get("url", "") if src is not None else "").netloc.lower()
        domain = domain.removeprefix("www.")
        source = source_for_domain(domain)
        title = (item.findtext("title") or "").strip()
        name = (src.text or "").strip() if src is not None else ""
        if name and title.endswith(f" - {name}"):
            title = title[: -len(name) - 3].strip()
        pub = item.findtext("pubDate")
        if not source or len(title) < 15 or not pub:
            continue
        try:
            published = parsedate_to_datetime(pub).astimezone(NEW_YORK).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        rows.append((published, source, domain, title, (item.findtext("link") or "").strip()))
    return sorted(rows)


def fetch_google(ticker: str, start: datetime, end: datetime, get=None) -> list:
    url = GOOGLE_NEWS_RSS.format(query=urllib.parse.quote(google_query(ticker, start.date(), end.date())))
    get = get or (lambda u: http_get(u, headers=BROWSER_HEADERS, retries=0, timeout=20))
    # Le flux est trié par pertinence : on ne garde que la fenêtre demandée.
    return [r for r in parse_google_rss(get(url)) if start <= r[0] < end + timedelta(hours=12)]


def download_google_news(out_dir: Path, tickers: list[str], start: date, end: date,
                         pause: float = GOOGLE_PAUSE, budget_minutes: float = 30.0,
                         today: Optional[date] = None, log=print, clock=time.monotonic,
                         sleep=time.sleep, get=None) -> list[str]:
    known = [t for t in tickers if t in GDELT_QUERIES or t == MARKET]
    return download_windows(out_dir / "news" / "google", known, news_windows(start, end),
                            lambda t, s, e: fetch_google(t, s, e, get), "Google News",
                            pause, budget_minutes, today or date.today(), log, clock, sleep)
