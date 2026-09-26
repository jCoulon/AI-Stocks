import unittest
from datetime import date, timedelta

from sp500_analyzer.analysis.indicators import atr, bollinger, ema, macd, rsi, sma
from sp500_analyzer.models import Bar


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_seeded_with_sma(self):
        out = ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(out[:2], [None, None])
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[3], 3.0)  # 4*0.5 + 2*0.5

    def test_rsi_bounds(self):
        up = [float(i) for i in range(1, 40)]
        self.assertEqual(rsi(up)[-1], 100.0)
        down = list(reversed(up))
        self.assertAlmostEqual(rsi(down)[-1], 0.0)
        zigzag = [10 + (i % 2) for i in range(40)]
        self.assertTrue(40 < rsi(zigzag)[-1] < 60)

    def test_macd_alignment(self):
        closes = [100 + i * 0.5 for i in range(60)]
        line, sig, hist = macd(closes)
        self.assertEqual(len(line), 60)
        self.assertIsNone(hist[30])
        self.assertIsNotNone(hist[-1])
        self.assertGreater(line[-1], 0)  # tendance haussière

    def test_bollinger_contains_mid(self):
        closes = [100 + (i % 5) for i in range(30)]
        mid, up, lo = bollinger(closes)
        self.assertTrue(lo[-1] < mid[-1] < up[-1])

    def test_atr_constant_range(self):
        d0 = date(2026, 1, 1)
        bars = [Bar(d0 + timedelta(days=i), 100, 101, 99, 100, 1000) for i in range(30)]
        self.assertAlmostEqual(atr(bars)[-1], 2.0)


if __name__ == "__main__":
    unittest.main()
