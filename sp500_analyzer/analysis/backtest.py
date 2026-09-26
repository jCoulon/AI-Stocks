"""Backtest « point-in-time » des facteurs de recherche calculables sur les cours.

Méthode (standard en finance empirique) :
- à chaque date de rebalancement t, les facteurs sont calculés sur l'historique
  tronqué à t (aucune donnée postérieure n'est visible) ;
- on mesure le coefficient d'information (IC) : corrélation de rang de Spearman entre
  le score du facteur et le rendement futur sur h séances, dans l'univers ;
- les dates sont espacées de h séances pour éviter le chevauchement des rendements
  futurs (sinon la statistique t serait artificiellement gonflée) ;
- t = IC moyen / (écart-type / √n). Harvey, Liu & Zhu (2016) recommandent |t| > 3
  pour un nouveau facteur, compte tenu du nombre de facteurs testés dans la littérature.

Les facteurs issus des news et des réseaux sociaux ne sont pas backtestés : leur
historique point-in-time n'est pas disponible dans les sources actuelles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..models import Bar
from ..providers.base import DataProvider
from .indicators import mean, stdev
from .research import FACTORS, TickerInputs, score_universe

BACKTEST_FACTORS = [f for f in FACTORS if f.price_only]


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> Optional[float]:
    if len(x) < 5:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = mean(rx), mean(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy)


@dataclass
class FactorStats:
    key: str
    name: str
    horizon: int
    ics: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.ics)

    @property
    def mean_ic(self) -> float:
        return mean(self.ics)

    @property
    def t_stat(self) -> float:
        sd = stdev(self.ics)
        return self.mean_ic / (sd / math.sqrt(self.n)) if self.n > 1 and sd > 0 else 0.0

    @property
    def hit_rate(self) -> float:
        return sum(ic > 0 for ic in self.ics) / self.n if self.n else 0.0


@dataclass
class BacktestReport:
    start: date
    end: date
    universe: int
    results: list[FactorStats]


def _slice(bars: list[Bar], day: date) -> list[Bar]:
    """Barres connues à la clôture du jour `day` (inclus)."""
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid].day <= day:
            lo = mid + 1
        else:
            hi = mid
    return bars[:lo]


def _forward_return(bars: list[Bar], day: date, h: int) -> Optional[float]:
    past = _slice(bars, day)
    i = len(past) - 1
    if i < 0 or past[-1].day != day or i + h >= len(bars):
        return None
    return bars[i + h].close / bars[i].close - 1


def run_backtest(provider: DataProvider, horizons: tuple[int, ...] = (5, 21), warmup: int = 260) -> BacktestReport:
    days = provider.trading_days()
    index_bars = provider.price_history(provider.index().ticker)
    history = {s.ticker: (provider.price_history(s.ticker), s.sector) for s in provider.universe()}

    results: list[FactorStats] = []
    composite: dict[int, FactorStats] = {}
    for h in horizons:
        stats = {f.key: FactorStats(f.key, f.name, h) for f in BACKTEST_FACTORS}
        comp = FactorStats("composite", "Composite recherche (cours)", h)
        for t_idx in range(warmup, len(days) - h, h):
            day = days[t_idx]
            inputs = {t: TickerInputs(_slice(bars, day), sector) for t, (bars, sector) in history.items()}
            readings = score_universe(inputs, _slice(index_bars, day), include_info=False)
            fwd = {t: _forward_return(bars, day, h) for t, (bars, _) in history.items()}
            tickers = [t for t in inputs if fwd[t] is not None]
            for f in BACKTEST_FACTORS:
                pairs = [(readings[t][f.key].score, fwd[t]) for t in tickers if readings[t][f.key].value is not None]
                ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if ic is not None:
                    stats[f.key].ics.append(ic)
            # Composite : moyenne pondérée des facteurs pertinents pour l'horizon.
            target = "court" if h <= 5 else "moyen"
            comp_scores = []
            for t in tickers:
                rs = [r for r in readings[t].values() if target in r.horizons and r.value is not None]
                w = sum(r.weight for r in rs)
                comp_scores.append((sum(r.score * r.weight for r in rs) / w if w else 0.0, fwd[t]))
            ic = spearman([p[0] for p in comp_scores], [p[1] for p in comp_scores])
            if ic is not None:
                comp.ics.append(ic)
        results += list(stats.values())
        composite[h] = comp
    results += list(composite.values())
    return BacktestReport(days[warmup], days[-1], len(history), results)


def render_backtest(report: BacktestReport, simulated: bool) -> str:
    out = [f"BACKTEST DES FACTEURS DE RECHERCHE — {report.start.strftime('%d/%m/%Y')} → "
           f"{report.end.strftime('%d/%m/%Y')}, {report.universe} titres",
           "  IC = corrélation de rang (Spearman) entre le score du facteur et le rendement futur ;",
           "  dates non chevauchantes ; |t| > 3 recommandé pour conclure (Harvey, Liu & Zhu, 2016).", ""]
    for h in sorted({r.horizon for r in report.results}):
        out.append(f"  Horizon {h} séances")
        out.append(f"    {'Facteur':<46} {'IC moyen':>9} {'t':>7} {'IC > 0':>8} {'dates':>6}")
        for r in (x for x in report.results if x.horizon == h):
            flag = "  ◀ significatif" if abs(r.t_stat) > 3 else ""
            out.append(f"    {r.name:<46} {r.mean_ic:>+9.3f} {r.t_stat:>+7.2f} {r.hit_rate:>8.0%} {r.n:>6}{flag}")
        out.append("")
    if simulated:
        out.append("  ⚠ Données SIMULÉES : les cours suivent une marche aléatoire (plus une tendance propre à")
        out.append("    chaque titre). Aucun facteur ne devrait y être significatif, hormis un momentum qui")
        out.append("    retrouverait la tendance injectée. Ces chiffres valident la mécanique du backtest")
        out.append("    (pas de biais d'anticipation), pas les facteurs : il faut de vraies données pour cela.")
    return "\n".join(out)
