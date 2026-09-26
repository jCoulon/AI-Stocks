import html as htmllib
import io
import json
import re
import unittest
from contextlib import redirect_stdout

from sp500_analyzer.analysis.stock import key_levels, performance, risk_metrics
from sp500_analyzer.cli import main
from sp500_analyzer.engine import run_analysis
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.report import render_html, render_stock_sheets


class StockAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = MockDataProvider()
        cls.report = run_analysis(cls.provider)
        cls.by = {t.security.ticker: t for t in cls.report.tickers}

    def test_every_ticker_has_a_sheet(self):
        for t in self.report.tickers:
            self.assertIsNotNone(t.stock, t.security.ticker)
            self.assertTrue(t.stock.thesis.startswith(t.security.name))
            self.assertEqual(len(t.stock.history), 126)

    def test_levels_bracket_the_price(self):
        for t in self.report.tickers:
            for lv in t.stock.levels:
                if lv.kind == "support":
                    self.assertLess(lv.price, t.last_close)
                if lv.kind == "resistance":
                    self.assertGreater(lv.price, t.last_close)
            prices = [lv.price for lv in t.stock.levels]
            self.assertEqual(prices, sorted(prices, reverse=True))

    def test_levels_dedupe_annual_extremes(self):
        bars = self.provider.price_history("META")
        levels = key_levels(bars, None, None)
        hi = next(lv.price for lv in levels if lv.label == "Plus haut 52 sem.")
        self.assertFalse([lv for lv in levels if lv.kind == "resistance" and abs(lv.price / hi - 1) <= 0.005])

    def test_performance_and_beta(self):
        idx = self.provider.price_history("^GSPC")
        perf, rel = performance(idx, idx)
        self.assertAlmostEqual(rel["1 mois"], 0.0, places=9)  # l'indice ne bat pas l'indice
        self.assertAlmostEqual(risk_metrics(idx, idx, 1.0)["Bêta vs S&P 500"], 1.0, places=6)
        tsla, ko = self.by["TSLA"].stock.risk_metrics, self.by["KO"].stock.risk_metrics
        self.assertGreater(tsla["Bêta vs S&P 500"], ko["Bêta vs S&P 500"])
        self.assertGreater(tsla["Volatilité annualisée"], ko["Volatilité annualisée"])

    def test_catalysts_reflect_quality_controller(self):
        meta = self.by["META"].stock.catalysts
        self.assertTrue(meta and all(not c.retained for c in meta))  # rumeur écartée
        unh = self.by["UNH"].stock.catalysts[0]
        self.assertTrue(unh.retained)
        self.assertLess(unh.tone, 0)
        self.assertGreater(unh.reaction, 0)  # divergence prix / news

    def test_strengths_and_risks(self):
        nvda = self.by["NVDA"].stock
        self.assertTrue(any("Catalyseur" in s and "Nvidia" in s for s in nvda.strengths))
        tsla = self.by["TSLA"].stock
        self.assertTrue(any("Catalyseur" in r and "Tesla" in r for r in tsla.risks))
        self.assertTrue(any("manipulation" in r for r in self.by["META"].stock.risks))

    def test_peers_same_sector(self):
        aapl = self.by["AAPL"]
        tech = {t.security.ticker for t in self.report.tickers if t.security.sector == "Technology"}
        peers = {p.ticker for p in aapl.stock.peers}
        self.assertEqual(peers, tech - {"AAPL"})
        rank, total = aapl.stock.sector_rank
        self.assertEqual(total, len(tech))
        self.assertTrue(1 <= rank <= total)

    def test_renderers(self):
        focused = run_analysis(self.provider, ["UNH"])
        text = render_stock_sheets(focused, ["UNH"])
        for part in ("FICHE UNH", "Niveaux clés", "Catalyseurs", "Pairs du secteur", "cours actuel"):
            self.assertIn(part, text)
        page = render_html(focused)
        self.assertIn('<details id="UNH" open>', page)
        raw = re.search(r"data-points='([^']*)'", page).group(1)
        points = json.loads(htmllib.unescape(raw))
        self.assertEqual(len(points), 126)

    def test_cli_stock_option(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["-s", "LLY", "--no-color"]), 0)
        out = buf.getvalue()
        self.assertIn("FICHE LLY", out)
        self.assertNotIn("AVIS PAR ACTION", out)


if __name__ == "__main__":
    unittest.main()
