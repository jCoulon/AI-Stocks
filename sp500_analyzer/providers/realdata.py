"""Source de données entièrement réelle, lue dans le dossier rempli par les workflows
« Données de marché réelles » (cours) et « News et macro réelles » (news, SEC, FRED).

  <dossier>/daily/<TICKER>.csv   cours quotidiens ajustés (voir CsvPriceProvider)
  <dossier>/news/<TICKER>.csv    articles GDELT de sources connues ; news/MARCHE.csv = marché
  <dossier>/news/google/<TICKER>.csv  titres financiers via Google News (historique)
  <dossier>/news/rss/<TICKER>.csv  titres des flux RSS Yahoo Finance / Nasdaq (collecte continue)
  <dossier>/news/finbert.csv     ton FinBERT de chaque titre (sinon : lexique financier)
  <dossier>/sec/<TICKER>.csv     dépôts réglementaires (8-K, 10-Q, 10-K...)
  <dossier>/social/stocktwits/<TICKER>.csv  messages StockTwits (collecte continue)
  <dossier>/social/reddit/<TICKER>.csv      messages Reddit via flux RSS (collecte continue)
  <dossier>/macro/<clé>.csv      séries FRED datées de leur publication

Chaque partie est facultative sauf les cours : ce qui manque reste vide et l'outil le signale.
Réseaux sociaux : StockTwits et Reddit, historique construit à partir de la mise en place.
"""

from __future__ import annotations

import csv
from bisect import bisect_left
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from ..models import NewsItem, Series, SocialPost
from .csv_prices import CsvPriceProvider
from .finbert import load_scores
from .realnews import MARKET, SEC_SOURCE, title_key
from .stocktwits import load_posts


def read_news(paths: list[Path], ticker: Optional[str], tones: dict[str, float]) -> list[NewsItem]:
    """News de plusieurs fichiers (GDELT, RSS), dédoublonnées par titre, avec le ton FinBERT
    quand il a été calculé."""
    items: dict[str, NewsItem] = {}
    for path in paths:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r.get("Title"):
                    continue
                key = title_key(r["Title"])
                item = NewsItem(ticker, datetime.fromisoformat(r["Published"]), r["Source"], r["Title"], tones.get(key))
                if key not in items or item.published < items[key].published:
                    items[key] = item
    return list(items.values())


def read_sec(path: Path, ticker: str) -> list[NewsItem]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [NewsItem(ticker, datetime.fromisoformat(r["Published"]), SEC_SOURCE, r["Title"])
                for r in csv.DictReader(f)]


def read_series(path: Path) -> Series:
    with open(path, newline="", encoding="utf-8") as f:
        return sorted((date.fromisoformat(r["Date"]), float(r["Value"])) for r in csv.DictReader(f))


class RealDataProvider(CsvPriceProvider):
    def __init__(self, folder: str | Path, as_of: date | None = None, universe: str = "sp500"):
        root = Path(folder)
        super().__init__(root / "daily", as_of, universe)
        self.root = root
        self._news: dict[Optional[str], list[NewsItem]] = {}
        #: Ton FinBERT par titre (vide : le lexique est utilisé)
        self.tones = load_scores(root)
        for t in [s.ticker for s in self.universe()] + [None]:
            name = f"{t or MARKET}.csv"
            items = read_news([root / "news" / name, root / "news" / "google" / name, root / "news" / "rss" / name],
                              t, self.tones)
            if t:
                items += read_sec(root / "sec" / f"{t}.csv", t)
            self._news[t] = sorted(items, key=lambda n: n.published)
        # Ton : étiquette de l'auteur (StockTwits), sinon FinBERT. Reddit : ancienneté des
        # comptes inconnue (neutre, 365 j).
        self._posts = {t: sorted(load_posts(root / "social" / "stocktwits" / f"{t}.csv", t, tones=self.tones)
                                 + load_posts(root / "social" / "reddit" / f"{t}.csv", t, "Reddit", 365, self.tones),
                                 key=lambda p: p.posted)
                       for t in [s.ticker for s in self.universe()]}
        macro_dir = root / "macro"
        self._macro = {p.stem: read_series(p) for p in sorted(macro_dir.glob("*.csv"))} if macro_dir.exists() else {}
        press = [n.published for t, items in self._news.items() for n in items if n.source != SEC_SOURCE]
        #: Première date couverte par les articles de presse (None : aucun article).
        self.news_start: Optional[date] = min(press).date() if press else None

    def news(self, ticker: str | None, since: datetime) -> list[NewsItem]:
        items = self._news.get(ticker, [])
        return items[bisect_left(items, since, key=lambda n: n.published):]

    def social_posts(self, ticker: str, since: datetime) -> list[SocialPost]:
        posts = self._posts.get(ticker, [])
        return posts[bisect_left(posts, since, key=lambda p: p.posted):]

    def macro(self) -> dict[str, Series]:
        return {k: list(v) for k, v in self._macro.items()}

    def coverage(self) -> str:
        n_press = sum(1 for items in self._news.values() for n in items if n.source != SEC_SOURCE)
        n_sec = sum(1 for items in self._news.values() for n in items if n.source == SEC_SOURCE)
        parts = [f"{n_press} articles de presse" + (f" depuis le {self.news_start:%d/%m/%Y}" if self.news_start else ""),
                 f"{n_sec} dépôts SEC",
                 f"ton FinBERT : {sum(n.tone is not None for items in self._news.values() for n in items)}/{n_press} titres"
                 if self.tones else "ton : lexique", f"macro : {', '.join(self._macro) or 'aucune série'}",
                 "réseaux sociaux : " + ", ".join(
                     f"{sum(p.platform == name for posts in self._posts.values() for p in posts)} messages {name}"
                     for name in ("StockTwits", "Reddit"))
                 if any(self._posts.values()) else "réseaux sociaux : aucune source"]
        return " ; ".join(parts)
