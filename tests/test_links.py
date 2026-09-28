import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from sp500_analyzer.analysis.sentiment import news_score
from sp500_analyzer.models import NewsItem
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers.googlenews import google_query
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.providers.realnews import write_news_csv
from sp500_analyzer.universe import LINKS
from tests.test_period_backtest import write_stooq_csvs


class LinkTests(unittest.TestCase):
    def test_cbrs_is_linked_to_openai(self):
        (link,) = LINKS["CBRS"]
        self.assertEqual((link.entity, link.name, link.weight), ("OPENAI", "OpenAI", 0.5))
        q = google_query("OPENAI", date(2026, 9, 7), date(2026, 9, 14))
        self.assertTrue(q.startswith('"OpenAI" (funding OR valuation'))

    def test_linked_news_are_attached_weighted_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily").mkdir()
            write_stooq_csvs(MockDataProvider(history=400), root / "daily")
            (root / "daily" / "CBRS.csv").write_text((root / "daily" / "AAPL.csv").read_text())
            (root / "news" / "google").mkdir(parents=True)
            write_news_csv(root / "news" / "google" / "OPENAI.csv", [
                (datetime(2026, 9, 21, 10), "Reuters", "reuters.com", "OpenAI raises $40 billion at record valuation", "u1"),
                (datetime(2026, 9, 22, 10), "CNBC", "cnbc.com", "OpenAI expands Cerebras compute deal", "u2"),
            ])
            write_news_csv(root / "news" / "google" / "CBRS.csv", [  # même titre déjà rattaché à CBRS
                (datetime(2026, 9, 22, 9), "Bloomberg", "bloomberg.com", "OpenAI expands Cerebras compute deal", "u3")])
            p = RealDataProvider(root, universe="ia")
            news = p.news("CBRS", datetime(2026, 1, 1))
            self.assertEqual([(n.headline, n.relevance) for n in news], [
                ("[OpenAI] OpenAI raises $40 billion at record valuation", 0.5),
                ("OpenAI expands Cerebras compute deal", 1.0),  # version directe gardée, pas de doublon
            ])
            self.assertEqual(p.news("NBIS", datetime(2026, 1, 1)), [])  # NBIS est lié à Microsoft, pas à OpenAI
            self.assertIn("dont 7 via des sociétés liées", p.coverage())  # CBRS 1 + NVDA, AMD, AVGO 2 chacun

    def test_relevance_weights_the_sentiment(self):
        now = datetime(2026, 9, 22, 22)
        direct = NewsItem("CBRS", datetime(2026, 9, 22, 10), "Reuters", "Cerebras shares slump after weak outlook", -0.8)
        linked = NewsItem("CBRS", datetime(2026, 9, 22, 10), "Reuters", "[OpenAI] OpenAI surges", 0.8, relevance=0.5)
        score, weight = news_score([direct, linked], now, half_life=3.0)
        self.assertAlmostEqual(score, (-0.8 + 0.5 * 0.8) / 1.5)
        full, _ = news_score([direct, NewsItem("CBRS", linked.published, "Reuters", "x", 0.8)], now, half_life=3.0)
        self.assertAlmostEqual(full, 0.0)


if __name__ == "__main__":
    unittest.main()
