"""Règle d'entrée (fixée avant le test) : cours à ≤ 1 ATR au-dessus du support le plus proche
ET (résistance − cours) / (cours − (support − 0,5 ATR)) ≥ 2. Variante : + tendance (cours > MM200).
Mesure : rendement 5 et 21 séances des titres « en zone » moins la moyenne des autres, par date."""
import sys, math
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from statistics import mean, stdev
from sp500_analyzer.providers.csv_prices import CsvPriceProvider
from sp500_analyzer.analysis.stock import key_levels
from sp500_analyzer.analysis.indicators import atr, sma
p = CsvPriceProvider(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "daily"), universe="tout")
H = {s.ticker: p.price_history(s.ticker) for s in p.universe()}
cal = sorted({b.day for h in H.values() for b in h})
idx = {t: {b.day: i for i, b in enumerate(h)} for t, h in H.items()}
def state(t, d):
    h = H[t]; i = idx[t].get(d)
    if i is None or i < 252: return None
    bars = h[:i+1]; c = [b.close for b in bars]
    s50, s200 = sma(c, 50)[-1], sma(c, 200)[-1]; a = atr(bars)[-1]
    lv = key_levels(bars, s50, s200); price = c[-1]
    below = [l.price for l in lv if l.price < price]; above = [l.price for l in lv if l.price > price]
    if not below or not above or not a: return None
    S, R = max(below), min(above)
    stop = S - 0.5 * a
    rr = (R - price) / (price - stop)
    on = (price - S) <= a
    return on, rr, price > s200
def fwd(t, d, h):
    i = idx[t].get(d); bars = H[t]
    return bars[i+h].close / bars[i].close - 1 if i is not None and i + h < len(bars) else None
res = {k: {5: [], 21: []} for k in ("support", "zone", "zone+tendance")}
counts = {k: 0 for k in res}
for d in cal[260::5]:
    st = {t: state(t, d) for t in H}
    for h in (5, 21):
        r = {t: fwd(t, d, h) for t in H if st[t] is not None}
        r = {t: v for t, v in r.items() if v is not None}
        if len(r) < 20: continue
        for k, cond in (("support", lambda s: s[0]), ("zone", lambda s: s[0] and s[1] >= 2),
                        ("zone+tendance", lambda s: s[0] and s[1] >= 2 and s[2])):
            ins = [v for t, v in r.items() if cond(st[t])]; outs = [v for t, v in r.items() if not cond(st[t])]
            if ins and outs:
                res[k][h].append(mean(ins) - mean(outs))
                if h == 5: counts[k] += len(ins)
for k in res:
    for h in (5, 21):
        xs = res[k][h]
        # dates espacées de 5 séances : fenêtres de 21 séances chevauchantes -> t corrigé (÷ sqrt(21/5))
        t = mean(xs) / stdev(xs) * math.sqrt(len(xs)) / (math.sqrt(21 / 5) if h == 21 else 1)
        print(f"{k:15} h={h:2} écart moyen vs autres {mean(xs):+.2%}  t {t:+.2f}  dates {len(xs)}  cas {counts[k]}")
