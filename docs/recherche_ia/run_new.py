import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
R = ROOT/"research"
panel = Panel(load_closes(R/"daily", AI + ["SPX", "SMH", "BTC-USD"]), calendar_ticker="SPX")
def series(folder, t, col, den=None):
    p = folder/f"{t}.csv"
    if not p.exists(): return {}
    with open(p) as f:
        out = {}
        for r in csv.DictReader(f):
            try:
                out[date.fromisoformat(r["Date"])] = float(r[col])/float(r[den]) if den else float(r[col])
            except (ValueError, ZeroDivisionError): pass
        return out
SVR = {t: series(R/"shortvol", t, "ShortVolume", "TotalVolume") for t in AI}
BAD_WIKI = {"CIFR", "APLD", "BBAI"}
WIKI = {t: series(R/"wiki", t, "Views") for t in AI if t not in BAD_WIKI}
def avg(m, d_list):
    xs = [m[d] for d in d_list if d in m]
    return mean(xs) if len(xs) >= max(3, len(d_list)//2) else None
def s1(p, t, i):
    return avg(SVR[t], p.cal[max(0,i-4):i+1])
def s2(p, t, i):
    a, b = avg(SVR[t], p.cal[max(0,i-4):i+1]), avg(SVR[t], p.cal[max(0,i-59):i+1])
    return None if a is None or b is None else a - b
def w1(p, t, i):
    if t not in WIKI: return None
    d = p.cal[i]; m = WIKI[t]
    a = [m[d - timedelta(days=k)] for k in range(1, 8) if d - timedelta(days=k) in m]   # vues publiées jusqu'à la veille
    b = [m[d - timedelta(days=k)] for k in range(1, 64) if d - timedelta(days=k) in m]
    if len(a) < 5 or len(b) < 40: return None
    return math.log((mean(a)+1)/(mean(b)+1))
def p5(p, t, i): return p.ret(t, i-5, 5)
disc = (date(2023,1,1), date(2026,3,31))
print("univers IA avec cours 5 ans :", sum(1 for t in AI if t in panel.s))
for name, f in [("P5 retournement 1 sem (-)", p5), ("S1 part à découvert 5j (-)", s1),
                ("S2 part à découvert anormale (-)", s2), ("W1 Wikipédia anormal (+)", w1)]:
    for h in (1, 5):
        m, tt, n = evaluate(panel, f, *disc, h=h, step=5)
        print(f"{name:34} h={h} découverte IC {m:+.3f} t {None if tt is None else round(tt,2):>6} n={n}")
