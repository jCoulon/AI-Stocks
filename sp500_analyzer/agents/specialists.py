"""Agents spécialistes déterministes : chacun encapsule un pilier d'analyse."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from ..analysis.coherence import CoherenceResult, assess
from ..analysis.macro import analyze_macro, macro_summary
from ..analysis.research import ResearchView, TickerInputs, build_research
from ..analysis.scoring import HORIZON_DAYS
from ..analysis.scoring import build_outlook
from ..analysis.sentiment import analyze_sentiment
from ..analysis.stock import build_stock_report
from ..analysis.technical import analyze_technical
from ..models import (
    Bar, Flag, MarketReport, NewsItem, PillarResult, Security, SocialPost, StockReport, TickerAnalysis,
)
from .base import Agent, Blackboard, Task


@dataclass
class TickerData:
    security: Security
    bars: list[Bar]
    news: list[NewsItem]
    posts: list[SocialPost]
    is_index: bool = False


@dataclass
class PillarPair:
    short: PillarResult
    medium: PillarResult
    stats: dict[str, float] = field(default_factory=dict)


def security_for(board: Blackboard, ticker: str) -> tuple[Security, bool]:
    index = board.provider.index()
    if ticker == index.ticker:
        return index, True
    for s in board.provider.universe():
        if s.ticker == ticker:
            return s, False
    raise KeyError(f"Titre inconnu : {ticker}")


class DataCollectorAgent(Agent):
    name = "collecteur"
    role = "Rassemble cours, news et messages sociaux d'un titre"

    def run(self, task: Task, board: Blackboard) -> TickerData:
        security, is_index = security_for(board, task.ticker)
        p = board.provider
        bars = p.price_history(security.ticker)
        if not bars:
            raise ValueError(f"Aucun cours disponible pour {security.ticker}")
        # Pour l'indice, le flux de news pertinent est celui des news de marché.
        news = p.news(None if is_index else security.ticker, board.now - timedelta(days=45))
        posts = [] if is_index else p.social_posts(security.ticker, board.now - timedelta(days=14))
        return TickerData(security, bars, news, posts, is_index)


class MacroEconomistAgent(Agent):
    name = "economiste"
    role = "Lit les séries macro et en déduit une vue par secteur"

    def run(self, task: Task, board: Blackboard) -> dict:
        series = board.provider.macro()
        sectors = {s.sector for s in board.provider.universe()} | {board.provider.index().sector}
        views = {}
        for sector in sorted(sectors):
            short, medium = analyze_macro(series, sector, board.provider.as_of)
            views[sector] = PillarPair(short, medium)
        return {"summary": macro_summary(series), "views": views}


class QualityControlAgent(Agent):
    name = "controleur"
    role = "Audite la qualité des données et recoupe les sources (rumeurs, bots, divergences)"

    def run(self, task: Task, board: Blackboard) -> CoherenceResult:
        data: TickerData = board.get(f"collect:{task.ticker}")
        p = board.provider
        return assess(data.bars, p.trading_days(), data.news, data.posts, p.as_of, board.now)


class TechnicalAnalystAgent(Agent):
    name = "technicien"
    role = "Analyse les graphiques : tendance, momentum, volumes, force relative"

    def run(self, task: Task, board: Blackboard) -> PillarPair:
        data: TickerData = board.get(f"collect:{task.ticker}")
        index_data: TickerData | None = None if data.is_index else board.get(f"collect:{board.provider.index().ticker}")
        short, medium, stats = analyze_technical(data.bars, index_data.bars if index_data else None)
        return PillarPair(short, medium, stats)


class SentimentAnalystAgent(Agent):
    name = "sentiment"
    role = "Mesure le ton des news fiables et des réseaux sociaux, selon les consignes du contrôleur"

    def run(self, task: Task, board: Blackboard) -> PillarPair:
        data: TickerData = board.get(f"collect:{task.ticker}")
        quality: CoherenceResult = board.get(f"quality:{task.ticker}")
        # Le contrôleur fixe les règles : news non confirmées exclues, poids social réduit si bots.
        short, medium, stats = analyze_sentiment(quality.trusted_news, data.posts, board.now, quality.social_trust)
        return PillarPair(short, medium, stats)


class StrategistAgent(Agent):
    name = "strategiste"
    role = "Confronte les avis des analystes et rend un verdict court et moyen terme"

    def run(self, task: Task, board: Blackboard) -> TickerAnalysis:
        t = task.ticker
        data: TickerData = board.get(f"collect:{t}")
        quality: CoherenceResult = board.get(f"quality:{t}")
        tech: PillarPair = board.get(f"technical:{t}")
        macro = board.get("macro")
        sentiment: PillarPair | None = board.get(f"sentiment:{t}")

        flags = list(quality.flags)
        coherence = quality.coherence
        pillars_s = {"technique": tech.short}
        pillars_m = {"technique": tech.medium}
        if macro:
            view: PillarPair = macro["views"][data.security.sector]
            pillars_s["macro"], pillars_m["macro"] = view.short, view.medium
        else:
            flags.append(Flag("AGENT_FAILURE", "warning", "Vue macro indisponible : avis rendu sans ce pilier"))
            coherence -= 0.1
        research_views = board.get("research")
        research: ResearchView | None = research_views.get(t) if research_views else None
        if research:
            pillars_s["recherche"], pillars_m["recherche"] = research.pillars()
        if sentiment:
            pillars_s["sentiment"], pillars_m["sentiment"] = sentiment.short, sentiment.medium
        else:
            flags.append(Flag("AGENT_FAILURE", "warning", "Analyse de sentiment indisponible : avis rendu sans ce pilier"))
            coherence -= 0.1
        coherence = max(0.1, coherence)

        trust = {"technique": quality.price_trust}
        last = data.bars[-1].close
        vol = tech.stats["daily_vol"]
        garch = research.garch if research else None
        short = build_outlook("court", pillars_s, last, vol, quality.data_quality, coherence, trust,
                              garch.horizon_vol(HORIZON_DAYS["court"]) if garch else None)
        medium = build_outlook("moyen", pillars_m, last, vol, quality.data_quality, coherence, trust,
                               garch.horizon_vol(HORIZON_DAYS["moyen"]) if garch else None)

        as_of = board.provider.as_of
        week_ref = next((b.close for b in reversed(data.bars) if b.day <= as_of - timedelta(days=7)),
                        data.bars[max(0, len(data.bars) - 6)].close)
        pillars = {f"{k}_court": v for k, v in pillars_s.items()} | {f"{k}_moyen": v for k, v in pillars_m.items()}
        return TickerAnalysis(
            security=data.security,
            last_close=last,
            week_return=last / week_ref - 1,
            week_closes=[(b.day, b.close) for b in data.bars[-6:]],
            pillars=pillars,
            flags=flags,
            data_quality=quality.data_quality,
            coherence=coherence,
            short=short,
            medium=medium,
            stats={**tech.stats, **(sentiment.stats if sentiment else {}), **quality.stats},
            research=research,
        )


class QuantResearchAgent(Agent):
    name = "chercheur"
    role = "Calcule les facteurs issus de la recherche académique et les classe dans l'univers"

    def __init__(self, tickers: list[str]):
        self.tickers = tickers

    def run(self, task: Task, board: Blackboard) -> dict[str, ResearchView]:
        index_data: TickerData = board.get(f"collect:{board.provider.index().ticker}")
        inputs: dict[str, TickerInputs] = {}
        for t in self.tickers:
            data: TickerData | None = board.get(f"collect:{t}")
            if data is None:  # collecte en échec : titre exclu du classement
                continue
            quality: CoherenceResult | None = board.get(f"quality:{t}")
            inputs[t] = TickerInputs(data.bars, data.security.sector,
                                     quality.trusted_news if quality else [], data.posts, board.now)
        return build_research(inputs, index_data.bars)


class MarketStrategistAgent(Agent):
    name = "chef-strategiste"
    role = "Agrège les verdicts : indice, largeur de marché, news macro"

    def __init__(self, tickers: list[str]):
        self.tickers = tickers

    def run(self, task: Task, board: Blackboard) -> MarketReport:
        p = board.provider
        index = board.get(f"strategy:{p.index().ticker}")
        results: list[TickerAnalysis] = [r for t in self.tickers if (r := board.get(f"strategy:{t}"))]
        n = len(results) or 1

        def share_above(key: str) -> float:
            # Rapporté aux seuls titres dont la moyenne est calculable (historique suffisant).
            known = [r for r in results if r.stats.get(key) is not None]
            return sum(r.last_close > r.stats[key] for r in known) / len(known) if known else 0.0

        breadth = {
            "advancers_week": sum(r.week_return > 0 for r in results) / n,
            "above_sma50": share_above("sma50"),
            "above_sma200": share_above("sma200"),
            "short_bullish": sum(r.short.score >= 0.12 for r in results) / n,
            "short_bearish": sum(r.short.score <= -0.12 for r in results) / n,
        }
        macro = board.get("macro")
        since = datetime.combine(p.as_of, time(0)) - timedelta(days=7)
        return MarketReport(
            as_of=p.as_of,
            index=index,
            tickers=results,
            macro_summary=macro["summary"] if macro else {},
            breadth=breadth,
            market_news=p.news(None, since),
        )


class StockAnalystAgent(Agent):
    name = "analyste-titre"
    role = "Rédige la fiche détaillée d'une action : thèse, niveaux clés, catalyseurs, risques, pairs"

    def run(self, task: Task, board: Blackboard) -> StockReport:
        t = task.ticker
        analysis: TickerAnalysis = board.get(f"strategy:{t}")
        data: TickerData = board.get(f"collect:{t}")
        index_data: TickerData = board.get(f"collect:{board.provider.index().ticker}")
        quality: CoherenceResult = board.get(f"quality:{t}")
        market: MarketReport = board.get("market")
        sector = [r for r in market.tickers if r.security.sector == analysis.security.sector]
        return build_stock_report(analysis, data.bars, index_data.bars, data.news, data.posts,
                                  quality, sector, board.now)
