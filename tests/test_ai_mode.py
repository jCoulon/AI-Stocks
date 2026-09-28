import unittest
from datetime import date

from sp500_analyzer.analysis.scoring import CONTRARIAN_SHORT, build_outlook
from sp500_analyzer.models import PillarResult, Signal
from sp500_analyzer.orchestrator import Orchestrator
from sp500_analyzer.providers import MockDataProvider


def pillar(name, score):
    return PillarResult(name, "court", [Signal("x", None, score, 1.0, "")])


class AiModeTests(unittest.TestCase):
    def test_contrarian_pillar_is_inverted(self):
        pillars = {"technique": pillar("technique", 0.6), "sentiment": pillar("sentiment", 0.2)}
        normal = build_outlook("court", pillars, 100, 0.02, 1.0, 1.0)
        ai = build_outlook("court", pillars, 100, 0.02, 1.0, 1.0, contrarian=CONTRARIAN_SHORT)
        self.assertAlmostEqual(ai.contributions["technique"], -normal.contributions["technique"])
        self.assertAlmostEqual(ai.contributions["sentiment"], normal.contributions["sentiment"])
        self.assertLess(ai.score, normal.score)

    def test_only_ai_tickers_are_affected(self):
        r = Orchestrator(MockDataProvider(as_of=date(2026, 9, 25))).run()
        by = {t.security.ticker: t for t in r.tickers}
        for ticker, sign in (("NVDA", -1), ("KO", 1)):
            t = by[ticker]
            tech = t.pillars["technique_court"].score
            if abs(tech) > 1e-6:
                self.assertEqual(t.short.contributions["technique"] * tech > 0, sign > 0, ticker)


if __name__ == "__main__":
    unittest.main()
