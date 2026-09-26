import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta

from sp500_analyzer.analysis.coherence import assess
from sp500_analyzer.analysis.scoring import build_outlook, label_for
from sp500_analyzer.analysis.sentiment import score_text
from sp500_analyzer.cli import main
from sp500_analyzer.engine import run_analysis
from sp500_analyzer.models import Bar, PillarResult, Signal
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.report import render_html, render_text, to_json

AS_OF = date(2026, 9, 25)


def _codes(analysis):
    return {f.code for f in analysis.flags}


class SentimentTests(unittest.TestCase):
    def test_polarity(self):
        self.assertGreater(score_text("Apple beats estimates, record growth"), 0.5)
        self.assertLess(score_text("Tesla cuts guidance, shares slump"), -0.5)
        self.assertEqual(score_text("Company files quarterly report"), 0.0)

    def test_negation_and_emoji(self):
        self.assertLess(score_text("results not strong"), 0)
        self.assertGreater(score_text("$XYZ 🚀🚀"), 0)


class ScoringTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(label_for(0.5), "Haussier")
        self.assertEqual(label_for(0.2), "Plutôt haussier")
        self.assertEqual(label_for(0.0), "Neutre")
        self.assertEqual(label_for(-0.2), "Plutôt baissier")
        self.assertEqual(label_for(-0.5), "Baissier")

    def _pillar(self, name, score):
        p = PillarResult(name, "court")
        p.signals.append(Signal("x", None, score, 1.0, ""))
        return p

    def test_agreement_raises_confidence(self):
        agree = {k: self._pillar(k, 0.5) for k in ("technique", "sentiment", "macro")}
        mixed = {"technique": self._pillar("technique", 0.9), "sentiment": self._pillar("sentiment", -0.6),
                 "macro": self._pillar("macro", -0.3)}
        a = build_outlook("court", agree, 100, 0.02, 1.0, 1.0)
        m = build_outlook("court", mixed, 100, 0.02, 1.0, 1.0)
        self.assertGreater(a.confidence, m.confidence)
        self.assertLessEqual(a.confidence, 0.8)
        self.assertTrue(a.low < 100 < a.high)

    def test_poor_data_lowers_confidence(self):
        pillars = {k: self._pillar(k, 0.5) for k in ("technique", "sentiment", "macro")}
        good = build_outlook("moyen", pillars, 100, 0.02, 1.0, 1.0)
        bad = build_outlook("moyen", pillars, 100, 0.02, 0.6, 0.5)
        self.assertLess(bad.confidence, good.confidence)


class MockProviderTests(unittest.TestCase):
    def test_deterministic(self):
        a, b = MockDataProvider(seed=7), MockDataProvider(seed=7)
        self.assertEqual(a.price_history("AAPL"), b.price_history("AAPL"))
        self.assertNotEqual(a.price_history("AAPL"), MockDataProvider(seed=8).price_history("AAPL"))

    def test_last_week_is_simulated(self):
        p = MockDataProvider()
        bars = p.price_history("NVDA")
        self.assertEqual(bars[-1].day, AS_OF)
        self.assertEqual([b.day.weekday() for b in bars[-5:]], [0, 1, 2, 3, 4])
        for b in bars:
            self.assertTrue(b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high)


class CoherenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_analysis(MockDataProvider())
        cls.by = {t.security.ticker: t for t in cls.report.tickers}

    def test_scenarios_detected(self):
        self.assertIn("UNEXPLAINED_MOVE", _codes(self.by["AMD"]))
        self.assertIn("MISSING_BARS", _codes(self.by["INTC"]))
        self.assertTrue({"UNCONFIRMED_RUMOR", "SUSPECTED_BOTS", "HYPE_WITHOUT_CONFIRMATION"} <= _codes(self.by["META"]))
        self.assertIn("PRICE_NEWS_DIVERGENCE", _codes(self.by["UNH"]))
        for t in ("NVDA", "TSLA", "PFE", "JPM", "LLY"):
            self.assertIn("CONFIRMED_BY_NEWS", _codes(self.by[t]), t)

    def test_clean_tickers_have_no_warnings(self):
        for t in ("MSFT", "KO", "JPM"):
            self.assertFalse([f for f in self.by[t].flags if f.severity != "info"], t)

    def test_flags_reduce_reliability(self):
        self.assertLess(self.by["META"].coherence, self.by["MSFT"].coherence)
        self.assertLess(self.by["INTC"].data_quality, 1.0)
        self.assertLess(self.by["META"].stats["bot_score"], 1.0 + 1e-9)
        self.assertGreater(self.by["META"].stats["bot_score"], 0.3)

    def test_news_direction_drives_sentiment(self):
        self.assertLess(self.by["TSLA"].pillars["sentiment_court"].score, 0)
        self.assertLess(self.by["PFE"].pillars["sentiment_court"].score, 0)
        self.assertGreater(self.by["NVDA"].pillars["sentiment_court"].score, 0)

    def test_broken_and_stale_bars(self):
        d0 = AS_OF - timedelta(days=10)
        cal = [d0 + timedelta(days=i) for i in range(11)]
        bars = [Bar(d, 100, 101, 99, 100, 1000) for d in cal[:-1]]
        bars[3] = Bar(cal[3], 100, 99, 101, 100, 1000)  # high < low
        res = assess(bars, cal, [], [], AS_OF, datetime.combine(AS_OF, datetime.min.time()))
        codes = {f.code for f in res.flags}
        self.assertIn("OHLC_INCONSISTENT", codes)
        self.assertIn("STALE_PRICES", codes)
        self.assertLess(res.data_quality, 0.7)


class EngineAndReportTests(unittest.TestCase):
    def test_scores_bounded(self):
        report = run_analysis(MockDataProvider())
        self.assertEqual(len(report.tickers), 30)
        for t in report.tickers + [report.index]:
            for o in (t.short, t.medium):
                self.assertTrue(-1 <= o.score <= 1)
                self.assertTrue(0 < o.confidence <= 0.8)
                self.assertTrue(o.low < t.last_close < o.high)

    def test_ticker_filter_keeps_breadth(self):
        full = run_analysis(MockDataProvider())
        one = run_analysis(MockDataProvider(), ["aapl"])
        self.assertEqual([t.security.ticker for t in one.tickers], ["AAPL"])
        self.assertEqual(one.breadth, full.breadth)

    def test_renderers(self):
        report = run_analysis(MockDataProvider(), ["META"])
        text = render_text(report, detail=["META"])
        self.assertIn("pas un conseil", text.lower())
        self.assertIn("SUSPECTED_BOTS", text)
        data = json.loads(to_json(report))
        self.assertEqual(data["tickers"][0]["security"]["ticker"], "META")
        html = render_html(report)
        self.assertIn("<svg", html)
        self.assertIn('id="META"', html)

    def test_cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["-t", "NVDA", "--no-color"]), 0)
        self.assertIn("NVDA — Nvidia", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
