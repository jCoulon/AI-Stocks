"""Pilier macro-économique et régime de marché, modulé par la sensibilité du secteur."""

from __future__ import annotations

import math
from datetime import date

from ..models import PillarResult, Series, Signal
from ..universe import SECTOR_PROFILE
from .indicators import clip


def _value(series: Series, back: int = 0) -> float | None:
    if len(series) <= back:
        return None
    return series[-1 - back][1]


def _change(series: Series, back: int) -> float | None:
    a, b = _value(series), _value(series, back)
    return None if a is None or b is None else a - b


def macro_summary(macro: dict[str, Series]) -> dict[str, float]:
    """Chiffres clés pour l'affichage."""
    out: dict[str, float] = {}
    for key in ("us10y", "us2y", "fed_funds", "vix", "wti", "put_call", "cpi_yoy", "unemployment", "ism_pmi", "aaii_spread"):
        if macro.get(key):
            out[key] = macro[key][-1][1]
    if macro.get("us10y") and macro.get("us2y"):
        out["curve_10y_2y"] = macro["us10y"][-1][1] - macro["us2y"][-1][1]
    for key, back in (("us10y", 5), ("vix", 5), ("wti", 5)):
        ch = _change(macro.get(key, []), back)
        if ch is not None:
            out[f"{key}_chg_5d"] = ch
    return out


def analyze_macro(macro: dict[str, Series], sector: str, as_of: date) -> tuple[PillarResult, PillarResult]:
    prof = SECTOR_PROFILE.get(sector, SECTOR_PROFILE["Index"])
    short = PillarResult("macro", "court")
    medium = PillarResult("macro", "moyen")

    def add(p: PillarResult, name, value, score, weight, comment):
        if value is not None:
            p.signals.append(Signal(name, value, clip(score), weight, comment))

    # ------------------------------------------------ régime de marché (court)
    vix = _value(macro.get("vix", []))
    if vix is not None:
        add(short, "VIX", vix, math.tanh((20 - vix) / 6), 0.2,
            "stress élevé" if vix > 25 else "calme" if vix < 16 else "volatilité modérée")
    vix_ch = _change(macro.get("vix", []), 5)
    if vix_ch is not None:
        add(short, "Variation VIX 5j", vix_ch, -math.tanh(vix_ch / 3), 0.15,
            "la peur recule" if vix_ch < 0 else "la peur monte")
    pc = _value(macro.get("put_call", []))
    if pc is not None:
        add(short, "Put/Call ratio", pc, 0.6 * math.tanh((pc - 0.9) / 0.15), 0.1,
            "couverture élevée (contrarien haussier)" if pc > 1 else "complaisance (contrarien baissier)" if pc < 0.75
            else "positionnement équilibré")

    y10_5 = _change(macro.get("us10y", []), 5)
    if y10_5 is not None:
        add(short, "Taux 10 ans (5j, pb)", y10_5 * 100, prof["rates"] * -math.tanh(y10_5 / 0.12), 0.2,
            f"taux en {'baisse' if y10_5 < 0 else 'hausse'} — "
            + ("favorable" if prof["rates"] * -y10_5 > 0 else "défavorable") + " au secteur")
    wti = macro.get("wti", [])
    if len(wti) > 5:
        oil_5 = wti[-1][1] / wti[-6][1] - 1
        add(short, "Pétrole WTI (5j)", oil_5 * 100, prof["oil"] * math.tanh(oil_5 / 0.05), 0.15,
            f"pétrole {oil_5 * 100:+.1f}% — " + ("favorable" if prof["oil"] * oil_5 > 0 else "neutre/défavorable")
            + " au secteur")
    ff_ch = _change(macro.get("fed_funds", []), 5)
    if ff_ch is not None:
        add(short, "Décision Fed (5j)", ff_ch * 100, -math.tanh(ff_ch / 0.25), 0.2,
            "baisse de taux" if ff_ch < 0 else "hausse de taux" if ff_ch > 0 else "statu quo")

    # ---------------------------------------------------- économie (moyen)
    pmi = macro.get("ism_pmi", [])
    if pmi:
        lvl = pmi[-1][1]
        trend = _change(pmi, 3) or 0.0
        add(medium, "ISM manufacturier", lvl, prof["cyclical"] * math.tanh((lvl - 50) / 2 + trend / 1.5), 0.2,
            f"{'expansion' if lvl > 50 else 'contraction'}, tendance {'en amélioration' if trend > 0 else 'en dégradation'}")
    cpi_ch = _change(macro.get("cpi_yoy", []), 3)
    if cpi_ch is not None:
        add(medium, "Inflation (3 mois)", cpi_ch, -math.tanh(cpi_ch / 0.3), 0.15,
            "désinflation" if cpi_ch < 0 else "réaccélération de l'inflation")
    un_ch = _change(macro.get("unemployment", []), 3)
    if un_ch is not None:
        add(medium, "Chômage (3 mois)", un_ch, -abs(prof["cyclical"]) * math.tanh(un_ch / 0.3) - 0.2 * math.tanh(un_ch / 0.3), 0.15,
            "marché du travail qui se détend" if un_ch > 0 else "marché du travail solide")
    if macro.get("us10y") and macro.get("us2y"):
        spread = macro["us10y"][-1][1] - macro["us2y"][-1][1]
        steep = spread - (macro["us10y"][-21][1] - macro["us2y"][-21][1]) if len(macro["us10y"]) > 21 else 0.0
        add(medium, "Courbe 10a-2a", spread * 100,
            0.4 * math.tanh(spread / 0.5) + prof["curve"] * math.tanh(steep / 0.1), 0.1,
            f"{'positive' if spread > 0 else 'inversée'}, {'pentification' if steep > 0 else 'aplatissement'}")
    y10_20 = _change(macro.get("us10y", []), 20)
    if y10_20 is not None:
        add(medium, "Taux 10 ans (1 mois, pb)", y10_20 * 100, prof["rates"] * -math.tanh(y10_20 / 0.25), 0.15,
            f"{y10_20 * 100:+.0f} pb sur un mois")
    if len(wti) > 20:
        oil_20 = wti[-1][1] / wti[-21][1] - 1
        add(medium, "Pétrole WTI (1 mois)", oil_20 * 100, prof["oil"] * math.tanh(oil_20 / 0.1), 0.1,
            f"{oil_20 * 100:+.1f}% sur un mois")
    ff_60 = _change(macro.get("fed_funds", []), 90)
    if ff_60 is not None:
        add(medium, "Politique monétaire (3 mois)", ff_60 * 100, -math.tanh(ff_60 / 0.25), 0.1,
            "cycle d'assouplissement" if ff_60 < 0 else "resserrement" if ff_60 > 0 else "statu quo")
    aaii = _value(macro.get("aaii_spread", []))
    if aaii is not None:
        add(medium, "Sondage AAII (bull-bear)", aaii, -0.5 * math.tanh(aaii / 25), 0.05,
            "optimisme des particuliers (contrarien)" if aaii > 15 else "pessimisme des particuliers (contrarien)"
            if aaii < -10 else "sentiment particuliers équilibré")

    return short, medium
