"""Interface que doit respecter toute source de données (simulée ou réelle)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime

from ..models import Bar, NewsItem, Security, Series, SocialPost


class DataProvider(ABC):
    """Contrat d'accès aux données de marché, news, réseaux sociaux et macro.

    Pour brancher de vraies données (API de cours, flux de news, API sociale,
    FRED...), il suffit d'implémenter cette classe : les moteurs d'analyse ne
    dépendent que de ces méthodes.
    """

    #: Dernière séance couverte par les données.
    as_of: date

    @abstractmethod
    def universe(self) -> list[Security]:
        """Actions à analyser."""

    @abstractmethod
    def index(self) -> Security:
        """Indice de référence (S&P 500)."""

    @abstractmethod
    def trading_days(self) -> list[date]:
        """Calendrier officiel des séances couvert par l'historique."""

    @abstractmethod
    def price_history(self, ticker: str) -> list[Bar]:
        """Barres journalières OHLCV triées par date croissante."""

    @abstractmethod
    def news(self, ticker: str | None, since: datetime) -> list[NewsItem]:
        """News d'une action (ou news de marché si ticker est None)."""

    @abstractmethod
    def social_posts(self, ticker: str, since: datetime) -> list[SocialPost]:
        """Messages publiés sur les réseaux sociaux au sujet d'une action."""

    @abstractmethod
    def macro(self) -> dict[str, Series]:
        """Séries macro-économiques et indicateurs de sentiment de marché.

        Clés attendues : us10y, us2y, fed_funds, cpi_yoy, unemployment,
        ism_pmi, vix, wti, put_call, aaii_spread.

        IMPORTANT (point-in-time) : chaque point doit être daté de sa date de
        **publication**, pas de la période qu'il mesure. Le CPI d'août, publié mi-septembre,
        est daté de mi-septembre. Sinon l'analyse utiliserait des chiffres qui n'étaient pas
        encore connus (biais d'anticipation).
        """
