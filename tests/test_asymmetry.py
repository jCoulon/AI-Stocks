import io
import json
import math
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path

from sp500_analyzer.analysis.asymmetry import build_row, price_metrics, render_asymmetry, score_rows
from sp500_analyzer.cli import main
from sp500_analyzer.models import Bar
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers.fundamentals import download_fundamentals, extract
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.universe import UNIVERSES
from tests.test_period_backtest import write_stooq_csvs


def bars(closes):
    d0 = date(2025, 1, 1)
    return [Bar(d0 + timedelta(days=i), c, c * 1.01, c * 0.99, c, 1000) for i, c in enumerate(closes)]


def quote_summary(**fin):
    raw = lambda v: {"raw": v, "fmt": str(v)}  # noqa: E731
    return {"quoteSummary": {"result": [{
        "price": {"marketCap": raw(5e9)},
        "financialData": {k: raw(v) for k, v in fin.items()},
        "defaultKeyStatistics": {"enterpriseToRevenue": raw(10.0), "shortPercentOfFloat": raw(0.2)},
        "summaryDetail": {"forwardPE": {}}}], "error": None}}


class AsymmetryTests(unittest.TestCase):
    def test_price_metrics(self):
        m = price_metrics(bars([100 + i * 0.1 for i in range(300)]))
        self.assertAlmostEqual(m["price"], 129.9)
        self.assertGreater(m["pos_52w"], 0.95)  # tendance régulière : proche du plus haut
        self.assertLess(m["vol"], 0.05)

    def test_row_flags_and_ratios(self):
        wild = [10.0]
        for i in range(299):
            wild.append(wild[-1] * (1.3 if i == 290 else (1.06 if i % 2 else 0.95)))
        fund = {"target_mean": wild[-1] * 1.5, "target_high": wild[-1] * 3, "target_low": wild[-1] * 1.1,
                "analysts": 3, "revenue_growth": 1.2, "ev_to_revenue": 20.0, "free_cash_flow": -100e6,
                "cash": 150e6, "short_float": 0.25, "fetched": "2026-09-28"}
        r = build_row("XX", "Test", "Néocloud", bars(wild), fund)
        self.assertAlmostEqual(r.target_upside, 0.5)
        self.assertEqual(r.analyst_ratio, math.inf)  # même l'objectif le plus bas est au-dessus du cours
        self.assertAlmostEqual(r.growth_per_multiple, 0.06)
        self.assertAlmostEqual(r.cash_years, 1.5)
        for flag in ("profil loterie", "dilution probable", "peu d'analystes", "sous l'objectif le plus bas",
                     "vente à découvert 25%"):
            self.assertTrue(any(flag in f for f in r.flags), flag)
        self.assertIn("fondamentaux absents", build_row("YY", "Y", "Puces", bars([1.0] * 60), None).flags)

    def test_scoring_ranks_and_sorting(self):
        rows = []
        for i, t in enumerate(["A", "B", "C", "D"]):
            fund = {"target_mean": 100 * (1 + 0.1 * i), "target_high": 150, "target_low": 80 - 5 * i,
                    "revenue_growth": 0.1 * i, "ev_to_revenue": 5.0}
            rows.append(build_row(t, t, "Puces", bars([100.0] * 60), fund))
        rows.append(build_row("E", "E", "Puces", bars([100.0] * 60), None))
        ranked = score_rows(rows)
        self.assertEqual([r.ticker for r in ranked], ["D", "C", "B", "A", "E"])
        self.assertIsNone(ranked[-1].score)  # sans fondamentaux : pas de score
        text = render_asymmetry(ranked)
        self.assertIn("pas un conseil", text)
        self.assertIn("cours unitaire bas", text)

    def test_extract_and_download(self):
        payload = quote_summary(currentPrice=10.0, targetMeanPrice=15.0, targetHighPrice=25.0, targetLowPrice=8.0,
                                numberOfAnalystOpinions=7, revenueGrowth=0.8)
        data = extract(payload)
        self.assertEqual((data["target_mean"], data["analysts"], data["ev_to_revenue"]), (15.0, 7.0, 10.0))
        self.assertIsNone(data["forward_pe"])
        with self.assertRaises(ValueError):
            extract({"quoteSummary": {"result": None, "error": {"code": "Not Found"}}})
        with tempfile.TemporaryDirectory() as tmp:
            errors = download_fundamentals(Path(tmp), ["NBIS"], pause=0, log=lambda *a: None,
                                           session=(lambda url: json.dumps(payload), "crumb"), today=date(2026, 9, 28))
            self.assertEqual(errors, [])
            saved = json.loads((Path(tmp) / "fundamentals" / "NBIS.json").read_text())
            self.assertEqual((saved["fetched"], saved["target_high"]), ("2026-09-28", 25.0))


class AiUniverseTests(unittest.TestCase):
    def test_universes(self):
        ia = {s.ticker for s in UNIVERSES["ia"]}
        self.assertTrue({"NBIS", "IREN", "NVDA", "PLTR"} <= ia)
        self.assertFalse({"KO", "XOM"} & ia)
        self.assertEqual(len(UNIVERSES["tout"]), len({s.ticker for s in UNIVERSES["tout"]}))

    def test_cli_asymmetry_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily").mkdir()
            write_stooq_csvs(MockDataProvider(history=400), root / "daily")
            for src, dst in (("AAPL", "NBIS"), ("TSLA", "IREN")):  # cours fictifs pour deux titres IA
                shutil.copy(root / "daily" / f"{src}.csv", root / "daily" / f"{dst}.csv")
            (root / "fundamentals").mkdir()
            for t, up in (("NBIS", 1.6), ("IREN", 1.2), ("NVDA", 1.1)):
                last = RealDataProvider(root, universe="ia").price_history(t)[-1].close
                (root / "fundamentals" / f"{t}.json").write_text(json.dumps({
                    "fetched": "2026-09-28", "target_mean": last * up, "target_high": last * 2,
                    "target_low": last * 0.7, "analysts": 10, "revenue_growth": 0.5, "ev_to_revenue": 12.0}))
            self.assertEqual({s.ticker for s in RealDataProvider(root, universe="ia").universe()} & {"KO", "NBIS"},
                             {"NBIS"})
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--donnees", str(root), "--asymetrie"])
            self.assertEqual(code, 0, err.getvalue())
            text = out.getvalue()
            self.assertIn("ÉCRAN D'ASYMÉTRIE — FOCUS IA (fondamentaux du 2026-09-28)", text)
            self.assertLess(text.index("NBIS "), text.index("IREN "))  # potentiel plus élevé : mieux classé
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--asymetrie"]), 2)  # pas de données réelles
                self.assertEqual(main(["--univers", "ia"]), 2)


if __name__ == "__main__":
    unittest.main()
