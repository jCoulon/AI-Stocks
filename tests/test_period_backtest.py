import io
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sp500_analyzer.analysis.period_backtest import run_period_backtest
from sp500_analyzer.cli import main
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers import csv_prices
from sp500_analyzer.providers.csv_prices import CsvPriceProvider, download_stooq, read_bars
from sp500_analyzer.providers.pointintime import PointInTimeProvider

SEPT = (date(2026, 9, 1), date(2026, 9, 25))


def write_stooq_csvs(provider, folder: Path) -> None:
    """Exporte les cours d'un fournisseur au format CSV de Stooq."""
    for sec in [*provider.universe(), provider.index()]:
        name = "SPX" if sec.ticker == provider.index().ticker else sec.ticker
        lines = ["Date,Open,High,Low,Close,Volume"]
        lines += [f"{b.day.isoformat()},{b.open},{b.high},{b.low},{b.close},{b.volume}"
                  for b in provider.price_history(sec.ticker)]
        (folder / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TamperedFuture(MockDataProvider):
    """Fournisseur dont les cours postérieurs à `cut` sont falsifiés (x3)."""

    def __init__(self, cut: date, **kw):
        super().__init__(**kw)
        self.cut = cut

    def price_history(self, ticker):
        return [b if b.day <= self.cut else replace(b, open=b.open * 3, high=b.high * 3, low=b.low * 3,
                                                    close=b.close * 3)
                for b in super().price_history(ticker)]


class PointInTimeTests(unittest.TestCase):
    def test_hides_everything_after_the_date(self):
        base = MockDataProvider()
        day = date(2026, 9, 18)
        pit = PointInTimeProvider(base, day)
        cutoff = datetime(2026, 9, 18, 22)
        since = datetime(2026, 1, 1)
        self.assertEqual(pit.price_history("NVDA")[-1].day, day)
        self.assertTrue(all(n.published <= cutoff for n in pit.news("NVDA", since)))
        self.assertFalse(any("Nvidia shares jump" in n.headline for n in pit.news("NVDA", since)))  # news du 22/09
        self.assertTrue(all(p.posted <= cutoff for p in pit.social_posts("META", since)))
        self.assertTrue(all(d <= day for s in pit.macro().values() for d, _ in s))
        self.assertEqual(pit.trading_days()[-1], day)

    def test_calls_do_not_depend_on_future_prices(self):
        cut = date(2026, 9, 15)
        clean = run_period_backtest(MockDataProvider(history=400), date(2026, 9, 14), cut, horizons=(1,))
        tampered = run_period_backtest(TamperedFuture(cut, history=400), date(2026, 9, 14), cut, horizons=(1,))
        key = lambda r: [(c.day, c.ticker, round(c.score, 12)) for c in r.calls]  # noqa: E731
        self.assertEqual(key(clean), key(tampered))


class PeriodBacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_period_backtest(MockDataProvider(history=400), *SEPT, horizons=(1, 5))

    def test_signal_days_and_outcome_windows(self):
        r = self.report
        self.assertEqual(r.signal_days[0], date(2026, 8, 31))  # veille : l'avis couvre tout septembre
        self.assertNotIn(date(2026, 9, 7), r.signal_days)     # Labor Day
        self.assertEqual(len(r.signal_days), 18)
        five = next(s for s in r.stats if s.horizon == 5)
        self.assertEqual(five.dates, 14)  # la fenêtre de 5 séances doit rester dans septembre
        self.assertTrue(all(c.day <= date(2026, 9, 18) for c in r.calls if 5 in c.fwd))

    def test_metrics_are_consistent(self):
        for s in self.report.stats:
            self.assertTrue(-1 <= s.mean_ic <= 1)
            self.assertTrue(0 <= s.hit_rate <= 1 and 0 <= s.base_rate_up <= 1)
        self.assertEqual(len(self.report.first_calls), 30)
        spx = MockDataProvider(history=400).price_history("^GSPC")
        by_day = {b.day: b.close for b in spx}
        self.assertAlmostEqual(self.report.index_return, by_day[date(2026, 9, 25)] / by_day[date(2026, 8, 31)] - 1)


class CsvProviderTests(unittest.TestCase):
    def test_reads_stooq_and_yahoo_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "X.csv"
            p.write_text("Date,Open,High,Low,Close,Adj Close,Volume\n2026-09-02,10,11,9,10.5,10.4,100\n"
                         "2026-09-01,9,10,8,9.5,9.4,200\n2026-09-03,null,null,null,null,null,null\n")
            bars = read_bars(p)
            self.assertEqual([b.day.day for b in bars], [1, 2])
            self.assertEqual(bars[1].close, 10.5)

    def test_real_price_pipeline_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_stooq_csvs(MockDataProvider(history=400), Path(tmp))
            provider = CsvPriceProvider(tmp)
            self.assertEqual(len(provider.universe()), 30)
            self.assertEqual(provider.news("AAPL", datetime(2026, 1, 1)), [])
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--cours", tmp, "--backtest-periode", "2026-09-21:2026-09-25"])
            self.assertEqual(code, 0, err.getvalue())
            self.assertIn("Cours réels.", out.getvalue())
            self.assertIn("AVIS DU 18/09/2026", out.getvalue())

    def test_stooq_download(self):
        class Stub(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = b"Date,Open,High,Low,Close,Volume\n2026-09-25,1,2,0.5,1.5,10\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        original = csv_prices.STOOQ_URL
        csv_prices.STOOQ_URL = f"http://127.0.0.1:{srv.server_address[1]}/q/d/l/?s={{symbol}}&i=d"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                errors = download_stooq(tmp, tickers=["AAPL"])
                self.assertEqual(errors, [])
                self.assertEqual(read_bars(Path(tmp) / "AAPL.csv")[0].close, 1.5)
                self.assertTrue((Path(tmp) / "SPX.csv").exists())
        finally:
            csv_prices.STOOQ_URL = original
            srv.shutdown()
            srv.server_close()

    def test_missing_index_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                CsvPriceProvider(tmp)


if __name__ == "__main__":
    unittest.main()
