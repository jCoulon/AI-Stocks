"""Scores par pilier et par signal de l'outil, toutes les 5 séances, univers IA (2026)."""
import sys, pickle
from datetime import date
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]) + "")
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.providers.pointintime import PointInTimeProvider
from sp500_analyzer.orchestrator import Orchestrator
base = RealDataProvider(str(__import__("pathlib").Path(__file__).resolve().parents[2]) + "/data", universe="ia")
cal = [d for d in base.trading_days() if date(2026,1,2) <= d <= date(2026,9,18)]
out = []
for d in cal[::5]:
    r = Orchestrator(PointInTimeProvider(base, d)).run()
    for t in r.tickers:
        row = {"day": d, "ticker": t.security.ticker, "short": t.short.score, "medium": t.medium.score}
        for k, v in t.short.contributions.items(): row["C:" + k] = v
        for pk, p in t.pillars.items():
            row["P:" + pk] = p.score
            for s in p.signals: row[f"S:{pk}:{s.name}"] = s.score
        out.append(row)
    print(d, len(out), flush=True)
pickle.dump(out, open(sys.argv[1], "wb"))
