import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers.finbert import score_titles
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.providers.reddit import collect_reddit, parse_reddit_atom, reddit_query
from tests.test_period_backtest import write_stooq_csvs

ATOM = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><author><name>/u/diamondhands</name></author><category term="wallstreetbets" label="r/wallstreetbets"/>
<content type="html">&lt;div&gt;&lt;p&gt;Loaded up on calls before earnings&lt;/p&gt;&lt;/div&gt; submitted by /u/diamondhands [link] [comments]</content>
<id>t3_abc123</id><published>2026-09-26T14:30:00+00:00</published>
<title>NVDA earnings play, who is in?</title></entry>
<entry><author><name>/u/x</name></author><id>t3_short</id><published>2026-09-26T14:30:00+00:00</published><title>ok</title></entry>
</feed>"""


class RedditTests(unittest.TestCase):
    def test_query_uses_names_for_ambiguous_symbols(self):
        self.assertEqual(reddit_query("NVDA"), 'NVDA OR "Nvidia"')
        self.assertEqual(reddit_query("V"), '"Visa"')
        self.assertEqual(reddit_query("IREN"), 'IREN OR "Iris Energy"')

    def test_parse_atom(self):
        rows = parse_reddit_atom(ATOM)
        self.assertEqual(len(rows), 1)  # message trop court ignoré
        r = rows[0]
        self.assertEqual((r["Id"], r["Author"], r["Posted"]), ("t3_abc123", "diamondhands", "2026-09-26 10:30:00"))
        self.assertEqual(r["Text"], "[r/wallstreetbets] NVDA earnings play, who is in? — Loaded up on calls before earnings")
        with self.assertRaises(ValueError):
            parse_reddit_atom("<html><body>blocked</body></html>")

    def test_blocked_source_stops_early(self):
        calls = []

        def blocked(url):
            calls.append(url)
            raise PermissionError("403")

        with tempfile.TemporaryDirectory() as tmp:
            errors = collect_reddit(Path(tmp), ["NVDA", "AAPL", "MSFT", "TSLA"], log=lambda *a: None,
                                    fetch=blocked, sleep=lambda s: None)
        self.assertEqual(len(calls), 2)
        self.assertIn("collecte interrompue", errors[-1])

    def test_provider_uses_finbert_tone_and_neutral_account_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily").mkdir()
            write_stooq_csvs(MockDataProvider(history=400), root / "daily")
            collect_reddit(root, ["NVDA"], log=lambda *a: None, fetch=lambda url: ATOM, sleep=lambda s: None)
            score_titles(root, lambda texts: [{"positive": 0.7, "negative": 0.1, "neutral": 0.2} for _ in texts],
                         log=lambda *a: None)
            p = RealDataProvider(root)
            (post,) = p.social_posts("NVDA", datetime(2026, 1, 1))
            self.assertEqual((post.platform, post.author_age_days), ("Reddit", 365))  # inconnue : pas « récent »
            self.assertAlmostEqual(post.tone, 0.6)
            self.assertIn("1 messages Reddit", p.coverage())


if __name__ == "__main__":
    unittest.main()
