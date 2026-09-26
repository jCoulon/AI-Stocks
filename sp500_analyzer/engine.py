"""Orchestration : récupère les données, vérifie leur cohérence, calcule les avis."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .analysis.coherence import assess
from .analysis.macro import analyze_macro, macro_summary
from .analysis.scoring import build_outlook
from .analysis.sentiment import analyze_sentiment
from .analysis.technical import analyze_technical
from .models import Bar, MarketReport, Security, TickerAnalysis
from .providers.base import DataProvider


def _week_closes(bars: list[Bar], n: int = 6):
    return [(b.day, b.close) for b in bars[-n:]]


def analyze_security(
    provider: DataProvider,
    security: Security,
    macro: dict,
    index_bars: list[Bar] | None,
) -> TickerAnalysis:
    now = datetime.combine(provider.as_of, time(22, 0))
    bars = provider.price_history(security.ticker)
    is_index = index_bars is None
    # Pour l'indice, le flux de news pertinent est celui des news de marché.
    news = provider.news(None if is_index else security.ticker, now - timedelta(days=45))
    posts = [] if is_index else provider.social_posts(security.ticker, now - timedelta(days=14))

    coh = assess(bars, provider.trading_days(), news, posts, provider.as_of, now)

    tech_s, tech_m, tstats = analyze_technical(bars, index_bars)
    macro_s, macro_m = analyze_macro(macro, security.sector, provider.as_of)
    pillars_s = {"technique": tech_s, "macro": macro_s}
    pillars_m = {"technique": tech_m, "macro": macro_m}
    sent_s, sent_m, sstats = analyze_sentiment(coh.trusted_news, posts, now, coh.social_trust)
    pillars_s["sentiment"] = sent_s
    pillars_m["sentiment"] = sent_m

    trust = {"technique": coh.price_trust}
    last = bars[-1].close
    vol = tstats["daily_vol"]
    short = build_outlook("court", pillars_s, last, vol, coh.data_quality, coh.coherence, trust)
    medium = build_outlook("moyen", pillars_m, last, vol, coh.data_quality, coh.coherence, trust)

    week_ref = next((b.close for b in reversed(bars) if b.day <= provider.as_of - timedelta(days=7)), bars[-6].close)
    pillars = {f"{k}_court": v for k, v in pillars_s.items()} | {f"{k}_moyen": v for k, v in pillars_m.items()}
    return TickerAnalysis(
        security=security,
        last_close=last,
        week_return=last / week_ref - 1,
        week_closes=_week_closes(bars),
        pillars=pillars,
        flags=coh.flags,
        data_quality=coh.data_quality,
        coherence=coh.coherence,
        short=short,
        medium=medium,
        stats={**tstats, **sstats, **coh.stats},
    )


def run_analysis(provider: DataProvider, tickers: list[str] | None = None) -> MarketReport:
    macro = provider.macro()
    index_bars = provider.price_history(provider.index().ticker)
    index = analyze_security(provider, provider.index(), macro, None)

    all_results = [analyze_security(provider, s, macro, index_bars) for s in provider.universe()]
    wanted = {t.upper() for t in tickers or []}
    results = [r for r in all_results if not wanted or r.security.ticker in wanted]

    n = len(all_results) or 1
    breadth = {
        "advancers_week": sum(r.week_return > 0 for r in all_results) / n,
        "above_sma50": sum(r.last_close > r.stats.get("sma50", float("inf")) for r in all_results) / n,
        "above_sma200": sum(r.last_close > r.stats.get("sma200", float("inf")) for r in all_results) / n,
        "short_bullish": sum(r.short.score >= 0.12 for r in all_results) / n,
        "short_bearish": sum(r.short.score <= -0.12 for r in all_results) / n,
    }
    since = datetime.combine(provider.as_of, time(0)) - timedelta(days=7)
    return MarketReport(
        as_of=provider.as_of,
        index=index,
        tickers=results,
        macro_summary=macro_summary(macro),
        breadth=breadth,
        market_news=provider.news(None, since),
    )
