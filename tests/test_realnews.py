import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sp500_analyzer.analysis.sentiment import analyze_sentiment
from sp500_analyzer.cli import main
from sp500_analyzer.models import NewsItem
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers.pointintime import PointInTimeProvider
from sp500_analyzer.providers.realdata import RealDataProvider
from sp500_analyzer.providers.realnews import (
    http_get, parse_fred_csv, parse_gdelt, publication_dated, sec_rows, source_for_domain, to_news_rows,
    write_news_csv,
)
from tests.test_period_backtest import write_stooq_csvs


def article(title, domain, seen):
    return {"title": title, "domain": domain, "seendate": seen, "url": f"https://{domain}/a", "language": "English"}


class GdeltTests(unittest.TestCase):
    def test_parse_rejects_text_messages(self):
        self.assertEqual(parse_gdelt('{"articles": [{"title": "x"}]}'), [{"title": "x"}])
        self.assertEqual(parse_gdelt("{}"), [])
        self.assertEqual(parse_gdelt(""), [])
        with self.assertRaises(ValueError):
            parse_gdelt("Please limit requests to one every 5 seconds")

    def test_known_sources_new_york_time_and_dedup(self):
        self.assertEqual(source_for_domain("www.reuters.com"), "Reuters")
        self.assertEqual(source_for_domain("finance.yahoo.com"), "Yahoo Finance")
        self.assertIsNone(source_for_domain("randomblog.net"))
        self.assertIsNone(source_for_domain("notreuters.com"))
        rows = to_news_rows([
            article("Nvidia shares jump after record results", "reuters.com", "20260826T210500Z"),
            article("Nvidia Shares Jump After Record Results", "cnbc.com", "20260826T203000Z"),  # reprise
            article("Nvidia to the moon, insiders say", "randomblog.net", "20260826T200000Z"),  # inconnue
            article("Short", "reuters.com", "20260826T200000Z"),
        ])
        self.assertEqual(len(rows), 1)
        published, source, _, title, _ = rows[0]
        self.assertEqual((source, published), ("CNBC", datetime(2026, 8, 26, 16, 30)))  # 20h30 UTC = 16h30 NY (été)

    def test_download_stops_when_gdelt_is_down_and_resumes(self):
        from unittest import mock
        from sp500_analyzer.providers import realnews

        calls = []

        def down(query, start, end):
            calls.append(query)
            raise TimeoutError("timed out")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(realnews, "gdelt_articles", down):
            errors = realnews.download_news(Path(tmp), ["NVDA", "AAPL"], date(2026, 7, 1), date(2026, 9, 25),
                                            pause=0, max_consecutive_failures=3, log=lambda *a: None)
            self.assertEqual(len(calls), 3)  # arrêt après 3 échecs d'affilée, sans parcourir AAPL
            self.assertIn("GDELT inaccessible", errors[-1])
            write_news_csv(Path(tmp) / "news" / "NVDA.csv", [])
            ok = []
            with mock.patch.object(realnews, "gdelt_articles", lambda q, s, e: ok.append(q) or []):
                realnews.download_news(Path(tmp), ["NVDA", "AAPL"], date(2026, 9, 1), date(2026, 9, 25),
                                       pause=0, resume=True, log=lambda *a: None)
            self.assertEqual(set(ok), {realnews.GDELT_QUERIES["AAPL"]})  # NVDA déjà présent : ignoré
            self.assertTrue((Path(tmp) / "news" / "AAPL.csv").exists())


class SecTests(unittest.TestCase):
    def test_filings_since_start_with_items(self):
        subs = {"filings": {"recent": {
            "form": ["8-K", "4", "10-Q", "8-K"],
            "acceptanceDateTime": ["2026-08-27T16:05:10.000Z", "2026-08-20T18:00:00.000Z",
                                   "2026-08-20T08:00:00.000Z", "2025-12-01T09:00:00.000Z"],
            "items": ["2.02,9.01", "", "", "5.02"],
            "accessionNumber": ["0001045810-26-000100", "x", "0001045810-26-000090", "y"],
            "primaryDocument": ["nvda-8k.htm", "", "nvda-10q.htm", ""],
        }}}
        rows = sec_rows(subs, 1045810, date(2026, 1, 1))
        self.assertEqual([r[1] for r in rows], ["10-Q", "8-K"])  # formulaire 4 ignoré, 2025 exclu
        accepted, form, items, title, url = rows[1]
        self.assertEqual(accepted, datetime(2026, 8, 27, 16, 5, 10))  # heure de l'Est
        self.assertEqual(items, "2.02 9.01")
        self.assertEqual(title, "Dépôt SEC 8-K : résultats trimestriels")
        self.assertEqual(url, "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000100/nvda-8k.htm")


class FredTests(unittest.TestCase):
    def test_parse_and_publication_dates(self):
        body = "observation_date,CPIAUCSL\n2025-07-01,300.0\n2025-08-01,301.0\n2026-07-01,309.0\n2026-08-01,.\n"
        obs = parse_fred_csv(body)
        self.assertEqual(len(obs), 3)
        cpi = publication_dated(obs, "yoy", "monthly:16")
        self.assertEqual(cpi, [(date(2026, 8, 16), 3.0)])  # CPI de juillet connu mi-août
        dec = publication_dated([(date(2025, 12, 1), 4.4)], "level", "monthly:10")
        self.assertEqual(dec, [(date(2026, 1, 10), 4.4)])
        ff = publication_dated([(date(2026, 9, 24), 3.88)], "level", "daily:1")
        self.assertEqual(ff, [(date(2026, 9, 25), 3.88)])

    def test_http_get_retries_on_rate_limit_message(self):
        calls = []

        class Stub(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                calls.append(self.path)
                body = (b"Please limit requests" if len(calls) == 1 else b'{"articles": []}')
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            body = http_get(f"http://127.0.0.1:{srv.server_address[1]}/x", sleep=lambda s: None,
                            retry_if=lambda b: b.startswith("Please limit"))
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(json.loads(body), {"articles": []})
        self.assertEqual(len(calls), 2)


class RealDataProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "daily").mkdir()
        write_stooq_csvs(MockDataProvider(history=400), root / "daily")
        (root / "news").mkdir()
        write_news_csv(root / "news" / "NVDA.csv", [
            (datetime(2026, 9, 17, 9, 0), "Reuters", "reuters.com", "Nvidia shares surge on record demand", "u1"),
            (datetime(2026, 9, 23, 18, 0), "CNBC", "cnbc.com", "Nvidia plunges after weak guidance", "u2"),
        ])
        write_news_csv(root / "news" / "MARCHE.csv", [
            (datetime(2026, 9, 18, 14, 0), "Reuters", "reuters.com", "Wall Street rallies as Fed cuts rates", "u3")])
        (root / "sec").mkdir()
        (root / "sec" / "NVDA.csv").write_text(
            "Published,Form,Items,Title,Url\n2026-09-18 16:05:10,8-K,2.02 9.01,Dépôt SEC 8-K : résultats trimestriels,u\n")
        (root / "macro").mkdir()
        (root / "macro" / "vix.csv").write_text("Date,Value\n2026-09-24,16.5\n2026-09-25,15.9\n")
        cls.root = root
        cls.provider = RealDataProvider(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reads_all_sources(self):
        p = self.provider
        nvda = p.news("NVDA", datetime(2026, 1, 1))
        self.assertEqual([n.source for n in nvda], ["Reuters", "SEC EDGAR", "CNBC"])  # triées par date
        self.assertEqual(len(p.news("NVDA", datetime(2026, 9, 20))), 1)
        self.assertEqual(p.news(None, datetime(2026, 1, 1))[0].headline, "Wall Street rallies as Fed cuts rates")
        self.assertEqual(p.news("AAPL", datetime(2026, 1, 1)), [])
        self.assertEqual(p.macro(), {"vix": [(date(2026, 9, 24), 16.5), (date(2026, 9, 25), 15.9)]})
        self.assertEqual(p.news_start, date(2026, 9, 17))
        self.assertIn("3 articles de presse", p.coverage())
        self.assertIn("1 dépôts SEC", p.coverage())

    def test_point_in_time_hides_later_news(self):
        pit = PointInTimeProvider(self.provider, date(2026, 9, 18))
        self.assertEqual([n.source for n in pit.news("NVDA", datetime(2026, 1, 1))], ["Reuters", "SEC EDGAR"])
        self.assertEqual(pit.macro()["vix"], [])

    def test_sec_filings_do_not_dilute_sentiment(self):
        now = datetime(2026, 9, 18, 22)
        press = [NewsItem("NVDA", datetime(2026, 9, 17, 9), "Reuters", "Nvidia shares surge on record demand")]
        filing = [NewsItem("NVDA", datetime(2026, 9, 18, 16), "SEC EDGAR", "Dépôt SEC 8-K : résultats trimestriels")]
        a, _, _ = analyze_sentiment(press, [], now)
        b, _, _ = analyze_sentiment(press + filing, [], now)
        self.assertAlmostEqual(a.signals[0].value, b.signals[0].value)
        self.assertGreater(a.signals[0].value, 0)

    def test_cli_backtest_with_real_data_folder(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--donnees", str(self.root), "--backtest-periode", "2026-09-21:2026-09-25"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("Données réelles : cours ; 3 articles de presse", out.getvalue())


if __name__ == "__main__":
    unittest.main()
