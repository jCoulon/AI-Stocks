import math
import random
import unittest
from datetime import date, datetime, timedelta

from sp500_analyzer.analysis.backtest import _forward_return, _slice, run_backtest, spearman
from sp500_analyzer.analysis.research import (
    TickerInputs, attention_shock, build_research, fit_garch, momentum_crash_risk, news_drift,
    percentile_ranks, price_factors, variance_ratio,
)
from sp500_analyzer.engine import run_analysis
from sp500_analyzer.models import Bar, NewsItem, Security, SocialPost
from sp500_analyzer.providers import DataProvider, MockDataProvider


def weekdays(n: int, end: date = date(2026, 9, 25)) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def bars_from_returns(returns: list[float], days: list[date], start: float = 100.0) -> list[Bar]:
    bars, c = [], start
    for d, r in zip(days, returns):
        o = c
        c = c * (1 + r)
        bars.append(Bar(d, o, max(o, c) * 1.001, min(o, c) * 0.999, c, 1_000_000))
    return bars


class StatisticsTests(unittest.TestCase):
    def test_percentile_ranks(self):
        r = percentile_ranks({"a": 1.0, "b": 3.0, "c": 2.0, "d": None})
        self.assertEqual((r["a"], r["c"], r["b"], r["d"]), (0.0, 0.5, 1.0, None))
        ties = percentile_ranks({"a": 1.0, "b": 1.0, "c": 2.0})
        self.assertEqual(ties["a"], ties["b"])

    def test_spearman(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0)
        self.assertIsNone(spearman([1, 2], [1, 2]))

    def test_variance_ratio_detects_regimes(self):
        rng = random.Random(1)
        days = weekdays(400)

        def ar1(phi):
            r, prev = [], 0.0
            for _ in days:
                prev = phi * prev + rng.gauss(0, 0.01)
                r.append(prev)
            return bars_from_returns(r, days)

        self.assertGreater(variance_ratio(ar1(0.4))[1], 1.96)   # autocorrélation positive : tendance
        self.assertLess(variance_ratio(ar1(-0.4))[1], -1.96)     # autocorrélation négative : retour à la moyenne
        self.assertLess(abs(variance_ratio(ar1(0.0))[1]), 2.5)   # marche aléatoire

    def test_garch_recovers_volatility_clustering(self):
        rng = random.Random(3)
        a, b, var_l = 0.08, 0.90, 0.0001
        s2, rets = var_l, []
        for _ in range(1500):
            e = rng.gauss(0, math.sqrt(s2))
            rets.append(e)
            s2 = var_l * (1 - a - b) + a * e * e + b * s2
        days = weekdays(1500)
        fit = fit_garch(bars_from_returns(rets, days), n=1500)
        self.assertGreater(fit.persistence, 0.9)
        iid = fit_garch(bars_from_returns([rng.gauss(0, 0.01) for _ in days], days), n=1500)
        self.assertLess(iid.persistence, fit.persistence)
        # La volatilité cumulée croît avec l'horizon.
        self.assertLess(fit.horizon_vol(5), fit.horizon_vol(63))

    def test_momentum_crash_condition(self):
        days = weekdays(300)
        down_then_up = [-0.002] * 278 + [0.004] * 22
        self.assertTrue(momentum_crash_risk(bars_from_returns(down_then_up, days)))
        self.assertFalse(momentum_crash_risk(bars_from_returns([0.001] * 300, days)))


class FactorTests(unittest.TestCase):
    def test_news_drift_continuation_vs_reversal(self):
        rng = random.Random(5)
        days = weekdays(120)
        rets = [rng.gauss(0, 0.01) for _ in days]
        rets[-2] = 0.06  # choc de +6 % (~6 σ) l'avant-dernière séance
        bars = bars_from_returns(rets, days)
        news = [NewsItem("X", datetime.combine(days[-2], datetime.min.time()) + timedelta(hours=8),
                         "Reuters", "X beats estimates")]
        self.assertGreater(news_drift(bars, news), 0)   # expliqué par une news : continuation
        self.assertLess(news_drift(bars, []), 0)        # sans news : retournement
        calm = bars_from_returns([rng.gauss(0, 0.01) for _ in days], days)
        self.assertIsNone(news_drift(calm, []))

    def test_attention_ignores_young_accounts(self):
        now = datetime(2026, 9, 25, 22)
        base = [SocialPost("X", now - timedelta(days=d, hours=1), "X", f"u{d}", 500, 1, "ok")
                for d in range(14)]
        bots = [SocialPost("X", now - timedelta(hours=h), "X", f"bot{h}", 5, 0, "pump") for h in range(40)]
        self.assertAlmostEqual(attention_shock(base + bots, now), attention_shock(base, now))

    def test_price_factor_directions(self):
        days = weekdays(300)
        winner = bars_from_returns([0.002] * 300, days)
        index = bars_from_returns([0.0005] * 300, days)
        f = price_factors(winner, index)
        self.assertGreater(f["mom_12_1"], 0)
        self.assertGreater(f["tsmom"], 0)
        self.assertAlmostEqual(f["high52"], 1.0, places=2)

    def test_mock_universe_scenarios(self):
        report = run_analysis(MockDataProvider())
        by = {t.security.ticker: t for t in report.tickers}
        amd = {f.key: f for f in by["AMD"].research.factors}
        self.assertLess(amd["news_drift"].score, 0)   # +7 % sans news : retournement attendu
        self.assertLess(amd["max"].score, -0.5)        # rendement journalier extrême : effet MAX
        self.assertIn("recherche_court", by["AMD"].pillars)
        for t in report.tickers:
            for f in t.research.factors:
                self.assertTrue(-1 <= f.score <= 1)
                if f.percentile is not None:
                    self.assertTrue(0 <= f.percentile <= 1)


class PersistentDriftProvider(DataProvider):
    """Univers fictif où le momentum est un vrai signal : chaque titre garde sa tendance."""

    def __init__(self, n_days: int = 700, n_tickers: int = 30):
        rng = random.Random(11)
        self.as_of = date(2026, 9, 25)
        self._days = weekdays(n_days)
        self._secs = [Security(f"T{i:02d}", f"Titre {i}", f"S{i % 5}") for i in range(n_tickers)]
        self._bars = {}
        for i, s in enumerate(self._secs):
            drift = (i - n_tickers / 2) * 0.0003
            self._bars[s.ticker] = bars_from_returns([drift + rng.gauss(0, 0.004) for _ in self._days], self._days)
        self._bars["IDX"] = bars_from_returns([rng.gauss(0, 0.002) for _ in self._days], self._days)

    def universe(self):
        return list(self._secs)

    def index(self):
        return Security("IDX", "Indice", "Index")

    def trading_days(self):
        return list(self._days)

    def price_history(self, ticker):
        return list(self._bars[ticker])

    def news(self, ticker, since):
        return []

    def social_posts(self, ticker, since):
        return []

    def macro(self):
        return {}


class BacktestTests(unittest.TestCase):
    def test_slicing_is_point_in_time(self):
        days = weekdays(50)
        bars = bars_from_returns([0.01] * 50, days)
        self.assertEqual(_slice(bars, days[19])[-1].day, days[19])
        self.assertEqual(len(_slice(bars, days[19])), 20)
        self.assertAlmostEqual(_forward_return(bars, days[10], 5), bars[15].close / bars[10].close - 1)
        self.assertIsNone(_forward_return(bars, days[-2], 5))

    def test_factors_ignore_future_data(self):
        provider = MockDataProvider()
        bars = provider.price_history("AAPL")
        index = provider.price_history("^GSPC")
        cut = bars[-40].day
        tampered = bars[:-39] + [Bar(b.day, b.open * 3, b.high * 3, b.low * 3, b.close * 3, b.volume * 9)
                                 for b in bars[-39:]]
        self.assertEqual(price_factors(_slice(bars, cut), _slice(index, cut)),
                         price_factors(_slice(tampered, cut), _slice(index, cut)))

    def test_backtest_detects_a_real_signal(self):
        # Contrôle positif : la tendance persistante doit ressortir via le momentum.
        report = run_backtest(PersistentDriftProvider(), horizons=(21,), warmup=260)
        mom = next(r for r in report.results if r.key == "mom_12_1")
        self.assertGreater(mom.mean_ic, 0.3)
        self.assertGreater(mom.t_stat, 3)

    def test_backtest_on_random_walk_finds_nothing_significant(self):
        report = run_backtest(MockDataProvider(history=600), horizons=(21,))
        self.assertTrue(all(abs(r.t_stat) < 3 for r in report.results if r.key != "composite"))
        self.assertTrue(all(r.n >= 10 for r in report.results))


if __name__ == "__main__":
    unittest.main()
