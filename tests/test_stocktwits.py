import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sp500_analyzer.analysis.sentiment import social_score
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.providers.stocktwits import collect_stocktwits, load_posts, parse_stream
from tests.test_period_backtest import write_stooq_csvs


def stream(*messages):
    return json.dumps({"response": {"status": 200}, "messages": list(messages)})


def msg(i, when, text, sentiment=None, joined="2020-01-01", likes=3):
    return {"id": i, "body": text, "created_at": when,
            "user": {"username": f"user{i}", "join_date": joined, "followers": 10},
            "likes": {"total": likes}, "entities": {"sentiment": {"basic": sentiment} if sentiment else None}}


class StockTwitsTests(unittest.TestCase):
    def test_parse_new_york_time_and_labels(self):
        rows = parse_stream(stream(msg(1, "2026-09-25T19:30:00Z", "$NVDA  breaking out\\nhard", "Bullish")))
        self.assertEqual(rows[0]["Posted"], "2026-09-25 15:30:00")  # 19h30 UTC = 15h30 à New York (été)
        self.assertEqual((rows[0]["Sentiment"], rows[0]["Text"]), ("Bullish", "$NVDA breaking out\\nhard"))
        with self.assertRaises(ValueError):
            parse_stream(json.dumps({"response": {"status": 429}, "errors": [{"message": "Rate limit"}]}))

    def test_collection_accumulates_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = stream(msg(1, "2026-09-25T19:30:00Z", "$NVDA to the moon", "Bullish"))
            second = stream(msg(1, "2026-09-25T19:30:00Z", "$NVDA to the moon", "Bullish"),
                            msg(2, "2026-09-26T14:00:00Z", "$NVDA guidance looks weak", "Bearish", joined="2026-09-20"))
            collect_stocktwits(root, ["NVDA"], log=lambda *a: None, fetch=lambda url: first)
            collect_stocktwits(root, ["NVDA"], log=lambda *a: None, fetch=lambda url: second)
            posts = load_posts(root / "social" / "stocktwits" / "NVDA.csv", "NVDA")
            self.assertEqual([p.tone for p in posts], [1.0, -1.0])
            self.assertEqual(posts[1].author_age_days, 6)  # compte créé 6 jours avant le message
            errors = collect_stocktwits(root, ["NVDA"], log=lambda *a: None, fetch=lambda url: "<html>blocked</html>")
            self.assertEqual(len(errors), 1)
            self.assertEqual(len(load_posts(root / "social" / "stocktwits" / "NVDA.csv", "NVDA")), 2)  # conservés

    def test_provider_serves_posts_and_labels_drive_the_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily").mkdir()
            write_stooq_csvs(MockDataProvider(history=400), root / "daily")
            collect_stocktwits(root, ["NVDA"], log=lambda *a: None, fetch=lambda url: stream(
                msg(1, "2026-09-24T15:00:00Z", "$NVDA holding here", "Bearish"),
                msg(2, "2026-09-25T15:00:00Z", "$NVDA great quarter", "Bullish", likes=0)))
            p = RealDataProvider(root)
            posts = p.social_posts("NVDA", datetime(2026, 9, 25))
            self.assertEqual([x.author for x in posts], ["user2"])
            self.assertEqual(p.social_posts("AAPL", datetime(2026, 1, 1)), [])
            self.assertIn("2 messages StockTwits", p.coverage())
            score, _ = social_score(p.social_posts("NVDA", datetime(2026, 1, 1)))
            self.assertLess(score, 0)  # le message baissier a plus de likes : le score suit les étiquettes


if __name__ == "__main__":
    unittest.main()
