import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from research import *
R = ROOT/"research"/"daily"
def ohlc(t):
    with open(R/f"{t}.csv") as f:
        return {date.fromisoformat(r["Date"]): (float(r["Open"]), float(r["Close"])) for r in csv.DictReader(f)}
btc = ohlc("BTC-USD"); MINERS = ["IREN","CIFR","WULF","CORZ","APLD"]
px = {t: ohlc(t) for t in MINERS}
def ols(x, y):
    mx, my = mean(x), mean(y); sxx = sum((a-mx)**2 for a in x)
    b = sum((a-mx)*(c-my) for a, c in zip(x, y))/sxx
    res = [c-my-b*(a-mx) for a, c in zip(x, y)]
    return b, b/math.sqrt(sum(r*r for r in res)/(len(x)-2)/sxx), len(x)
def run(start, end):
    x, gap, oc = [], [], []
    days = sorted(px["IREN"])
    for k in range(1, len(days)):
        mon, fri = days[k], days[k-1]
        if not (start <= mon <= end) or mon.weekday() != 0 or (mon - fri).days != 3: continue
        sun = mon - timedelta(days=1)
        if fri not in btc or sun not in btc: continue
        wk = btc[sun][1]/btc[fri][1]-1
        g = [px[t][mon][0]/px[t][fri][1]-1 for t in MINERS if mon in px[t] and fri in px[t]]
        o = [px[t][mon][1]/px[t][mon][0]-1 for t in MINERS if mon in px[t]]
        if len(g) >= 3: x.append(wk); gap.append(mean(g)); oc.append(mean(o))
    print(f"  {start}→{end}  écart d'ouverture lundi ~ BTC week-end : pente %+.2f t %+.2f n=%d" % ols(x, gap))
    print(f"  {start}→{end}  lundi ouverture→clôture ~ BTC week-end : pente %+.2f t %+.2f n=%d" % ols(x, oc))
run(date(2026,4,1), date(2026,9,25))
