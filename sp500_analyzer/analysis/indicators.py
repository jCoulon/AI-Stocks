"""Indicateurs techniques classiques (implémentation pure Python).

Chaque fonction renvoie une liste alignée sur l'entrée ; les premières valeurs
non calculables valent None.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from ..models import Bar

Values = list[Optional[float]]


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def sma(values: Sequence[float], n: int) -> Values:
    out: Values = [None] * len(values)
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= n:
            acc -= values[i - n]
        if i >= n - 1:
            out[i] = acc / n
    return out


def ema(values: Sequence[float], n: int) -> Values:
    out: Values = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: Sequence[float], n: int = 14) -> Values:
    """RSI de Wilder."""
    out: Values = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0)
        losses += max(-ch, 0)
    avg_g, avg_l = gains / n, losses / n

    def value() -> float:
        return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)

    out[n] = value()
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(ch, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-ch, 0)) / n
        out[i] = value()
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Values, Values, Values]:
    ef, es = ema(closes, fast), ema(closes, slow)
    line: Values = [f - s if f is not None and s is not None else None for f, s in zip(ef, es)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig_part = ema([v for v in line[start:] if v is not None], signal)
    sig: Values = [None] * start + sig_part
    hist: Values = [m - s if m is not None and s is not None else None for m, s in zip(line, sig)]
    return line, sig, hist


def bollinger(closes: Sequence[float], n: int = 20, k: float = 2.0) -> tuple[Values, Values, Values]:
    mid = sma(closes, n)
    up: Values = [None] * len(closes)
    lo: Values = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        sd = stdev(w)
        up[i] = mid[i] + k * sd
        lo[i] = mid[i] - k * sd
    return mid, up, lo


def atr(bars: Sequence[Bar], n: int = 14) -> Values:
    out: Values = [None] * len(bars)
    if len(bars) <= n:
        return out
    trs = [bars[0].high - bars[0].low]
    for i in range(1, len(bars)):
        pc = bars[i - 1].close
        trs.append(max(bars[i].high - bars[i].low, abs(bars[i].high - pc), abs(bars[i].low - pc)))
    prev = sum(trs[1:n + 1]) / n
    out[n] = prev
    for i in range(n + 1, len(bars)):
        prev = (prev * (n - 1) + trs[i]) / n
        out[i] = prev
    return out


def pct_returns(closes: Sequence[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))
