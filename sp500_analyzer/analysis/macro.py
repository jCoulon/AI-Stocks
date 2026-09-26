"""Pilier macro-économique et régime de marché, modulé par la sensibilité du secteur."""

from __future__ import annotations

import math
import calendar
from datetime import date, timedelta

from ..models import Bar, PillarResult, Series, Signal
from ..universe import SECTOR_PROFILE
from .indicators import clip, mean, stdev


def _value(series: Series) -> float | None:
    return series[-1][1] if series else None


def _value_at(series: Series, day) -> float | None:
    """Dernière valeur publiée au plus tard le jour `day`."""
    out = None
    for d, v in series:
        if d > day:
            break
        out = v
    return out


def _months_back(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    m += 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def _is_monthly(series: Series) -> bool:
    gaps = [(series[i][0] - series[i - 1][0]).days for i in range(1, len(series))]
    return bool(gaps) and sorted(gaps)[len(gaps) // 2] >= 25


def _value_before(series: Series, days: int | None, months: int | None) -> float | None:
    last = series[-1][0]
    if months is not None:
        target = _months_back(last, months)
        if _is_monthly(series):
            # Série mensuelle : on compare des mois, quel que soit le jour de datation
            # (1er du mois ou fin de mois), pour couvrir exactement `months` mois.
            key = (target.year, target.month)
            candidates = [v for d, v in series if (d.year, d.month) <= key]
            return candidates[-1] if candidates else None
        return _value_at(series, target)
    if days is not None:
        return _value_at(series, last - timedelta(days=days))
    raise ValueError("_change : préciser days ou months")


def _change(series: Series, days: int | None = None, months: int | None = None) -> float | None:
    """Variation sur une durée calendaire (en jours ou en mois civils), quelle que soit la
    fréquence de la série (quotidienne, hebdomadaire, mensuelle datée au 1er ou en fin de mois)."""
    if not series:
        return None
    before = _value_before(series, days, months)
    return None if before is None else series[-1][1] - before


def _pct_change(series: Series, days: int) -> float | None:
    if not series:
        return None
    before = _value_before(series, days, None)
    return None if not before else series[-1][1] / before - 1


# Durées calendaires : 1 semaine de bourse et 1 mois (jours), 3 mois (mois civils).
WEEK, MONTH, QUARTER_MONTHS = 7, 28, 3


def macro_summary(macro: dict[str, Series]) -> dict[str, float]:
    """Chiffres clés pour l'affichage."""
    out: dict[str, float] = {}
    for key in ("us10y", "us2y", "fed_funds", "vix", "wti", "put_call", "cpi_yoy", "unemployment", "ism_pmi", "aaii_spread"):
        if macro.get(key):
            out[key] = macro[key][-1][1]
    if macro.get("us10y") and macro.get("us2y"):
        out["curve_10y_2y"] = macro["us10y"][-1][1] - macro["us2y"][-1][1]
    for key in ("us10y", "vix", "wti"):
        ch = _change(macro.get(key, []), WEEK)
        if ch is not None:
            out[f"{key}_chg_5d"] = ch
    return out


def variance_risk_premium(vix: Series, index_bars: list[Bar], window: int = 21) -> list[tuple[date, float]]:
    """Prime de risque de variance (Bollerslev, Tauchen & Zhou, 2009), en points de variance
    annualisée : VIX² (variance implicite, 30 jours) − variance réalisée de l'indice sur
    les `window` dernières séances. Série alignée sur les dates communes au VIX et à l'indice."""
    sq = [math.log(index_bars[i].close / index_bars[i - 1].close) ** 2 for i in range(1, len(index_bars))]
    pos = {b.day: i for i, b in enumerate(index_bars[1:])}
    out = []
    for d, v in vix:
        i = pos.get(d)
        if i is not None and i + 1 >= window:
            out.append((d, (v / 100) ** 2 - sum(sq[i + 1 - window:i + 1]) * 252 / window))
    return out


def vrp_zscore(vrp: list[tuple[date, float]]) -> float | None:
    """Prime actuelle en écarts-types de sa propre année écoulée (None si moins de 60 points)."""
    hist = [v for _, v in vrp[-252:]]
    if len(hist) < 60:
        return None
    sd = stdev(hist)
    return (hist[-1] - mean(hist)) / sd if sd else 0.0


def analyze_macro(
    macro: dict[str, Series], sector: str, as_of: date, vrp_z: float | None = None,
) -> tuple[PillarResult, PillarResult]:
    """`vrp_z` : prime de risque de variance standardisée (voir vrp_zscore), calculée une
    fois pour tous les secteurs ; None si l'indice ou le VIX sont indisponibles."""
    prof = SECTOR_PROFILE.get(sector, SECTOR_PROFILE["Index"])
    short = PillarResult("macro", "court")
    medium = PillarResult("macro", "moyen")

    def add(p: PillarResult, name, value, score, weight, comment):
        if value is not None:
            p.signals.append(Signal(name, value, clip(score), weight, comment))

    # ------------------------------------------------ régime de marché (court)
    vix = _value(macro.get("vix", []))
    if vix is not None:
        # Lecture de court terme (appétit pour le risque). À moyen terme, c'est la prime de
        # risque de variance, et non le niveau du VIX, qui porte l'information (voir plus bas).
        add(short, "VIX", vix, math.tanh((20 - vix) / 6), 0.2,
            "stress élevé" if vix > 25 else "calme" if vix < 16 else "volatilité modérée")
    vix_ch = _change(macro.get("vix", []), WEEK)
    if vix_ch is not None:
        add(short, "Variation VIX 5j", vix_ch, -math.tanh(vix_ch / 3), 0.15,
            "la peur recule" if vix_ch < 0 else "la peur monte")
    pc = _value(macro.get("put_call", []))
    if pc is not None:
        add(short, "Put/Call ratio", pc, 0.6 * math.tanh((pc - 0.9) / 0.15), 0.1,
            "couverture élevée (contrarien haussier)" if pc > 1 else "complaisance (contrarien baissier)" if pc < 0.75
            else "positionnement équilibré")

    y10_5 = _change(macro.get("us10y", []), WEEK)
    if y10_5 is not None:
        add(short, "Taux 10 ans (5j, pb)", y10_5 * 100, prof["rates"] * -math.tanh(y10_5 / 0.12), 0.2,
            f"taux en {'baisse' if y10_5 < 0 else 'hausse'} — "
            + ("favorable" if prof["rates"] * -y10_5 > 0 else "défavorable") + " au secteur")
    wti = macro.get("wti", [])
    oil_5 = _pct_change(wti, WEEK)
    if oil_5 is not None:
        add(short, "Pétrole WTI (5j)", oil_5 * 100, prof["oil"] * math.tanh(oil_5 / 0.05), 0.15,
            f"pétrole {oil_5 * 100:+.1f}% — " + ("favorable" if prof["oil"] * oil_5 > 0 else "neutre/défavorable")
            + " au secteur")
    ff_ch = _change(macro.get("fed_funds", []), WEEK)
    if ff_ch is not None:
        add(short, "Décision Fed (5j)", ff_ch * 100, -math.tanh(ff_ch / 0.25), 0.2,
            "baisse de taux" if ff_ch < 0 else "hausse de taux" if ff_ch > 0 else "statu quo")

    # ---------------------------------------------------- économie (moyen)
    pmi = macro.get("ism_pmi", [])
    if pmi:
        lvl = pmi[-1][1]
        trend = _change(pmi, months=QUARTER_MONTHS) or 0.0
        add(medium, "ISM manufacturier", lvl, prof["cyclical"] * math.tanh((lvl - 50) / 2 + trend / 1.5), 0.2,
            f"{'expansion' if lvl > 50 else 'contraction'}, tendance {'en amélioration' if trend > 0 else 'en dégradation'}")
    cpi_ch = _change(macro.get("cpi_yoy", []), months=QUARTER_MONTHS)
    if cpi_ch is not None:
        add(medium, "Inflation (3 mois)", cpi_ch, -math.tanh(cpi_ch / 0.3), 0.15,
            "désinflation" if cpi_ch < 0 else "réaccélération de l'inflation")
    un_ch = _change(macro.get("unemployment", []), months=QUARTER_MONTHS)
    if un_ch is not None:
        add(medium, "Chômage (3 mois)", un_ch, -abs(prof["cyclical"]) * math.tanh(un_ch / 0.3) - 0.2 * math.tanh(un_ch / 0.3), 0.15,
            "marché du travail qui se détend" if un_ch > 0 else "marché du travail solide")
    if macro.get("us10y") and macro.get("us2y"):
        spread = macro["us10y"][-1][1] - macro["us2y"][-1][1]
        month_ago = macro["us10y"][-1][0] - timedelta(days=MONTH)
        y10_m, y2_m = _value_at(macro["us10y"], month_ago), _value_at(macro["us2y"], month_ago)
        steep = spread - (y10_m - y2_m) if y10_m is not None and y2_m is not None else 0.0
        add(medium, "Courbe 10a-2a", spread * 100,
            0.4 * math.tanh(spread / 0.5) + prof["curve"] * math.tanh(steep / 0.1), 0.1,
            f"{'positive' if spread > 0 else 'inversée'}, {'pentification' if steep > 0 else 'aplatissement'}")
    y10_20 = _change(macro.get("us10y", []), MONTH)
    if y10_20 is not None:
        add(medium, "Taux 10 ans (1 mois, pb)", y10_20 * 100, prof["rates"] * -math.tanh(y10_20 / 0.25), 0.15,
            f"{y10_20 * 100:+.0f} pb sur un mois")
    oil_20 = _pct_change(wti, MONTH)
    if oil_20 is not None:
        add(medium, "Pétrole WTI (1 mois)", oil_20 * 100, prof["oil"] * math.tanh(oil_20 / 0.1), 0.1,
            f"{oil_20 * 100:+.1f}% sur un mois")
    ff_60 = _change(macro.get("fed_funds", []), months=QUARTER_MONTHS)
    if ff_60 is not None:
        add(medium, "Politique monétaire (3 mois)", ff_60 * 100, -math.tanh(ff_60 / 0.25), 0.1,
            "cycle d'assouplissement" if ff_60 < 0 else "resserrement" if ff_60 > 0 else "statu quo")
    # Prime de risque de variance : élevée => rendements du marché plus élevés, surtout à
    # l'horizon trimestriel (Bollerslev, Tauchen & Zhou, 2009). Standardisée sur un an.
    if vrp_z is not None:
        z = vrp_z
        add(medium, "Prime de risque de variance", z, math.tanh(z / 1.5), 0.15,
            f"{'élevée' if z > 0.5 else 'faible' if z < -0.5 else 'normale'} ({z:+.1f} écart-type sur 1 an) "
            "— Bollerslev, Tauchen & Zhou (2009)")
    aaii = _value(macro.get("aaii_spread", []))
    if aaii is not None:
        add(medium, "Sondage AAII (bull-bear)", aaii, -0.5 * math.tanh(aaii / 25), 0.05,
            "optimisme des particuliers (contrarien)" if aaii > 15 else "pessimisme des particuliers (contrarien)"
            if aaii < -10 else "sentiment particuliers équilibré")

    return short, medium
