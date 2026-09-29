import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

from sp500_analyzer.analysis.watchlist import (
    DEFAULT_WATCHLIST, assess, load_watchlist, render_html, render_text, save_watchlist,
)
from sp500_analyzer.cli import main
from sp500_analyzer.models import KeyLevel
from sp500_analyzer.orchestrator import Orchestrator
from sp500_analyzer.providers import MockDataProvider


class WatchlistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = Orchestrator(MockDataProvider(as_of=date(2026, 9, 25))).run()
        cls.t = next(t for t in cls.report.tickers if t.security.ticker == "NVDA")

    def test_storage_roundtrip_and_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.json"
            self.assertEqual(load_watchlist(path), DEFAULT_WATCHLIST)
            self.assertEqual(save_watchlist(["nvda", " aip ", "NVDA", ""], path), ["NVDA", "AIP"])
            self.assertEqual(load_watchlist(path), ["NVDA", "AIP"])

    def _with_levels(self, support_gap, resistance_gap):
        t = self.t
        price, atr = t.last_close, t.stats["atr"]
        t.stock.levels = [KeyLevel("Support 1", price - support_gap * atr, "support"),
                          KeyLevel("Résistance 1", price + resistance_gap * atr, "resistance")]
        return t

    def test_entry_zone_when_on_support_with_good_reward(self):
        t = self._with_levels(0.5, 5)
        v = assess(t, {"target_mean": t.last_close * 1.3, "analysts": 8}, None, date(2026, 9, 25),
                   self.report.macro_summary)
        names = {c.name: c for c in v.checks}
        self.assertTrue(names["Support proche"].ok)
        self.assertTrue(names["Gain / risque"].ok)
        self.assertAlmostEqual(v.reward_risk, 5 / 1.0, places=5)  # risque = 0,5 + 0,5 ATR
        against = sum(c.ok is False for c in v.checks if c.name in ("Tendance de fond", "Avis court terme de l'outil",
                                                                      "Économie (taux, VIX, pétrole...)"))
        self.assertEqual(v.verdict, "Zone d'entrée technique" if against <= 1 else "À surveiller")

    def test_far_from_support_and_upcoming_earnings(self):
        t = self._with_levels(4, 1)
        v = assess(t, None, None, date(2026, 9, 25))
        self.assertFalse({c.name: c for c in v.checks}["Support proche"].ok)
        self.assertIn(v.verdict, ("À surveiller", "Pas le moment"))
        v = assess(self._with_levels(0.5, 5), None, (date(2026, 10, 1), "Résultats"), date(2026, 9, 25))
        self.assertEqual(v.verdict, "Attendre la publication")
        html = render_html([v], ["ZZZZ"], date(2026, 9, 25), ["NVDA", "ZZZZ"], ["NVDA"])
        self.assertIn("data-watch-remove=\'NVDA\'", html)
        self.assertIn("ZZZZ", html)
        self.assertIn("pas un conseil", html)
        self.assertIn("NVDA", render_text([v], [], date(2026, 9, 25)))

    def test_cli_sets_and_shows_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SP500_WATCHLIST"] = str(Path(tmp) / "w.json")
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(main(["--surveillance", "NVDA,KO,ZZZZ"]), 0)
                self.assertIn("MA LISTE DE SURVEILLANCE", out.getvalue())
                self.assertIn("ZZZZ", out.getvalue())
                self.assertEqual(json.loads((Path(tmp) / "w.json").read_text())["tickers"], ["NVDA", "KO", "ZZZZ"])
            finally:
                del os.environ["SP500_WATCHLIST"]


if __name__ == "__main__":
    unittest.main()
