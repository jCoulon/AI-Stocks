import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from sp500_analyzer.providers.googlenews import download_google_news, google_query, parse_google_rss
from sp500_analyzer.providers.realnews import MARKET, read_news_rows

FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Nvidia shares climb as AI chip demand stays strong - Reuters</title>
<link>https://news.google.com/rss/articles/abc</link><pubDate>Tue, 08 Sep 2026 14:05:00 GMT</pubDate>
<source url="https://www.reuters.com">Reuters</source></item>
<item><title>Is Nvidia stock a buy? My take - Random Blog</title>
<link>https://news.google.com/rss/articles/def</link><pubDate>Tue, 08 Sep 2026 15:00:00 GMT</pubDate>
<source url="https://randomblog.example">Random Blog</source></item>
<item><title>Nvidia stock slides after export curbs report - CNBC</title>
<link>https://news.google.com/rss/articles/ghi</link><pubDate>Mon, 17 Aug 2026 20:30:00 GMT</pubDate>
<source url="https://www.cnbc.com">CNBC</source></item>
</channel></rss>"""


class GoogleNewsTests(unittest.TestCase):
    def test_query_requires_company_and_finance_terms(self):
        q = google_query("NVDA", date(2026, 9, 7), date(2026, 9, 14))
        self.assertIn('"Nvidia"', q)
        self.assertIn("(stock OR shares OR earnings", q)
        self.assertTrue(q.endswith("after:2026-09-06 before:2026-09-14"))
        self.assertIn('"Wall Street"', google_query(MARKET, date(2026, 9, 7), date(2026, 9, 14)))

    def test_parse_keeps_known_sources_and_strips_suffix(self):
        rows = parse_google_rss(FEED)
        self.assertEqual([r[1] for r in rows], ["CNBC", "Reuters"])  # blog inconnu écarté, tri par date
        published, _, domain, title, _ = rows[1]
        self.assertEqual((title, domain), ("Nvidia shares climb as AI chip demand stays strong", "reuters.com"))
        self.assertEqual(published, datetime(2026, 9, 8, 10, 5))  # 14h05 GMT = 10h05 à New York (été)

    def test_download_keeps_only_requested_window(self):
        urls = []

        def get(url):
            urls.append(url)
            return FEED

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors = download_google_news(root, ["NVDA"], date(2026, 9, 7), date(2026, 9, 13), pause=0,
                                          today=date(2026, 9, 26), log=lambda *a: None, sleep=lambda s: None,
                                          get=get)
            self.assertEqual(errors, [])
            self.assertEqual(len(urls), 1)
            rows = read_news_rows(root / "news" / "google" / "NVDA.csv")
            self.assertEqual([r[1] for r in rows], ["Reuters"])  # le titre d'août, hors fenêtre, est écarté
            self.assertIn("NVDA,1,1,1", (root / "news" / "google" / "couverture.csv").read_text())


if __name__ == "__main__":
    unittest.main()
