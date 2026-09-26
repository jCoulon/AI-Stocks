"""Pilier technique : lecture des graphiques (tendance, momentum, volumes)."""

from __future__ import annotations

import math

from ..models import Bar, PillarResult, Signal
from .indicators import atr, bollinger, clip, closes_on_calendar, ema, macd, mean, pct_returns, rsi, sma, stdev


def _lg(r: float) -> float:
    """Rendement logarithmique : symétrique (+x % puis retour = 0), contrairement au
    rendement arithmétique (+50 % puis −33 %), qui biaise les scores vers la hausse."""
    return math.log1p(r)


def _last(values):
    return values[-1] if values else None


def analyze_technical(bars: list[Bar], index_bars: list[Bar] | None = None) -> tuple[PillarResult, PillarResult, dict]:
    """Renvoie (pilier court terme, pilier moyen terme, statistiques utiles)."""
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    rets = pct_returns(closes)
    c = closes[-1]
    vol_d = stdev(rets[-60:]) or 0.01

    short = PillarResult("technique", "court")
    medium = PillarResult("technique", "moyen")

    # Rendements sur N séances : mesurés sur le calendrier de l'indice (séances manquantes
    # du titre comblées par le dernier cours), pour comparer des périodes identiques.
    if index_bars:
        aligned = closes_on_calendar(bars, [b.day for b in index_bars])
        idx = [b.close for b in index_bars]
    else:
        aligned, idx = list(closes), None

    def ret_n(n: int) -> float | None:
        if len(aligned) <= n or aligned[-n - 1] is None or aligned[-1] is None:
            return None
        return aligned[-1] / aligned[-n - 1] - 1

    def rel_n(n: int) -> float | None:
        r = ret_n(n)
        if r is None or idx is None or len(idx) <= n:
            return None
        return (1 + r) / (idx[-1] / idx[-n - 1]) - 1

    # ---------------------------------------------------------- court terme
    r = _last(rsi(closes, 14))
    if r is not None:
        momentum = clip((r - 50) / 20)
        reversal = -(r - 70) / 10 if r > 70 else (30 - r) / 10 if r < 30 else 0.0
        comment = ("surachat, risque de repli" if r > 70 else "survente, rebond possible" if r < 30
                   else "momentum positif" if r > 55 else "momentum négatif" if r < 45 else "neutre")
        short.signals.append(Signal("RSI 14", r, clip(0.6 * momentum + reversal), 0.2, comment))

    e20 = _last(ema(closes, 20))
    if e20:
        gap = c / e20 - 1
        short.signals.append(Signal("Cours vs EMA20", gap * 100, math.tanh(_lg(gap) / (2 * vol_d)), 0.2,
                                    f"{'au-dessus' if gap >= 0 else 'en dessous'} de la moyenne 20 j"))

    _, _, hist = macd(closes)
    a = _last(atr(bars, 14)) or c * vol_d
    if hist[-1] is not None and hist[-2] is not None:
        h, slope = hist[-1], hist[-1] - hist[-2]
        score = clip(0.7 * math.tanh(h / (0.25 * a)) + 0.3 * math.tanh(slope / (0.05 * a)))
        short.signals.append(Signal("MACD histogramme", h, score, 0.2,
                                    f"{'haussier' if h > 0 else 'baissier'}, {'accélère' if slope * h > 0 else 'ralentit'}"))

    r5 = ret_n(5)
    if r5 is not None:
        short.signals.append(Signal("Perf. 5 séances", r5 * 100, 0.8 * math.tanh(_lg(r5) / (vol_d * math.sqrt(5))), 0.15,
                                    f"{r5 * 100:+.1f}% sur la semaine"))

    mid, up, lo = bollinger(closes)
    if up[-1] is not None and up[-1] != lo[-1]:
        pb = (c - lo[-1]) / (up[-1] - lo[-1])
        # Continu : +0,3 en haut de bande, puis bascule progressive vers -0,4 (sur-extension)
        # sur 0,2 de %B au-delà ; symétrique en bas de bande.
        if pb > 1:
            score = 0.3 - 0.7 * min(1.0, (pb - 1) / 0.2)
        elif pb < 0:
            score = -0.3 + 0.7 * min(1.0, -pb / 0.2)
        else:
            score = (pb - 0.5) * 0.6
        short.signals.append(Signal("Bollinger %B", pb, score, 0.1,
                                    "hors bande haute (extension)" if pb > 1 else "hors bande basse" if pb < 0
                                    else "dans les bandes"))

    if len(volumes) >= 55 and r5 is not None:
        vr = mean(volumes[-5:]) / mean(volumes[-55:-5])
        # Sens du mouvement lissé (un rendement quasi nul ne donne pas un signe franc)
        # et intensité nulle en dessous de x1,1 puis croissante : score continu.
        direction = math.tanh(_lg(r5) / (vol_d * math.sqrt(5) * 0.5))
        score = direction * clip((vr - 1.1) / 0.7, 0.0, 1.0)
        short.signals.append(Signal("Volume 5j / 50j", vr, score, 0.1,
                                    "volumes confirment le mouvement" if vr > 1.3 else "volumes normaux"))

    rel = rel_n(5)
    if rel is not None:
        short.signals.append(Signal("Force relative 5j vs S&P", rel * 100, math.tanh(_lg(rel) / (vol_d * 2)), 0.05,
                                    "surperforme l'indice" if rel > 0 else "sous-performe l'indice"))

    # ---------------------------------------------------------- moyen terme
    s50, s200 = sma(closes, 50), sma(closes, 200)
    if s200[-1] and s50[-1]:
        cross = s50[-1] / s200[-1] - 1
        medium.signals.append(Signal("SMA50 vs SMA200", cross * 100, math.tanh(_lg(cross) / 0.03), 0.25,
                                     "structure haussière (golden cross)" if cross > 0 else "structure baissière (death cross)"))
        d200 = c / s200[-1] - 1
        medium.signals.append(Signal("Cours vs SMA200", d200 * 100, math.tanh(_lg(d200) / 0.08), 0.2,
                                     f"{d200 * 100:+.1f}% vs moyenne 200 j"))
    r63 = ret_n(63)
    if r63 is not None:
        medium.signals.append(Signal("Momentum 3 mois", r63 * 100, math.tanh(_lg(r63) / (vol_d * math.sqrt(63))), 0.2,
                                     f"{r63 * 100:+.1f}% sur 3 mois"))
    if s50[-1] and s50[-21]:
        slope = s50[-1] / s50[-21] - 1
        medium.signals.append(Signal("Pente SMA50 (20j)", slope * 100, math.tanh(slope / 0.02), 0.15,
                                     "tendance intermédiaire " + ("montante" if slope > 0 else "descendante")))
    if len(rets) >= 120:
        vr = stdev(rets[-20:]) / (stdev(rets[-120:]) or 1)
        score = clip(-(vr - 1) * 0.8, -0.4, 0.2)  # continu : -0,4 dès x1,5, +0,2 sous x0,75
        medium.signals.append(Signal("Régime de volatilité", vr, score, 0.1,
                                     "volatilité en hausse" if vr > 1.5 else "volatilité contenue" if vr < 0.8 else "volatilité normale"))
    rel = rel_n(63)
    if rel is not None:
        medium.signals.append(Signal("Force relative 3m vs S&P", rel * 100, math.tanh(_lg(rel) / 0.08), 0.1,
                                     "surperforme l'indice" if rel > 0 else "sous-performe l'indice"))

    stats = {
        "atr": a,
        "daily_vol": vol_d,
        # None (et non NaN) quand l'historique est trop court : NaN n'est pas du JSON valide.
        "rsi": r,
        "sma50": s50[-1],
        "sma200": s200[-1],
    }
    return short, medium, stats
