"""Moteur de test des signaux candidats (pré-enregistrés) sur l'univers IA."""
import csv, math, sys, json
from datetime import date, timedelta, datetime
from pathlib import Path
from statistics import mean, stdev
from collections import defaultdict
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]) + "")
from sp500_analyzer.universe import AI_THEME

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[2]) + "/data")
AI = sorted(AI_THEME)

def load_closes(folder, tickers):
    out = {}
    for t in tickers:
        p = folder / f"{t}.csv"
        if not p.exists(): continue
        with open(p) as f:
            out[t] = {date.fromisoformat(r["Date"]): float(r["Close"]) for r in csv.DictReader(f) if r["Close"]}
    return out

def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0]*len(xs)
    i = 0
    while i < len(order):
        j = i
        while j+1 < len(order) and xs[order[j+1]] == xs[order[i]]: j += 1
        for k in range(i, j+1): r[order[k]] = (i+j)/2
        i = j+1
    return r

def spearman(a, b):
    if len(a) < 5: return None
    ra, rb = rank(a), rank(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x-ma)*(y-mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x-ma)**2 for x in ra)*sum((y-mb)**2 for y in rb))
    return num/den if den else None

def tstat(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 3: return (mean(xs) if xs else None), None, len(xs)
    s = stdev(xs)
    return mean(xs), (mean(xs)/s*math.sqrt(len(xs)) if s else None), len(xs)

class Panel:
    def __init__(self, closes, calendar_ticker="NVDA"):
        self.c = closes
        self.cal = sorted(closes[calendar_ticker])
        self.idx = {d: i for i, d in enumerate(self.cal)}
        # séries alignées sur le calendrier (None si absent)
        self.s = {t: [v.get(d) for d in self.cal] for t, v in closes.items()}

    def ret(self, t, i, h):
        """rendement de la clôture i à i+h"""
        s = self.s[t]
        if i < 0 or i+h >= len(s) or s[i] is None or s[i+h] is None: return None
        return s[i+h]/s[i]-1

    def hist(self, t, i, n):
        s = self.s[t][max(0, i-n+1):i+1]
        return [x for x in s if x is not None]

def evaluate(panel, signal, start, end, h=5, step=5, tickers=AI, min_hist=60):
    """signal(panel, t, i) -> float|None ; IC transversal par date, dates espacées de step."""
    days = [i for i, d in enumerate(panel.cal) if start <= d <= end]
    ics = []
    for i in days[::step]:
        xs, ys = [], []
        for t in tickers:
            if t not in panel.s or len(panel.hist(t, i, min_hist)) < min_hist: continue
            x = signal(panel, t, i)
            y = panel.ret(t, i, h)
            if x is None or y is None or (isinstance(x, float) and math.isnan(x)): continue
            xs.append(x); ys.append(y)
        ics.append(spearman(xs, ys))
    return tstat(ics)

# ---- signaux de cours
def p1_rev1m(p, t, i): return p.ret(t, i-21, 21)
def p2_mom12_1(p, t, i):
    return p.ret(t, i-252, 231) if i >= 252 else None
def p3_52wh(p, t, i):
    h = p.hist(t, i, 252)
    return h[-1]/max(h) if len(h) >= 120 else None
def p4_max(p, t, i):
    h = p.hist(t, i, 22)
    return max(h[k]/h[k-1]-1 for k in range(1, len(h))) if len(h) >= 15 else None
def p5_rev1w(p, t, i): return p.ret(t, i-5, 5)
