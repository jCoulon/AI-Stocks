import sys, json, glob; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
from bisect import bisect_left
tick = [Path(f).stem for f in glob.glob(str(ROOT/"events"/"*.json"))]
panel = Panel(load_closes(ROOT/"daily", tick + ["SPX"]))
rows = []
for t in tick:
    if t not in panel.s: continue
    for ds in json.load(open(ROOT/"events"/f"{t}.json"))["past_earnings"]:
        d = date.fromisoformat(ds); i = bisect_left(panel.cal, d)
        if i == 0 or i+22 >= len(panel.cal): continue
        j = i+1 if panel.cal[i] == d else i
        react = panel.ret(t, i-1, j-i+1)
        drift = panel.ret(t, j, 20); mkt = panel.ret("SPX", j, 20)
        if react is None or drift is None: continue
        rows.append((d, t, t in AI, react, drift - mkt))
def report(sel, label):
    x = [r[3] for r in sel]; y = [r[4] for r in sel]
    ic = spearman(x, y)
    up = [r[4] for r in sel if r[3] > 0]; dn = [r[4] for r in sel if r[3] <= 0]
    diff = mean(up) - mean(dn)
    se = math.sqrt(stdev(up)**2/len(up) + stdev(dn)**2/len(dn))
    print(f"{label:34} n={len(sel):3} IC {ic:+.3f}  hausse->{mean(up):+.1%} baisse->{mean(dn):+.1%} écart {diff:+.1%} t {diff/se:+.2f}")
disc = [r for r in rows if r[0] <= date(2026,3,31)]
report(disc, "E1 découverte, tous titres")
report([r for r in disc if r[2]], "E1 découverte, titres IA")
