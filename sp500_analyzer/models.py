"""Structures de données partagées par les fournisseurs et les moteurs d'analyse."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


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


@dataclass
class MarketReport:
    as_of: date
    index: TickerAnalysis
    tickers: list[TickerAnalysis]
    macro_summary: dict[str, float]
    breadth: dict[str, float]
    market_news: list[NewsItem]
