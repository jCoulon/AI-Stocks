"""Tests de non-régression issus de l'audit des analyses (un test par écart corrigé)."""

import json
import math
import random
import unittest
from datetime import date, datetime

from sp500_analyzer.analysis.coherence import explaining_news
from sp500_analyzer.analysis.indicators import bollinger, closes_on_calendar
from sp500_analyzer.analysis.macro import analyze_macro
from sp500_analyzer.analysis.research import fit_garch, variance_ratio
from sp500_analyzer.analysis.sentiment import score_text
from sp500_analyzer.analysis.stock import performance
from sp500_analyzer.analysis.technical import analyze_technical
from sp500_analyzer.models import Bar, NewsItem
from sp500_analyzer.orchestrator import Orchestrator
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.report import to_json
from tests.test_research import bars_from_returns, weekdays


def simulate_garch(a, b, n, seed, var_l=1e-4):
    rng = random.Random(seed)
    s2, out = var_l, []
    for _ in range(n):
        e = rng.gauss(0, math.sqrt(s2))
        out.append(e)
        s2 = var_l * (1 - a - b) + a * e * e + b * s2
    return out


class IndicatorAuditTests(unittest.TestCase):
    def test_bollinger_uses_population_std(self):
        closes = [float(x) for x in [1, 2, 3, 4, 5] * 4]
        mid, up, _ = bollinger(closes, 20, 2)
        pop_sd = math.sqrt(sum((c - 3) ** 2 for c in closes) / 20)
        self.assertAlmostEqual(up[-1], 3 + 2 * pop_sd)


class CalendarAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockDataProvider()
        self.intc = self.provider.price_history("INTC")  # séance du mardi manquante
        self.index = self.provider.price_history("^GSPC")

    def test_closes_on_calendar_fills_gaps(self):
        cal = [b.day for b in self.index]
        aligned = closes_on_calendar(self.intc, cal)
        self.assertEqual(len(aligned), len(cal))
        self.assertEqual(aligned[-4], aligned[-5])  # mardi manquant = cours du lundi reporté

    def test_five_session_return_spans_five_sessions(self):
        start = self.index[-6].day
        start_close = next(b.close for b in reversed(self.intc) if b.day <= start)
        expected = self.intc[-1].close / start_close - 1
        perf, rel = performance(self.intc, self.index)
        self.assertAlmostEqual(perf["1 semaine"], expected)
        short, _, _ = analyze_technical(self.intc, self.index)
        r5 = next(s for s in short.signals if s.name == "Perf. 5 séances").value
        self.assertAlmostEqual(r5, expected * 100)


class SentimentAuditTests(unittest.TestCase):
    def test_financial_phrases(self):
        self.assertGreater(score_text("Fed holds rates steady, signals openness to cut later this year"), 0)
        self.assertGreater(score_text("Treasury yields fall after dovish Fed statement"), 0)
        self.assertLess(score_text("Jobless claims rise slightly"), 0)
        self.assertGreater(score_text("Chevron rises with crude after OPEC+ extends output cuts"), 0)
        self.assertLess(score_text("Treasury yields jump as inflation accelerates"), 0)
        self.assertLess(score_text("Company cuts guidance"), score_text("Company cuts costs"))

    def test_acquisition_is_not_positive_by_default(self):
        self.assertEqual(score_text("Acme to acquire rival"), 0.0)


class MacroAuditTests(unittest.TestCase):
    def test_lookbacks_follow_calendar_not_observation_count(self):
        # Série hebdomadaire des Fed funds : une baisse il y a 10 semaines doit compter
        # dans « 3 mois », une baisse il y a 20 semaines non.
        fridays = [d for d in weekdays(400) if d.weekday() == 4]

        def fed(weeks_ago):
            cut = fridays[-weeks_ago]
            return [(d, 4.0 if d < cut else 3.75) for d in fridays]

        def monetary_signal(series):
            _, medium = analyze_macro({"fed_funds": series}, "Index", date(2026, 9, 25))
            return next(s for s in medium.signals if s.name.startswith("Politique"))

        self.assertLess(monetary_signal(fed(10)).value, 0)
        self.assertEqual(monetary_signal(fed(20)).value, 0)


class RobustnessAuditTests(unittest.TestCase):
    def test_short_histories_do_not_crash_and_export_valid_json(self):
        for history in (8, 30, 60):
            report = Orchestrator(MockDataProvider(history=history), retries=0).run()
            self.assertEqual(len(report.tickers), 30, history)
            self.assertFalse([r for r in report.trace if r["status"] != "done"], history)
            json.loads(to_json(report))  # strict : pas de NaN
            for t in report.tickers:
                self.assertIsNotNone(t.stock)


class TimingAuditTests(unittest.TestCase):
    def test_news_timing(self):
        days = [date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22)]
        bars = [Bar(d, 1, 1, 1, 1, 1) for d in days]

        def news(dt, source="Reuters"):
            return [NewsItem("X", dt, source, "x")]

        self.assertTrue(explaining_news(bars, 2, news(datetime(2026, 9, 19, 10))))   # samedi → lundi
        self.assertFalse(explaining_news(bars, 2, news(datetime(2026, 9, 21, 18))))  # après clôture
        self.assertTrue(explaining_news(bars, 3, news(datetime(2026, 9, 21, 18))))   # → mardi
        self.assertFalse(explaining_news(bars, 2, news(datetime(2026, 9, 17, 9))))   # trop ancienne
        self.assertFalse(explaining_news(bars, 2, news(datetime(2026, 9, 21, 9), "StockBuzzDaily")))


class StatisticsAuditTests(unittest.TestCase):
    def test_garch_estimates_are_close_to_truth(self):
        days = weekdays(1000)
        fits = [fit_garch(bars_from_returns(simulate_garch(0.08, 0.90, 1000, s), days), n=1000) for s in range(4)]
        self.assertAlmostEqual(sum(f.alpha for f in fits) / 4, 0.08, delta=0.02)
        self.assertAlmostEqual(sum(f.beta for f in fits) / 4, 0.90, delta=0.03)

    def test_variance_ratio_robust_to_volatility_clustering(self):
        # Marche aléatoire à volatilité GARCH : pas d'autocorrélation, donc le test ne doit
        # conclure à un régime qu'environ 5 % du temps.
        days = weekdays(260)
        n = 200
        false_regimes = sum(
            abs(variance_ratio(bars_from_returns(simulate_garch(0.12, 0.86, 260, s), days))[1]) > 1.96
            for s in range(n)
        )
        self.assertLess(false_regimes / n, 0.09)


def mirror(bars, k=100.0 ** 2):
    """Trajectoire miroir en log autour de 100 : chaque hausse devient une baisse identique."""
    return [Bar(b.day, k / b.open, k / b.low, k / b.high, k / b.close, b.volume) for b in bars]


class SymmetryAndContinuityAuditTests(unittest.TestCase):
    def setUp(self):
        rng = random.Random(9)
        self.days = weekdays(300)
        self.index = bars_from_returns([rng.gauss(0, 0.009) for _ in self.days], self.days)
        self.paths = [bars_from_returns([rng.gauss(0, 0.015) for _ in self.days], self.days) for _ in range(12)]

    def test_time_series_momentum_is_symmetric(self):
        from sp500_analyzer.analysis.research import price_factors
        for bars in self.paths:
            a = price_factors(bars, self.index)["tsmom"]
            b = price_factors(mirror(bars), mirror(self.index))["tsmom"]
            self.assertAlmostEqual(a + b, 0.0, delta=0.05)

    def test_scored_returns_are_symmetric(self):
        for bars in self.paths:
            a, _, _ = analyze_technical(bars, self.index)
            b, _, _ = analyze_technical(mirror(bars), mirror(self.index))
            sa = {x.name: x.score for x in a.signals}
            sb = {x.name: x.score for x in b.signals}
            self.assertAlmostEqual(sa["Perf. 5 séances"] + sb["Perf. 5 séances"], 0.0, delta=0.01)

    def test_biased_duplicate_signal_removed(self):
        _, medium, _ = analyze_technical(self.paths[0], self.index)
        self.assertNotIn("Distance plus haut 52s", {s.name for s in medium.signals})

    def test_signals_are_continuous_in_price(self):
        from dataclasses import replace
        for bars in self.paths[:6]:
            prev = None
            for k in range(-20, 21):
                last = bars[-1]
                c = last.close * (1 + k * 0.001)
                shifted = bars[:-1] + [replace(last, close=c, high=max(last.high, c), low=min(last.low, c))]
                sh, md, _ = analyze_technical(shifted, self.index)
                cur = {x.name: x.score for x in sh.signals + md.signals}
                if prev:
                    for name, v in cur.items():
                        self.assertLess(abs(v - prev[name]), 0.2, name)
                prev = cur


class MethodologyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sp500_analyzer.engine import run_analysis
        cls.reports = [run_analysis(MockDataProvider(seed=s)) for s in (1, 2, 3)]

    def test_trend_is_not_double_counted(self):
        from sp500_analyzer.analysis.backtest import spearman
        tech, research = [], []
        for r in self.reports:
            for t in r.tickers:
                tech.append(t.pillars["technique_moyen"].score)
                research.append(t.pillars["recherche_moyen"].score)
        self.assertLess(abs(spearman(tech, research)), 0.3)
        names = {s.name for s in self.reports[0].tickers[0].pillars["technique_moyen"].signals}
        self.assertIn("Momentum 12-1 mois", names)  # la tendance académique est bien dans le bloc tendance
        self.assertNotIn("Momentum 12-1 mois",
                         {s.name for s in self.reports[0].tickers[0].pillars["recherche_moyen"].signals})

    def test_single_beta_everywhere(self):
        for t in self.reports[0].tickers:
            research_beta = next(f.value for f in t.research.factors if f.key == "beta")
            self.assertAlmostEqual(t.stock.risk_metrics["Bêta vs S&P 500"], research_beta)

    def test_ranges_are_centered_uncertainty_bands(self):
        for t in self.reports[0].tickers:
            for o in (t.short, t.medium):
                self.assertAlmostEqual((o.low + o.high) / 2, t.last_close, places=6)

    def test_no_tone_shift_without_recent_news(self):
        for r in self.reports:
            for t in r.tickers:
                names = {s.name for s in t.pillars["sentiment_moyen"].signals}
                if t.stats.get("news_count_7d", 0) == 0:
                    self.assertNotIn("Inflexion du ton", names, t.security.ticker)


if __name__ == "__main__":
    unittest.main()
