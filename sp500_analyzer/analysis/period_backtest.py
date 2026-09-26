"""Backtest de l'outil complet sur une période (ex. septembre), sans biais d'anticipation.

Pour chaque séance de signal (la veille de la période, puis chaque séance de la période),
toute l'équipe d'agents est relancée sur une vue point-in-time des données
(PointInTimeProvider) : cours, news, messages et chiffres macro postérieurs sont invisibles.
L'avis court terme de chaque titre est ensuite confronté aux cours réalisés h séances plus
tard, à condition que la fenêtre reste dans la période.

Mesures, pour chaque horizon h :
- IC : corrélation de rang entre scores et rendements futurs le même jour (qualité du
  classement relatif), moyenne sur les séances de signal ;
- taux de réussite directionnel : part des avis haussiers suivis d'une hausse et des avis
  baissiers suivis d'une baisse (avis « Neutre » exclus), en absolu et relatif au S&P 500 ;
- écart haussiers − baissiers : rendement moyen des titres jugés haussiers moins celui des
  titres jugés baissiers.

Mise en garde : une période d'un mois ne compte qu'une vingtaine de séances, et les titres
d'un même jour évoluent ensemble (facteur de marché). Les résultats sont descriptifs ; ils ne
permettent pas de conclure statistiquement au pouvoir prédictif de l'outil.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from ..orchestrator import Orchestrator
from ..providers.base import DataProvider
from ..providers.pointintime import PointInTimeProvider
from .backtest import spearman
from .indicators import closes_on_calendar, mean

BULLISH, BEARISH = 0.12, -0.12  # seuils des libellés « Plutôt haussier » / « Plutôt baissier »


@dataclass
class Call:
    day: date
    ticker: str
    label: str
    score: float
    confidence: float
    fwd: dict[int, float] = field(default_factory=dict)  # rendement sur h séances
    excess: dict[int, float] = field(default_factory=dict)  # rendement - rendement du S&P 500


@dataclass
class HorizonStats:
    horizon: int
    dates: int
    mean_ic: Optional[float]
    share_ic_positive: Optional[float]
    directional_calls: int
    hit_rate: Optional[float]
    hit_rate_vs_index: Optional[float]
    bull_mean: Optional[float]
    bear_mean: Optional[float]
    #: part des titres en hausse sur l'horizon (réussite d'un avis « toujours haussier »)
    base_rate_up: Optional[float] = None
    #: statistique t de l'IC moyen, calculée sur des dates espacées de h séances (fenêtres
    #: disjointes) pour ne pas surestimer la significativité
    ic_t: Optional[float] = None
    independent_dates: int = 0

    @property
    def spread(self) -> Optional[float]:
        if self.bull_mean is None or self.bear_mean is None:
            return None
        return self.bull_mean - self.bear_mean


@dataclass
class MonthStats:
    month: str  # AAAA-MM
    dates: int
    mean_ic: Optional[float]
    bull_excess: Optional[float]  # surperformance moyenne vs S&P des avis haussiers
    bear_excess: Optional[float]
    index_return: float


@dataclass
class StrategyStats:
    """Panier équipondéré des titres jugés haussiers, renouvelé toutes les h séances."""

    horizon: int
    periods: int
    strategy: float  # rendement cumulé
    equal_weight: float  # univers équipondéré (comparateur équitable)
    index: float
    beat_equal_weight_share: float  # part des périodes où le panier bat l'univers équipondéré
    invested_share: float  # part des périodes avec au moins un titre haussier


@dataclass
class PeriodReport:
    start: date
    end: date
    simulated: bool
    signal_days: list[date]
    calls: list[Call]
    stats: list[HorizonStats]
    index_return: float
    #: (titre, avis, score, confiance, rendement période, rendement vs S&P) pour le 1er avis
    first_calls: list[tuple[str, str, float, float, float, float]]
    months: list[MonthStats] = field(default_factory=list)
    strategy: Optional[StrategyStats] = None


def _outcome_index(calendar: list[date], day: date, h: int, end: date) -> Optional[int]:
    i = calendar.index(day)
    j = i + h
    return j if j < len(calendar) and calendar[j] <= end else None


def run_period_backtest(
    base: DataProvider,
    start: date,
    end: date,
    horizons: tuple[int, ...] = (1, 5),
    progress: Optional[Callable[[date], None]] = None,
) -> PeriodReport:
    full_calendar = base.trading_days()
    period = [d for d in full_calendar if start <= d <= end]
    if len(period) < 2:
        raise ValueError(f"Pas assez de séances entre {start} et {end} dans les données")
    before = [d for d in full_calendar if d < start]
    signal_days = ([before[-1]] if before else []) + period[:-1]
    calendar = [d for d in full_calendar if d <= end]

    index_ticker = base.index().ticker
    index_close = dict(zip(calendar, closes_on_calendar(base.price_history(index_ticker), calendar)))
    closes = {s.ticker: dict(zip(calendar, closes_on_calendar(base.price_history(s.ticker), calendar)))
              for s in base.universe()}

    calls: list[Call] = []
    for day in signal_days:
        if progress:
            progress(day)
        report = Orchestrator(PointInTimeProvider(base, day)).run()
        for t in report.tickers:
            call = Call(day, t.security.ticker, t.short.label, t.short.score, t.short.confidence)
            for h in horizons:
                j = _outcome_index(calendar, day, h, end)
                c0, c1 = closes[call.ticker].get(day), closes[call.ticker].get(calendar[j]) if j else None
                if j is None or not c0 or not c1:
                    continue
                r = c1 / c0 - 1
                call.fwd[h] = r
                call.excess[h] = r - (index_close[calendar[j]] / index_close[day] - 1)
            calls.append(call)

    stats = []
    for h in horizons:
        by_day: dict[date, list[Call]] = {}
        for c in calls:
            if h in c.fwd:
                by_day.setdefault(c.day, []).append(c)
        ic_by_day = {d: ic for d, cs in by_day.items()
                     if (ic := spearman([c.score for c in cs], [c.fwd[h] for c in cs])) is not None}
        ics = list(ic_by_day.values())
        # Fenêtres disjointes : une date de signal sur h.
        indep = [ic_by_day[d] for d in signal_days[::h] if d in ic_by_day]
        ic_t = None
        if len(indep) > 2:
            sd = (sum((x - mean(indep)) ** 2 for x in indep) / (len(indep) - 1)) ** 0.5
            ic_t = mean(indep) / (sd / len(indep) ** 0.5) if sd > 0 else None
        directional = [c for cs in by_day.values() for c in cs if c.score >= BULLISH or c.score <= BEARISH]
        bulls = [c.fwd[h] for c in directional if c.score >= BULLISH]
        bears = [c.fwd[h] for c in directional if c.score <= BEARISH]
        stats.append(HorizonStats(
            horizon=h,
            dates=len(by_day),
            mean_ic=mean(ics) if ics else None,
            share_ic_positive=sum(ic > 0 for ic in ics) / len(ics) if ics else None,
            directional_calls=len(directional),
            hit_rate=(sum((c.fwd[h] > 0) == (c.score > 0) for c in directional) / len(directional)
                      if directional else None),
            hit_rate_vs_index=(sum((c.excess[h] > 0) == (c.score > 0) for c in directional) / len(directional)
                               if directional else None),
            bull_mean=mean(bulls) if bulls else None,
            bear_mean=mean(bears) if bears else None,
            base_rate_up=(sum(c.fwd[h] > 0 for cs in by_day.values() for c in cs)
                          / sum(len(cs) for cs in by_day.values()) if by_day else None),
            ic_t=ic_t,
            independent_dates=len(indep),
        ))

    first_day = signal_days[0]
    idx_ret = index_close[calendar[-1]] / index_close[first_day] - 1
    first_calls = []
    for c in (c for c in calls if c.day == first_day):
        c0, c1 = closes[c.ticker].get(first_day), closes[c.ticker].get(calendar[-1])
        if c0 and c1:
            r = c1 / c0 - 1
            first_calls.append((c.ticker, c.label, c.score, c.confidence, r, r - idx_ret))
    first_calls.sort(key=lambda x: -x[2])

    months = _monthly(calls, signal_days, calendar, index_close, horizons)
    strategy = _strategy(calls, signal_days, calendar, index_close, horizons, end)

    from ..providers.mock import MockDataProvider
    return PeriodReport(start, end, isinstance(base, MockDataProvider), signal_days, calls, stats,
                        idx_ret, first_calls, months, strategy)


def _ref_horizon(horizons: tuple[int, ...]) -> int:
    return 5 if 5 in horizons else max(horizons)


def _monthly(calls, signal_days, calendar, index_close, horizons) -> list[MonthStats]:
    h = _ref_horizon(horizons)
    out = []
    # L'avis de la veille de la période est rattaché au premier mois de la période.
    first_month = signal_days[1].strftime("%Y-%m") if len(signal_days) > 1 else signal_days[0].strftime("%Y-%m")
    month_of = {d: max(d.strftime("%Y-%m"), first_month) for d in signal_days}
    for month in sorted(set(month_of.values())):
        days = [d for d in signal_days if month_of[d] == month]
        cs = [c for c in calls if c.day in set(days) and h in c.fwd]
        by_day: dict[date, list[Call]] = {}
        for c in cs:
            by_day.setdefault(c.day, []).append(c)
        ics = [ic for g in by_day.values() if (ic := spearman([c.score for c in g], [c.fwd[h] for c in g])) is not None]
        bulls = [c.excess[h] for c in cs if c.score >= BULLISH]
        bears = [c.excess[h] for c in cs if c.score <= BEARISH]
        month_days = [d for d in calendar if d.strftime("%Y-%m") == month]
        prev = [d for d in calendar if d < month_days[0]]  # performance du S&P sur le mois civil
        base_day = prev[-1] if prev else month_days[0]
        out.append(MonthStats(month, len(by_day), mean(ics) if ics else None,
                              mean(bulls) if bulls else None, mean(bears) if bears else None,
                              index_close[month_days[-1]] / index_close[base_day] - 1))
    return out


def _strategy(calls, signal_days, calendar, index_close, horizons, end) -> Optional[StrategyStats]:
    h = _ref_horizon(horizons)
    by_day: dict[date, list[Call]] = {}
    for c in calls:
        if h in c.fwd:
            by_day.setdefault(c.day, []).append(c)
    windows = [d for d in signal_days[::h] if d in by_day]
    if not windows:
        return None
    strat = ew = idx = 1.0
    beat = invested = 0
    for d in windows:
        cs = by_day[d]
        universe = mean([c.fwd[h] for c in cs])
        bulls = [c.fwd[h] for c in cs if c.score >= BULLISH]
        r = mean(bulls) if bulls else 0.0  # aucun avis haussier : panier en liquidités
        invested += bool(bulls)
        beat += r > universe
        j = _outcome_index(calendar, d, h, end)
        strat *= 1 + r
        ew *= 1 + universe
        idx *= index_close[calendar[j]] / index_close[d]
    n = len(windows)
    return StrategyStats(h, n, strat - 1, ew - 1, idx - 1, beat / n, invested / n)


def _pct(v: Optional[float], signed: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v:+.1%}" if signed else f"{v:.0%}"


def render_period_backtest(r: PeriodReport) -> str:
    fmt = "%d/%m/%Y"
    out = [f"BACKTEST DE L'OUTIL — période du {r.start.strftime(fmt)} au {r.end.strftime(fmt)}",
           ("⚠ Données SIMULÉES : ce backtest valide la mécanique, pas la qualité des avis."
            if r.simulated else "Cours réels."),
           *(["  (Dans les données simulées, news et messages sociaux ne couvrent que les dernières semaines :"
              " sur le reste de la période, seuls les cours et la macro alimentent l'outil.)"]
             if r.simulated and len(r.signal_days) > 40 else []),
           f"  {len(r.signal_days)} séances de signal (outil complet relancé à chaque clôture, sans donnée future) ;"
           f" S&P 500 sur la période : {r.index_return:+.2%}", ""]

    out.append(f"  {'Horizon':<12} {'séances':>7} {'IC moyen':>9} {'t (IC)':>7} {'IC > 0':>7} {'avis tranchés':>14}"
               f" {'réussite':>9} {'(base)':>7} {'vs S&P':>7} {'haussiers':>10} {'baissiers':>10} {'écart':>7}")
    for s in r.stats:
        out.append(
            f"  {str(s.horizon) + ' séance' + ('s' if s.horizon > 1 else ''):<12} {s.dates:>7} "
            f"{('%+.3f' % s.mean_ic) if s.mean_ic is not None else '—':>9} "
            f"{('%+.2f' % s.ic_t) if s.ic_t is not None else '—':>7} {_pct(s.share_ic_positive, False):>7} "
            f"{s.directional_calls:>14} {_pct(s.hit_rate, False):>9} {_pct(s.base_rate_up, False):>7} "
            f"{_pct(s.hit_rate_vs_index, False):>7} "
            f"{_pct(s.bull_mean):>10} {_pct(s.bear_mean):>10} {_pct(s.spread):>7}")
    out += ["",
            "  IC : corrélation de rang entre scores et rendements futurs (0 = aucun pouvoir de classement).",
            "  t (IC) : significativité de l'IC sur des fenêtres disjointes ; |t| > 2 est un indice, |t| > 3 une",
            "  preuve raisonnable (Harvey, Liu & Zhu, 2016).",
            "  Réussite : avis haussiers suivis d'une hausse et baissiers suivis d'une baisse (« Neutre » exclus) ;",
            "  (base) : part des titres en hausse — la réussite qu'aurait un avis « toujours haussier » ;",
            "  une réussite en absolu n'a de valeur que si elle dépasse ce taux de base.",
            "  « vs S&P » : même mesure sur la performance relative à l'indice (taux de base ≈ 50 %).",
            "  Haussiers / baissiers : rendement moyen des titres jugés haussiers / baissiers ; écart = différence.", ""]

    if r.strategy:
        st = r.strategy
        out += [f"  STRATÉGIE : panier équipondéré des titres jugés haussiers, renouvelé toutes les {st.horizon} séances"
                f" ({st.periods} périodes)",
                f"    Stratégie {st.strategy:+.2%}   |   univers équipondéré {st.equal_weight:+.2%}   |   S&P 500 {st.index:+.2%}",
                f"    Bat l'univers équipondéré sur {st.beat_equal_weight_share:.0%} des périodes ;"
                f" investie {st.invested_share:.0%} du temps (sinon en liquidités).",
                "    Hors frais de transaction ; le comparateur équitable est l'univers équipondéré.", ""]

    if len(r.months) > 1:
        h = r.strategy.horizon if r.strategy else 5
        out.append(f"  MOIS PAR MOIS (avis à {h} séances)")
        out.append(f"  {'Mois':<8} {'séances':>7} {'IC moyen':>9} {'haussiers vs S&P':>17} {'baissiers vs S&P':>17} {'S&P 500':>8}")
        for m in r.months:
            out.append(f"  {m.month:<8} {m.dates:>7} {('%+.3f' % m.mean_ic) if m.mean_ic is not None else '—':>9} "
                       f"{_pct(m.bull_excess):>17} {_pct(m.bear_excess):>17} {m.index_return:>+8.1%}")
        out.append("")

    first = r.signal_days[0].strftime(fmt)
    out.append(f"  AVIS DU {first} ET PERFORMANCE JUSQU'AU {r.end.strftime(fmt)}")
    out.append(f"  {'Titre':<6} {'Avis court terme':<17} {'score':>6} {'conf.':>6} {'perf.':>8} {'vs S&P':>8}  résultat")
    for ticker, label, score, conf, ret, exc in r.first_calls:
        if score >= BULLISH:
            verdict = "✓" if exc > 0 else "✗"
        elif score <= BEARISH:
            verdict = "✓" if exc < 0 else "✗"
        else:
            verdict = "·"
        out.append(f"  {ticker:<6} {label:<17} {score:>+6.2f} {conf:>6.0%} {ret:>+8.1%} {exc:>+8.1%}  {verdict}")
    bulls = [x for x in r.first_calls if x[2] >= BULLISH]
    bears = [x for x in r.first_calls if x[2] <= BEARISH]
    if bulls or bears:
        out.append("")
        if bulls:
            out.append(f"  Panier « haussiers » ({len(bulls)} titres) : {mean([x[4] for x in bulls]):+.2%} "
                       f"(vs S&P {mean([x[5] for x in bulls]):+.2%})")
        if bears:
            out.append(f"  Panier « baissiers » ({len(bears)} titres) : {mean([x[4] for x in bears]):+.2%} "
                       f"(vs S&P {mean([x[5] for x in bears]):+.2%})")
    n_dates = len(r.signal_days)
    warning = ([f"  ⚠ {n_dates} séances et des titres qui évoluent ensemble : résultats descriptifs, sans valeur",
                "    statistique (il faudrait plusieurs années pour distinguer un pouvoir prédictif du hasard)."]
               if n_dates < 120 else
               [f"  ⚠ {n_dates} séances : se fier à la statistique t (fenêtres disjointes), pas aux pourcentages bruts ;",
                "    une seule année reste courte pour conclure, et les régimes de marché changent."])
    out += [""] + warning + [
            "  ✓ / ✗ : avis confirmé / démenti par la performance relative au S&P 500 ; · : avis neutre."]
    return "\n".join(out)
