import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sp500_analyzer.analysis.sentiment import headline_tone
from sp500_analyzer.models import NewsItem
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers.finbert import load_scores, score_titles
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.providers.realnews import read_news_rows, write_news_csv
from sp500_analyzer.providers.rss import collect_rss, merge_rows, parse_rss
from tests.test_period_backtest import write_stooq_csvs

YAHOO = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Yahoo! Finance: NVDA News</title>
<item><title>Nvidia stock rises after record data center sales</title>
<link>https://finance.yahoo.com/news/nvidia-record-123.html</link>
<pubDate>Thu, 24 Sep 2026 20:15:00 +0000</pubDate></item>
<item><title>Why Nvidia shares could fall further, analysts warn</title>
<link>https://www.fool.com/investing/2026/09/24/nvidia/</link>
<pubDate>Thu, 24 Sep 2026 13:00:00 +0000</pubDate></item>
<item><title>Short</title><link>https://x.com</link><pubDate>Thu, 24 Sep 2026 13:00:00 +0000</pubDate></item>
</channel></rss>"""


class RssTests(unittest.TestCase):
    def test_parse_rss_new_york_time_and_sources(self):
        rows = parse_rss(YAHOO, "Yahoo Finance")
        self.assertEqual(len(rows), 2)  # titre trop court ignoré
        published, source, domain, title, _ = rows[0]
        self.assertEqual(published, datetime(2026, 9, 24, 16, 15))  # 20h15 UTC = 16h15 à New York (été)
        self.assertEqual((source, domain), ("Yahoo Finance", "finance.yahoo.com"))
        self.assertEqual(rows[1][1], "The Motley Fool")  # source d'origine reconnue par son domaine

    def test_collection_accumulates_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fetch = lambda url: YAHOO if "yahoo" in url else "<rss><channel></channel></rss>"  # noqa: E731
            self.assertEqual(collect_rss(root, ["NVDA"], log=lambda *a: None, fetch=fetch), [])
            collect_rss(root, ["NVDA"], log=lambda *a: None, fetch=fetch)  # 2e passage : rien de nouveau
            self.assertEqual(len(read_news_rows(root / "news" / "rss" / "NVDA.csv")), 2)

            def broken(url):
                raise TimeoutError("down")

            errors = collect_rss(root, ["NVDA"], log=lambda *a: None, fetch=broken)
            self.assertEqual(len(errors), 2)  # Yahoo et Nasdaq en échec...
            self.assertEqual(len(read_news_rows(root / "news" / "rss" / "NVDA.csv")), 2)  # ...historique conservé

    def test_merge_keeps_first_publication(self):
        a = (datetime(2026, 9, 24, 10), "CNBC", "cnbc.com", "Nvidia soars on demand", "u1")
        b = (datetime(2026, 9, 24, 9), "Reuters", "reuters.com", "NVIDIA soars on demand!", "u2")
        self.assertEqual(merge_rows([a], [b]), [b])


class FinbertTests(unittest.TestCase):
    def test_scores_only_new_titles_and_provider_uses_them(self):
        calls = []

        def fake(titles):
            calls.append(list(titles))
            return [{"positive": 0.1, "negative": 0.85, "neutral": 0.05} if "fall" in t
                    else {"positive": 0.9, "negative": 0.02, "neutral": 0.08} for t in titles]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily").mkdir()
            write_stooq_csvs(MockDataProvider(history=400), root / "daily")
            (root / "news" / "rss").mkdir(parents=True)
            write_news_csv(root / "news" / "rss" / "NVDA.csv", parse_rss(YAHOO, "Yahoo Finance"))
            write_news_csv(root / "news" / "NVDA.csv", [  # même titre via GDELT : un seul score
                (datetime(2026, 9, 24, 16, 20), "Reuters", "reuters.com",
                 "Nvidia stock rises after record data center sales", "u")])
            self.assertEqual(score_titles(root, fake, log=lambda *a: None), 2)
            self.assertEqual(score_titles(root, fake, log=lambda *a: None), 0)  # tout est en cache
            self.assertEqual(len(calls), 1)
            scores = load_scores(root)
            self.assertAlmostEqual(scores["why nvidia shares could fall further analysts warn"], -0.75)

            p = RealDataProvider(root)
            nvda = p.news("NVDA", datetime(2026, 1, 1))
            self.assertEqual(len(nvda), 2)  # doublon GDELT / RSS fusionné
            self.assertEqual(nvda[0].headline, "Why Nvidia shares could fall further, analysts warn")
            self.assertAlmostEqual(nvda[0].tone, -0.75)
            self.assertIn("ton FinBERT : 2/2 titres", p.coverage())

    def test_headline_tone_prefers_precomputed_score(self):
        text = "Nvidia beats estimates but guidance disappoints"
        self.assertEqual(headline_tone(NewsItem("NVDA", datetime(2026, 9, 24), "Reuters", text, -0.6)), -0.6)
        self.assertNotEqual(headline_tone(NewsItem("NVDA", datetime(2026, 9, 24), "Reuters", text)), -0.6)


if __name__ == "__main__":
    unittest.main()
