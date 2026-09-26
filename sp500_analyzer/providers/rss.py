"""Collecte des flux RSS gratuits de news par action (Yahoo Finance, Nasdaq).

Ces flux ne gardent que les derniers titres (une vingtaine) : lancée plusieurs fois par jour
par le workflow « News RSS et FinBERT », la collecte accumule un historique à partir de
maintenant dans <dossier>/news/rss/<TICKER>.csv (même format que les news GDELT, dédoublonné).
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from .realnews import (
    MARKET, NEW_YORK, http_get, read_news_rows, source_for_domain, title_key, write_news_csv,
)

YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
NASDAQ_RSS = "https://www.nasdaq.com/feed/rssoutbound?symbol={symbol}"
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                                 "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                   "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"}


def parse_rss(body: str, default_source: str) -> list[tuple[datetime, str, str, str, str]]:
    """(publication heure de New York, source, domaine, titre, url) des éléments d'un flux RSS 2.0."""
    root = ET.fromstring(body.strip().encode("utf-8"))
    rows = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        if len(title) < 15 or not pub:
            continue
        try:
            published = parsedate_to_datetime(pub).astimezone(NEW_YORK).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        domain = urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
        rows.append((published, source_for_domain(domain) or default_source, domain, title, link))
    return rows


def merge_rows(existing: list, new: list) -> list:
    """Fusionne en dédoublonnant par titre (la première parution est gardée)."""
    rows: dict[str, tuple] = {}
    for row in [*existing, *new]:
        key = title_key(row[3])
        if key not in rows or row[0] < rows[key][0]:
            rows[key] = row
    return sorted(rows.values())


def _feeds(ticker: str) -> list[tuple[str, str]]:
    if ticker == MARKET:
        return [(YAHOO_RSS.format(symbol=urllib.parse.quote("^GSPC")), "Yahoo Finance")]
    symbol = ticker.replace(".", "-")
    return [(YAHOO_RSS.format(symbol=symbol), "Yahoo Finance"), (NASDAQ_RSS.format(symbol=symbol.lower()), "Nasdaq")]


def collect_rss(out_dir: Path, tickers: list[str], log=print, fetch=None) -> list[str]:
    folder = out_dir / "news" / "rss"
    folder.mkdir(parents=True, exist_ok=True)
    fetch = fetch or (lambda url: http_get(url, headers=BROWSER_HEADERS, retries=1, timeout=20))
    errors = []
    for ticker in tickers:
        new: list = []
        for url, source in _feeds(ticker):
            try:
                new += parse_rss(fetch(url), source)
            except Exception as e:  # noqa: BLE001 — un flux en échec n'empêche pas les autres
                errors.append(f"RSS {ticker} ({source}) : {type(e).__name__}: {str(e)[:120]}")
        path = folder / f"{ticker}.csv"
        existing = read_news_rows(path) if path.exists() else []
        merged = merge_rows(existing, new)
        write_news_csv(path, merged)
        log(f"  RSS {ticker:6} {len(new):3} titres lus, {len(merged) - len(existing):3} nouveaux, {len(merged)} au total")
    return errors


def latest(rows: list) -> Optional[datetime]:
    return max((r[0] for r in rows), default=None)
