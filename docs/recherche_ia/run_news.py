import sys, pickle; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
from bisect import bisect_right
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.providers.realnews import SEC_SOURCE
cache = Path(sys.argv[0]).with_name("news_ai.pkl")
if cache.exists():
    news = pickle.load(open(cache, "rb"))
else:
    rp = RealDataProvider(ROOT, universe="ia")
    news = {t: [(n.published, n.tone) for n in rp._news.get(t, []) if n.relevance >= 1 and n.source != SEC_SOURCE] for t in AI}
    pickle.dump(news, open(cache, "wb"))
times = {t: [x[0] for x in v] for t, v in news.items()}
panel = Panel(load_closes(ROOT/"daily", AI + ["SPX"]))
def window(t, i, days):
    d = panel.cal[i]; end = datetime(d.year, d.month, d.day, 16, 0)
    a = bisect_right(times[t], end - timedelta(days=days)); b = bisect_right(times[t], end)
    return news[t][a:b]
def n1(p, t, i):
    if p.cal[i] < date(2026,3,9): return None  # 60 j d'historique de news
    a, b = len(window(t, i, 7)), len(window(t, i, 63))
    return math.log((a + 1) / (b * 7 / 63 + 1))
def n2(p, t, i):
    w = [x[1] for x in window(t, i, 7) if x[1] is not None]
    return mean(w) if len(w) >= 3 else None
def n1b(p, t, i):  # volume brut 7 j (sans normalisation), pour info
    return math.log(1 + len(window(t, i, 7)))
disc = (date(2026,1,5), date(2026,5,29))
for name, f in [("N1 news anormales (+)", n1), ("N2 ton FinBERT 7j (+)", n2)]:
    for h in (1, 5):
        m, tt, n = evaluate(panel, f, *disc, h=h, step=5)
        print(f"{name:24} h={h} découverte IC {m:+.3f} t {None if tt is None else round(tt,2)} n={n}")
print({t: len(v) for t, v in news.items()})
