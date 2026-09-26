"""Fiche d'analyse détaillée d'une action : thèse, niveaux clés, catalyseurs, risques, pairs."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from ..models import (
    Bar, Catalyst, KeyLevel, NewsItem, Peer, Signal, SocialPost, StockReport, TickerAnalysis,
)
from .coherence import CoherenceResult, reaction_index
from .indicators import mean, pct_returns, sma, stdev
from .sentiment import score_text

HORIZONS = [("1 semaine", 5), ("1 mois", 21), ("3 mois", 63), ("6 mois", 126), ("1 an", 252)]
PILLAR_NAMES = {"technique": "l'analyse technique", "sentiment": "le sentiment (news et réseaux sociaux)",
                "macro": "le contexte macro-économique",
                "recherche": "l'ensemble des facteurs issus de la recherche académique"}
CHART_DAYS = 126


def _ret(closes: list[float], n: int) -> Optional[float]:
    return closes[-1] / closes[-n - 1] - 1 if len(closes) > n else None


def performance(bars: list[Bar], index_bars: list[Bar]) -> tuple[dict[str, float], dict[str, float]]:
    closes = [b.close for b in bars]
    idx = {b.day: b.close for b in index_bars}
    perf, rel = {}, {}
    for label, n in HORIZONS:
        r = _ret(closes, n)
        if r is None:
            continue
        perf[label] = r
        start = bars[-n - 1].day
        if start in idx and bars[-1].day in idx:
            rel[label] = (1 + r) / (idx[bars[-1].day] / idx[start]) - 1
    return perf, rel


def risk_metrics(bars: list[Bar], index_bars: list[Bar], atr: float) -> dict[str, float]:
    closes = [b.close for b in bars]
    rets = pct_returns(closes)
    out = {"Volatilité annualisée": stdev(rets[-60:]) * math.sqrt(252),
           "ATR 14 j (% du cours)": atr / closes[-1]}

    # Bêta sur 120 séances, calculé uniquement sur les dates communes.
    idx = {b.day: b.close for b in index_bars}
    pairs = [(bars[i].close / bars[i - 1].close - 1, idx[bars[i].day] / idx[bars[i - 1].day] - 1)
             for i in range(max(1, len(bars) - 120), len(bars))
             if bars[i].day in idx and bars[i - 1].day in idx]
    if len(pairs) > 20:
        xs, ys = [p[1] for p in pairs], [p[0] for p in pairs]
        mx, my = mean(xs), mean(ys)
        var = sum((x - mx) ** 2 for x in xs)
        if var:
            out["Bêta vs S&P 500"] = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var

    peak, mdd = closes[-CHART_DAYS], 0.0
    for c in closes[-CHART_DAYS:]:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    out["Repli max. 6 mois"] = mdd
    return out


def key_levels(bars: list[Bar], sma50: Optional[float], sma200: Optional[float]) -> list[KeyLevel]:
    """Supports / résistances : pivots (plus bas / plus hauts locaux) des 60 dernières séances."""
    close = bars[-1].close
    window = bars[-60:]
    lows, highs = [], []
    for i in range(3, len(window) - 3):
        seg = window[i - 3:i + 4]
        if window[i].low == min(b.low for b in seg):
            lows.append(window[i])
        if window[i].high == max(b.high for b in seg):
            highs.append(window[i])

    def distinct(values: list[float]) -> list[float]:
        # Fusionne les niveaux distants de moins de 1 %.
        out: list[float] = []
        for v in values:
            if all(abs(v / o - 1) > 0.01 for o in out):
                out.append(v)
        return out

    supports = distinct(sorted((b.low for b in lows if b.low < close), reverse=True))[:2]
    resistances = distinct(sorted(b.high for b in highs if b.high > close))[:2]
    year = bars[-252:]
    hi, lo = max(b.high for b in year), min(b.low for b in year)
    # Un pivot confondu avec un extrême annuel n'est affiché qu'une fois.
    supports = [v for v in supports if abs(v / lo - 1) > 0.005]
    resistances = [v for v in resistances if abs(v / hi - 1) > 0.005]
    levels = [KeyLevel(f"Support {i + 1}", v, "support") for i, v in enumerate(supports)]
    levels += [KeyLevel(f"Résistance {i + 1}", v, "resistance") for i, v in enumerate(resistances)]
    if sma50:
        levels.append(KeyLevel("Moyenne 50 j", sma50, "moyenne"))
    if sma200:
        levels.append(KeyLevel("Moyenne 200 j", sma200, "moyenne"))
    levels.append(KeyLevel("Plus haut 52 sem.", hi, "extreme"))
    levels.append(KeyLevel("Plus bas 52 sem.", lo, "extreme"))
    return sorted(levels, key=lambda lv: -lv.price)


def catalysts(bars: list[Bar], news: list[NewsItem], quality: CoherenceResult, now: datetime) -> list[Catalyst]:
    trusted = set(id(n) for n in quality.trusted_news)
    out = []
    for n in news:
        if now - n.published > timedelta(days=7):
            continue
        i = reaction_index(bars, n.published)
        reaction = bars[i].close / bars[i - 1].close - 1 if i else None
        out.append(Catalyst(n.published, n.source, n.headline, score_text(n.headline), reaction, id(n) in trusted))
    return sorted(out, key=lambda c: c.published, reverse=True)


def social_stats(posts: list[SocialPost], stats: dict[str, float], now: datetime) -> dict[str, float]:
    recent = [p for p in posts if now - p.posted <= timedelta(days=3)]
    return {
        "Messages (3 j)": float(len(recent)),
        "Ton social (3 j)": stats.get("social_3d", 0.0),
        "Buzz vs normale": stats.get("buzz", 1.0),
        "Comptes < 30 jours": (sum(p.author_age_days < 30 for p in recent) / len(recent)) if recent else 0.0,
        "Score de manipulation": stats.get("bot_score", 0.0),
    }


def _all_signals(t: TickerAnalysis, pillars: tuple[str, ...]) -> list[tuple[str, Signal]]:
    out = []
    for key, pillar in t.pillars.items():
        if pillar.pillar not in pillars:
            continue
        horizon = "CT" if key.endswith("_court") else "MT"
        out += [(horizon, s) for s in pillar.signals]
    return out


def strengths_and_risks(t: TickerAnalysis, levels: list[KeyLevel], metrics: dict[str, float],
                        cats: list[Catalyst]) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    strengths, risks = [], []

    def pick(signals, sign: int, limit: int, target: list[str], threshold: float) -> None:
        count = 0
        for horizon, sig in sorted(signals, key=lambda x: -sign * x[1].score * x[1].weight):
            if count >= limit:
                break
            if sign * sig.score >= threshold and sig.name not in seen:
                target.append(f"{sig.name} ({horizon}) : {sig.comment}")
                seen.add(sig.name)
                count += 1

    # Signaux propres au titre d'abord ; le contexte macro (commun à tous) ensuite, en appoint.
    specific = _all_signals(t, ("technique", "sentiment", "recherche"))
    context = _all_signals(t, ("macro",))
    pick(specific, +1, 4, strengths, 0.4)
    pick(context, +1, 1, strengths, 0.5)
    pick(specific, -1, 4, risks, 0.3)
    pick(context, -1, 1, risks, 0.3)

    for c in cats:
        if c.retained and abs(c.tone) > 0.3 and c.reaction is not None and c.reaction * c.tone > 0:
            (strengths if c.tone > 0 else risks).append(
                f"Catalyseur : « {c.headline} » ({c.source}, {c.reaction:+.1%} le jour même)")
    risks += [f"Alerte données : {f.message}" for f in t.flags if f.severity != "info"]

    close = t.last_close
    res = [lv for lv in levels if lv.kind == "resistance"]
    if res and res[-1].price / close - 1 < 0.02:
        risks.append(f"Cours proche d'une résistance ({res[-1].price:,.2f}, {res[-1].price / close - 1:+.1%})")
    vol = metrics.get("Volatilité annualisée", 0)
    if vol > 0.45:
        risks.append(f"Volatilité élevée ({vol:.0%} annualisée) : amplitude des mouvements importante")
    return strengths, risks


def thesis(t: TickerAnalysis, perf: dict[str, float], rank: tuple[int, int]) -> str:
    s = t.security
    parts = [f"{s.name} ({s.ticker}) ressort «\u00a0{t.short.label.lower()}\u00a0» à court terme "
             f"(score {t.short.score:+.2f}, confiance {t.short.confidence:.0%}) et «\u00a0{t.medium.label.lower()}\u00a0» "
             f"à moyen terme (score {t.medium.score:+.2f}, confiance {t.medium.confidence:.0%})."]
    drivers = []
    for o in (t.short, t.medium):
        lead = max(o.contributions, key=lambda k: abs(o.contributions[k]))
        drivers.append((lead, "soutient le plus" if o.contributions[lead] > 0 else "pèse le plus sur"))
    if drivers[0] == drivers[1]:
        lead, verb = drivers[0]
        parts.append(f"Aux deux horizons, c'est {PILLAR_NAMES.get(lead, lead)} qui {verb} l'avis.")
    else:
        for (lead, verb), horizon in zip(drivers, ("court", "moyen")):
            parts.append(f"À {horizon} terme, c'est {PILLAR_NAMES.get(lead, lead)} qui {verb} l'avis.")
    if "1 semaine" in perf and "3 mois" in perf:
        parts.append(f"Le titre a fait {perf['1 semaine']:+.1%} sur la semaine et {perf['3 mois']:+.1%} sur 3 mois.")
    if rank[1] > 1:
        ordinal = "1er" if rank[0] == 1 else f"{rank[0]}e"
        parts.append(f"Il se classe {ordinal} sur {rank[1]} dans son secteur ({s.sector}) à court terme.")
    if t.coherence < 0.8 or t.data_quality < 0.9:
        parts.append("Les données présentent des incohérences : l'avis est à prendre avec prudence.")
    return " ".join(parts)


def build_stock_report(
    t: TickerAnalysis,
    bars: list[Bar],
    index_bars: list[Bar],
    news: list[NewsItem],
    posts: list[SocialPost],
    quality: CoherenceResult,
    sector_results: list[TickerAnalysis],
    now: datetime,
) -> StockReport:
    closes = [b.close for b in bars]
    s50, s200 = sma(closes, 50), sma(closes, 200)
    perf, rel = performance(bars, index_bars)
    metrics = risk_metrics(bars, index_bars, t.stats.get("atr", 0.0))
    levels = key_levels(bars, s50[-1], s200[-1])
    cats = catalysts(bars, news, quality, now)

    ranked = sorted(sector_results, key=lambda r: -r.short.score)
    rank = (next((i + 1 for i, r in enumerate(ranked) if r.security.ticker == t.security.ticker), 1), len(ranked))
    peers = [Peer(r.security.ticker, r.week_return, r.short.score, r.medium.score)
             for r in ranked if r.security.ticker != t.security.ticker]

    strengths, risks = strengths_and_risks(t, levels, metrics, cats)
    history = [(bars[i].day, bars[i].close, s50[i], s200[i]) for i in range(max(0, len(bars) - CHART_DAYS), len(bars))]
    return StockReport(
        thesis=thesis(t, perf, rank),
        strengths=strengths,
        risks=risks,
        performance=perf,
        relative=rel,
        risk_metrics=metrics,
        levels=levels,
        catalysts=cats,
        social=social_stats(posts, t.stats, now),
        peers=peers,
        sector_rank=rank,
        history=history,
    )
