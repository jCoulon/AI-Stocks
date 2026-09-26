"""Structures de données partagées par les fournisseurs et les moteurs d'analyse."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass(frozen=True)
class Security:
    ticker: str
    name: str
    sector: str
    beta: float = 1.0


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class NewsItem:
    ticker: Optional[str]  # None = news macro / marché
    published: datetime
    source: str
    headline: str
    #: Ton précalculé du titre (-1 à 1, ex. FinBERT) ; None = calculé par le lexique.
    tone: Optional[float] = None


@dataclass(frozen=True)
class SocialPost:
    ticker: str
    posted: datetime
    platform: str
    author: str
    author_age_days: int
    likes: int
    text: str


# Série macro : liste ordonnée de (date, valeur)
Series = list[tuple[date, float]]


@dataclass
class Signal:
    """Un indicateur élémentaire, ramené à un score dans [-1, 1]."""

    name: str
    value: Optional[float]
    score: float
    weight: float
    comment: str


@dataclass
class PillarResult:
    """Résultat d'un pilier d'analyse (technique, sentiment, macro) pour un horizon."""

    pillar: str
    horizon: str
    signals: list[Signal] = field(default_factory=list)

    @property
    def score(self) -> float:
        total = sum(s.weight for s in self.signals)
        if total == 0:
            return 0.0
        return sum(s.score * s.weight for s in self.signals) / total


@dataclass
class Flag:
    """Alerte de qualité ou de cohérence des données."""

    code: str
    severity: str  # "info" | "warning" | "critical"
    message: str


@dataclass
class Outlook:
    horizon: str  # "court" | "moyen"
    score: float
    label: str
    confidence: float
    low: float
    high: float
    contributions: dict[str, float] = field(default_factory=dict)


@dataclass
class KeyLevel:
    label: str
    price: float
    kind: str  # "support" | "resistance" | "moyenne" | "extreme"


@dataclass
class Catalyst:
    """News récente et réaction du cours le jour de sa publication."""

    published: datetime
    source: str
    headline: str
    tone: float
    reaction: Optional[float]  # rendement de la séance de réaction
    retained: bool  # False = écartée par le contrôleur (rumeur non confirmée)


@dataclass
class Peer:
    ticker: str
    week_return: float
    short_score: float
    medium_score: float


@dataclass
class StockReport:
    """Fiche d'analyse détaillée d'une action (agent analyste-titre)."""

    thesis: str
    strengths: list[str]
    risks: list[str]
    performance: dict[str, float]  # horizon -> rendement
    relative: dict[str, float]  # horizon -> surperformance vs S&P 500
    risk_metrics: dict[str, float]
    levels: list[KeyLevel]
    catalysts: list[Catalyst]
    social: dict[str, float]
    peers: list[Peer]
    sector_rank: tuple[int, int]  # (rang court terme dans le secteur, nb de titres)
    #: Historique pour le graphique : (date, clôture, MM50, MM200)
    history: list[tuple[date, float, Optional[float], Optional[float]]]


@dataclass
class TickerAnalysis:
    security: Security
    last_close: float
    week_return: float
    week_closes: list[tuple[date, float]]
    pillars: dict[str, PillarResult]
    flags: list[Flag]
    data_quality: float
    coherence: float
    short: Outlook
    medium: Outlook
    stats: dict[str, float] = field(default_factory=dict)
    stock: Optional[StockReport] = None
    #: Vue « recherche » (facteurs académiques, régime, GARCH) — voir analysis/research.py
    research: Optional[Any] = None


@dataclass
class MarketReport:
    as_of: date
    index: TickerAnalysis
    tickers: list[TickerAnalysis]
    macro_summary: dict[str, float]
    breadth: dict[str, float]
    market_news: list[NewsItem]
    #: Synthèse rédigée par l'agent rédacteur (optionnel, via Claude).
    narrative: Optional[str] = None
    #: Journal d'exécution de l'orchestrateur (une entrée par tâche d'agent).
    trace: list = field(default_factory=list)
