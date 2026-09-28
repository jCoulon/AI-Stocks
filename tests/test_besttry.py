import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path

from sp500_analyzer.analysis.besttry import build_rows, earnings_reactions, html_besttry, rank, render_besttry
from sp500_analyzer.cli import main
from sp500_analyzer.models import Bar
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.providers.events import (
    Event, download_events, load_calendar, parse_earnings_date, parse_surprise_dates, ticker_events,
)
from tests.test_period_backtest import write_stooq_csvs


def bars(closes, d0=date(2026, 1, 1)):
    return [Bar(d0 + timedelta(days=i), c, c, c, c, 1000) for i, c in enumerate(closes)]


EARNINGS_DATE = {"data": {"announcement": "Earnings announcement* for NVDA: Nov 19, 2026",
                          "reportText": "NVIDIA Corporation is estimated to report earnings on 11/19/2026 after "
                                        "market close. The report will be for the fiscal Quarter ending Oct 2026."}}
SURPRISE = {"data": {"earningsSurpriseTable": {"rows": [
    {"fiscalQtrEnd": "Jul 2026", "dateReported": "8/26/2026", "eps": 1.1},
    {"fiscalQtrEnd": "Apr 2026", "dateReported": "5/27/2026", "eps": 0.9}]}}}


class ParsingTests(unittest.TestCase):
    def test_earnings_date(self):
        self.assertEqual(parse_earnings_date(EARNINGS_DATE),
                         {"date": "2026-11-19", "estimated": True, "timing": "après clôture"})
        confirmed = {"data": {"announcement": "Earnings announcement for X: Oct 5, 2026",
                              "reportText": "X is expected to report earnings on 10/05/2026 before market open."}}
        self.assertEqual(parse_earnings_date(confirmed),
                         {"date": "2026-10-05", "estimated": False, "timing": "avant ouverture"})
        self.assertIsNone(parse_earnings_date({"data": {"announcement": "N/A"}}))
        self.assertIsNone(parse_earnings_date({"data": None}))

    def test_surprise_dates(self):
        self.assertEqual(parse_surprise_dates(SURPRISE), ["2026-05-27", "2026-08-26"])
        self.assertEqual(parse_surprise_dates({"data": None}), [])

    def test_download_keeps_past_dates_and_stops_when_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "events").mkdir()
            (root / "events" / "NVDA.json").write_text(json.dumps({"past_earnings": ["2026-02-25"]}))

            def get(url):
                return json.dumps(EARNINGS_DATE if "earnings-date" in url else SURPRISE)

            errors = download_events(root, ["NVDA"], pause=0, log=lambda *_: None, get=get, today=date(2026, 9, 28))
            self.assertEqual(errors, [])
            data = json.loads((root / "events" / "NVDA.json").read_text())
            self.assertEqual(data["past_earnings"], ["2026-02-25", "2026-05-27", "2026-08-26"])
            self.assertEqual(data["next_earnings"]["date"], "2026-11-19")
            self.assertEqual(data["fetched"], "2026-09-28")

            def refuse(url):
                raise OSError("403")

            errors = download_events(root, ["A", "B", "C", "D"], pause=0, log=lambda *_: None, get=refuse)
            self.assertIn("arrêt", errors[-1])
            self.assertEqual(len(errors), 4)

    def test_calendar_and_ticker_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "events").mkdir()
            (root / "events" / "calendar.csv").write_text(
                "# commentaire\nDate,Ticker,Event,Note\n2026-10-28,MARCHE,Fed,taux\n2026-10-15,cbrs,Journée investisseurs,\n"
                "2026-09-29,OPENAI,DevDay,keynote\n")
            (root / "events" / "CBRS.json").write_text(json.dumps({
                "past_earnings": ["2026-06-24", "2026-08-12"],
                "next_earnings": {"date": "2026-11-12", "estimated": True, "timing": ""}}))
            cal = load_calendar(root)
            self.assertEqual([(e.ticker, e.kind) for e in cal],
                             [("MARCHE", "marche"), ("CBRS", "autre"), ("OPENAI", "autre")])
            evs = ticker_events(root, "CBRS", date(2026, 5, 14), date(2024, 9, 26), date(2026, 9, 25))
            self.assertEqual([(e.day, e.kind) for e in evs], [
                (date(2026, 9, 29), "lie"), (date(2026, 10, 15), "autre"), (date(2026, 11, 10), "lockup"), (date(2026, 11, 12), "resultats")])
            self.assertFalse(evs[-1].confirmed)
            self.assertEqual(evs[0].label, "[OpenAI] DevDay")
            self.assertIn("poids 50%", evs[0].note)
            # Revu au 1er août : la publication du 12/08 était à venir ; la prochaine date (trop proche
            # d'une date passée déjà listée) n'est pas doublée.
            evs = ticker_events(root, "CBRS", date(2026, 5, 14), date(2024, 9, 26), date(2026, 8, 1))
            self.assertIn((date(2026, 8, 12), "resultats"), [(e.day, e.kind) for e in evs])
            # Titre coté depuis le début de l'historique : pas de lock-up.
            self.assertFalse([e for e in ticker_events(root, "NVDA", date(2024, 9, 26), date(2024, 9, 26),
                                                       date(2026, 9, 25)) if e.kind == "lockup"])


class ScreenTests(unittest.TestCase):
    def test_earnings_reactions_window(self):
        b = bars([100] * 10 + [100, 120, 110] + [110] * 10)  # publication le 12e jour (index 11)
        # veille (index 10, 100) -> lendemain (index 12, 110)
        self.assertAlmostEqual(earnings_reactions(b, [date(2026, 1, 12)])[0], 0.10)
        self.assertEqual(earnings_reactions(b, [date(2025, 1, 1), date(2027, 1, 1)]), [])

    def test_rows_rank_and_render(self):
        closes = [100 + i % 3 for i in range(200)]
        closes[100], closes[101] = 130, 125  # forte réaction à la publication du jour 100
        b = bars(closes)
        as_of = b[-1].day
        ev = Event("X", as_of + timedelta(days=10), "resultats", "Résultats trimestriels", True, "après clôture")
        lock = Event("X", as_of + timedelta(days=90), "lockup", "Fin du lock-up (estimée)", False)
        rows = build_rows("X", "X Corp", "Puces", b, [ev, lock], as_of, 60, [b[100].day],
                          {"short_float": 0.25}, "lié à OpenAI")
        self.assertEqual(len(rows), 1)  # lock-up hors horizon
        r = rows[0]
        self.assertAlmostEqual(r.past_moves[0], 125 / 100 - 1, places=3)
        self.assertGreater(r.multiple, 5)
        self.assertFalse(r.estimated_move)
        self.assertTrue(any("vente à découvert 25%" in f for f in r.flags))

        other = build_rows("Y", "Y", "", b, [Event("Y", as_of + timedelta(days=3), "resultats", "Résultats")],
                           as_of, 60, [])
        self.assertTrue(other[0].estimated_move)
        ranked = rank(other + rows)
        self.assertEqual(ranked[0].ticker, "X")
        text = render_besttry(ranked, as_of, 60, [Event("MARCHE", as_of + timedelta(days=5), "marche", "Fed")])
        self.assertIn("BEST TRY", text)
        self.assertIn("Fed", text)
        html = html_besttry(ranked, as_of, 60, [], "2026-09-28")
        self.assertIn('data-ticker="X"', html)
        self.assertIn("pas un conseil", html)
        self.assertIn("comme</strong> à la baisse", html)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily").mkdir()
            provider = MockDataProvider(history=400)
            write_stooq_csvs(provider, root / "daily")
            (root / "events").mkdir()
            last = provider.as_of
            (root / "events" / "NVDA.json").write_text(json.dumps({
                "fetched": "2026-09-28", "past_earnings": [(last - timedelta(days=90)).isoformat()],
                "next_earnings": {"date": (last + timedelta(days=20)).isoformat(), "estimated": False,
                                  "timing": "après clôture"}}))
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = main(["--donnees", str(root), "--best-try"])
            self.assertEqual(code, 0)
            self.assertIn("NVDA", out.getvalue())
            self.assertIn("Résultats trimestriels", out.getvalue())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--best-try"]), 2)


if __name__ == "__main__":
    unittest.main()
