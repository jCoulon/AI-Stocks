import sys, pickle; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
rows = pickle.load(open(sys.argv[1], "rb"))
panel = Panel(load_closes(ROOT/"daily", AI + ["SPX"]))
end = date.fromisoformat(sys.argv[2]); start = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date(2026,1,1)
keys = sorted({k for r in rows for k in r if k not in ("day","ticker")})
by_day = defaultdict(list)
for r in rows:
    if start <= r["day"] <= end: by_day[r["day"]].append(r)
res = []
for k in keys:
    ics = []
    for d, rs in sorted(by_day.items()):
        i = panel.idx[d]; xs, ys = [], []
        for r in rs:
            y = panel.ret(r["ticker"], i, 5)
            if k in r and y is not None: xs.append(r[k]); ys.append(y)
        if len(set(xs)) > 3: ics.append(spearman(xs, ys))
    m, t, n = tstat(ics)
    if m is not None and n >= 5: res.append((t or 0, k, m, n))
for t, k, m, n in sorted(res):
    print(f"{k:60} IC {m:+.3f} t {t:+.2f} n={n}")
