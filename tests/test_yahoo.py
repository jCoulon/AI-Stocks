import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from sp500_analyzer.providers.csv_prices import read_bars
from sp500_analyzer.providers.yahoo import (
    NEW_YORK, parse_chart, resample_10min, write_daily_csv, write_intraday_csv, yahoo_symbol,
)


def chart(timestamps, closes, adj=None):
    q = {"open": closes, "high": [c + 1 if c is not None else None for c in closes],
         "low": [c - 1 if c is not None else None for c in closes], "close": closes,
         "volume": [100] * len(closes)}
    ind = {"quote": [q]}
    if adj:
        ind["adjclose"] = [{"adjclose": adj}]
    return {"chart": {"result": [{"timestamp": timestamps, "indicators": ind}], "error": None}}


class YahooTests(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(yahoo_symbol("^GSPC"), "^GSPC")
        self.assertEqual(yahoo_symbol("SPX"), "^GSPC")
        self.assertEqual(yahoo_symbol("BRK.B"), "BRK-B")

    def test_parse_skips_incomplete_rows_and_reports_errors(self):
        rows = parse_chart(chart([1, 2, 3], [10.0, None, 12.0]))
        self.assertEqual([r[4] for r in rows], [10.0, 12.0])
        with self.assertRaises(ValueError):
            parse_chart({"chart": {"result": None, "error": {"description": "No data found"}}})

    def test_resample_5min_to_10min_regular_session(self):
        day = datetime(2026, 9, 21, 9, 25, tzinfo=NEW_YORK)  # 9h25 : pré-ouverture, ignorée
        stamps = [int((day + timedelta(minutes=5 * i)).timestamp()) for i in range(80)]  # 9h25 → 16h00
        closes = [100.0 + i for i in range(80)]
        bars = resample_10min(parse_chart(chart(stamps, closes)))
        self.assertEqual(len(bars), 39)  # 9h30 → 15h50 : 39 barres de 10 minutes
        first = bars[0]
        self.assertEqual(first.start.strftime("%H:%M"), "09:30")
        self.assertEqual((first.open, first.close, first.high, first.low, first.volume), (101.0, 102.0, 103.0, 100.0, 200))
        self.assertEqual(bars[-1].start.strftime("%H:%M"), "15:50")

    def test_csv_outputs_are_readable(self):
        day = datetime(2026, 9, 21, 9, 30, tzinfo=NEW_YORK)
        stamps = [int((day + timedelta(minutes=5 * i)).timestamp()) for i in range(4)]
        bars = resample_10min(parse_chart(chart(stamps, [1.0, 2.0, 3.0, 4.0])))
        with tempfile.TemporaryDirectory() as tmp:
            write_intraday_csv(Path(tmp) / "X.csv", bars)
            lines = (Path(tmp) / "X.csv").read_text().splitlines()
            self.assertEqual(lines[0], "Datetime,Open,High,Low,Close,Volume")
            self.assertTrue(lines[1].startswith("2026-09-21 09:30,1.0000"))
            write_daily_csv(Path(tmp) / "D.csv", [(date(2026, 9, 21), 1, 2, 0.5, 1.5, 10)])
            self.assertEqual(read_bars(Path(tmp) / "D.csv")[0].close, 1.5)

    def test_download_all_includes_extra_tickers(self):
        from unittest import mock
        from sp500_analyzer.providers import yahoo

        day = datetime(2026, 9, 21, 9, 30, tzinfo=NEW_YORK)
        payload = chart([int((day + timedelta(minutes=5 * i)).timestamp()) for i in range(4)], [1.0, 2.0, 3.0, 4.0])
        symbols = []

        def fake(url, *a, **kw):
            symbols.append(url.split("/chart/")[1].split("?")[0])
            return payload

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(yahoo, "_get_json", fake):
            errors = yahoo.download_all(tmp, date(2026, 9, 21), date(2026, 9, 21), pause=0, extra=("iren", "AAPL"))
            self.assertEqual(errors, [])
            self.assertTrue((Path(tmp) / "intraday_10min" / "2026-09" / "IREN.csv").exists())
            self.assertTrue((Path(tmp) / "daily" / "IREN.csv").exists())
        self.assertEqual(symbols.count("IREN"), 2)
        self.assertEqual(symbols.count("AAPL"), 2)  # déjà dans l'univers : pas de doublon


if __name__ == "__main__":
    unittest.main()
