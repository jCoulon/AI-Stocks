"""Vue « point-in-time » d'une source de données : rien de postérieur à une date n'est visible.

Sert au backtest sur période : l'outil complet (tous les agents) est relancé à chaque date
comme s'il tournait ce jour-là, sans aucune information future (cours, news, messages,
chiffres macro publiés plus tard).
"""

from __future__ import annotations

from datetime import date, datetime, time

from ..models import Bar, NewsItem, Security, Series, SocialPost
from .base import DataProvider

# Heure de l'analyse : après la clôture américaine (16h), comme l'outil en production.
ANALYSIS_TIME = time(22, 0)


class PointInTimeProvider(DataProvider):
    def __init__(self, base: DataProvider, as_of: date):
        self.base = base
        self.as_of = as_of
        self._cutoff = datetime.combine(as_of, ANALYSIS_TIME)

    def universe(self) -> list[Security]:
        return self.base.universe()

    def index(self) -> Security:
        return self.base.index()

    def trading_days(self) -> list[date]:
        return [d for d in self.base.trading_days() if d <= self.as_of]

    def price_history(self, ticker: str) -> list[Bar]:
        return [b for b in self.base.price_history(ticker) if b.day <= self.as_of]

    def news(self, ticker: str | None, since: datetime) -> list[NewsItem]:
        return [n for n in self.base.news(ticker, since) if n.published <= self._cutoff]

    def social_posts(self, ticker: str, since: datetime) -> list[SocialPost]:
        return [p for p in self.base.social_posts(ticker, since) if p.posted <= self._cutoff]

    def macro(self) -> dict[str, Series]:
        # Les séries sont datées de leur publication (contrat de DataProvider.macro).
        return {k: [(d, v) for d, v in s if d <= self.as_of] for k, s in self.base.macro().items()}
