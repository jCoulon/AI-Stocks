import sys, pickle; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
print("=== RÉSERVE — tests uniques ===")
# H-A : P5 sur 2026-04-01 → 2026-09-25
panel = Panel(load_closes(ROOT/"daily", AI + ["SPX"]))
def p5(p, t, i): return p.ret(t, i-5, 5)
m, tt, n = evaluate(panel, p5, date(2026,4,1), date(2026,9,25), h=5)
print(f"H-A retournement 1 sem : IC {m:+.3f} t {tt:+.2f} n={n}   (règle : t <= -1.65)")
# H-B / H-C : sur les scores décomposés, 2026-06-01 → 2026-09-25
rows = pickle.load(open(sys.argv[1], "rb"))
by_day = defaultdict(list)
for r in rows:
    if date(2026,6,1) <= r["day"] <= date(2026,9,25): by_day[r["day"]].append(r)
variants = {"outil": lambda r: r["short"], "H-B technique inversée": lambda r: r["short"] - 2*r.get("C:technique", 0),
            "H-C sans technique court": lambda r: r["short"] - r.get("C:technique", 0)}
ics = defaultdict(list)
for d, rs in sorted(by_day.items()):
    i = panel.idx[d]
    ys = [panel.ret(r["ticker"], i, 5) for r in rs]
    ok = [k for k, y in enumerate(ys) if y is not None]
    for name, f in variants.items():
        ics[name].append(spearman([f(rs[k]) for k in ok], [ys[k] for k in ok]))
for name in variants:
    m, tt, n = tstat(ics[name]); print(f"{name:26} IC {m:+.3f} t {tt:+.2f} n={n}")
for name in list(variants)[1:]:
    diff = [a-b for a, b in zip(ics[name], ics["outil"])]
    m, tt, n = tstat(diff); print(f"  différence {name} − outil : {m:+.3f} t {tt:+.2f}  (règle : > 0 et t >= 1.65)")
