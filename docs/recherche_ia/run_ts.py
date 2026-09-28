import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
from bisect import bisect_left
folder = ROOT/"research"/"daily" if len(sys.argv) > 1 else ROOT/"daily"
SMALL = ["IREN","CIFR","WULF","APLD","CORZ","SOUN","BBAI","AI","PATH","NBIS","CRWV","SMCI"]
leaders = ["NVDA"] + (["SMH"] if (folder/"SMH.csv").exists() else [])
panel = Panel(load_closes(folder, AI + leaders + ["SPX"]))
def ols(x, y):
    mx, my = mean(x), mean(y)
    b = sum((a-mx)*(c-my) for a, c in zip(x, y))/sum((a-mx)**2 for a in x)
    res = [c-my-b*(a-mx) for a, c in zip(x, y)]
    se = math.sqrt(sum(r*r for r in res)/(len(x)-2)/sum((a-mx)**2 for a in x))
    return b, b/se, len(x)
def basket(i):
    rs = [panel.ret(t, i, 1) for t in SMALL]
    rs = [r for r in rs if r is not None]
    return mean(rs) if len(rs) >= 4 else None
D0 = date(2023,1,1) if len(sys.argv) > 1 else date(2024,10,1)
for L in leaders:
    x, y = [], []
    for i, d in enumerate(panel.cal[:-1]):
        if not (D0 <= d <= date(2026,3,31)) or i == 0: continue
        a, b = panel.ret(L, i-1, 1), basket(i)   # veille du leader -> jour du panier
        if a is not None and b is not None: x.append(a); y.append(b)
    b, t, n = ols(x, y)
    print(f"T1 {L} veille -> panier petites IA : pente {b:+.3f} t {t:+.2f} n={n}")
    # contrôle : autocorrélation propre du panier
x, y = [], []
for i, d in enumerate(panel.cal[:-1]):
    if not (D0 <= d <= date(2026,3,31)) or i == 0: continue
    a, b = basket(i-1), basket(i)
    if a is not None and b is not None: x.append(a); y.append(b)
print("contrôle : panier veille -> panier jour : pente %+.3f t %+.2f n=%d" % ols(x, y))
