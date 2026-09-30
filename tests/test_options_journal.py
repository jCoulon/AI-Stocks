import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from sp500_analyzer.analysis.besttry import BestTryRow
from sp500_analyzer.analysis.journal import read, record, render_html, render_text, score
from sp500_analyzer.cli import main
from sp500_analyzer.providers.events import Event
from sp500_analyzer.providers.options import (
    atm_straddles, download_options, implied_event_move, parse_nasdaq_chain, parse_yahoo_chain,
)

TODAY = date(2026, 9, 30)
NASDAQ = {"data": {"table": {"rows": [
    {"expirygroup": "October 2, 2026", "strike": None},
    {"expirygroup": "", "expiryDate": "Oct 2", "strike": "95.00", "c_Bid": "5.9", "c_Ask": "6.1", "c_Last": "6",
     "p_Bid": "0.9", "p_Ask": "1.1", "p_Last": "1"},
    {"expirygroup": "", "expiryDate": "Oct 2", "strike": "100.00", "c_Bid": "1.9", "c_Ask": "2.1", "c_Last": "2",
     "p_Bid": "1.9", "p_Ask": "2.1", "p_Last": "2"},
    {"expirygroup": "November 20, 2026", "strike": None},
    {"expirygroup": "", "expiryDate": "Nov 20", "strike": "100.00", "c_Bid": "--", "c_Ask": "--", "c_Last": "7.5",
     "p_Bid": "7.4", "p_Ask": "7.6", "p_Last": "7"},
]}}}


class OptionsTests(unittest.TestCase):
    def test_parse_nasdaq_and_straddles(self):
        rows = parse_nasdaq_chain(NASDAQ, TODAY)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["expiry"], date(2026, 11, 20))
        self.assertEqual(rows[-1]["call"], 7.5)  # pas de fourchette : dernier prix
        st = atm_straddles(rows, 100.4)
        self.assertEqual([s["expiry"] for s in st], ["2026-10-02", "2026-11-20"])
        self.assertAlmostEqual(st[0]["straddle"], 4.0)
        self.assertAlmostEqual(st[1]["move"], 15.0 / 100.4)

    def test_parse_yahoo(self):
        spot, rows = parse_yahoo_chain({"optionChain": {"result": [{
            "quote": {"regularMarketPrice": 50}, "options": [{"expirationDate": 1793318400,
                                                               "calls": [{"strike": 50, "bid": 2, "ask": 2.2}],
                                                               "puts": [{"strike": 50, "bid": 1.8, "ask": 2}]}]}]}})
        self.assertEqual(spot, 50)
        self.assertAlmostEqual(rows[0]["call"] + rows[0]["put"], 4.0)

    def test_implied_event_move_removes_ordinary_days(self):
        k = math.sqrt(2 / math.pi)
        daily = 0.02
        # Échéance avant l'événement : 5 séances ordinaires ; après : 10 séances + un événement de σ 8 %.
        pre = k * daily * math.sqrt(5)
        post = k * math.sqrt(10 * daily ** 2 + 0.08 ** 2)
        snap = {"fetched": "2026-09-30", "straddles": [
            {"expiry": "2026-10-07", "move": pre}, {"expiry": "2026-10-15", "move": post}]}
        im = implied_event_move(snap, date(2026, 10, 12), date(2026, 9, 30), None)
        self.assertEqual(im["expiry"], "2026-10-15")
        self.assertEqual(im["daily_source"], "implicite")
        self.assertAlmostEqual(im["event_move"], k * 0.08, places=4)  # 11 séances dont le jour de l'événement
        self.assertIsNone(implied_event_move(snap, date(2026, 12, 1), date(2026, 9, 30), 0.02))
        # Cotations incohérentes (échéance après l'événement moins chère que les séances ordinaires).
        bad = {"fetched": "2026-09-30", "straddles": [{"expiry": "2026-10-07", "move": 0.05},
                                                       {"expiry": "2026-10-15", "move": 0.05}]}
        self.assertIsNone(implied_event_move(bad, date(2026, 10, 12), date(2026, 9, 30), None)["event_move"])

    def test_download_writes_snapshot_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = download_options(Path(tmp), {"AAA": 100.4, "BBB": 10.0}, TODAY, pause=0, log=lambda *_: None,
                                      get=lambda url: json.dumps(NASDAQ))
            self.assertEqual(len(errors), 1)  # BBB : aucun prix d'exercice proche de 10
            snap = json.loads((Path(tmp) / "options" / "AAA.json").read_text())
            self.assertEqual(snap["spot"], 100.4)
            self.assertIn("2026-11-20", (Path(tmp) / "options" / "history.csv").read_text())
            self.assertTrue((Path(tmp) / "options" / "_echantillon.json").exists())

    def test_pricing_label(self):
        ev = Event("X", date(2026, 11, 1), "resultats", "Résultats")
        row = BestTryRow("X", "X", "", 10, ev, 30, 0.04, 0.15)
        self.assertEqual(row.pricing, "")
        row.implied_move = 0.10
        self.assertEqual(row.pricing, "sous-évalué")
        row.implied_move = 0.20
        self.assertEqual(row.pricing, "surévalué")
        row.implied_move = 0.14
        self.assertEqual(row.pricing, "cohérent")


def fake_report(day, prices, scores):
    tickers = [SimpleNamespace(security=SimpleNamespace(ticker=t), last_close=prices[t],
                               short=SimpleNamespace(score=scores[t], label="x"),
                               medium=SimpleNamespace(score=scores[t], label="x")) for t in prices]
    return SimpleNamespace(tickers=tickers, as_of=day)


class JournalTests(unittest.TestCase):
    def test_record_replace_and_score(self):
        tickers = [f"T{i}" for i in range(8)]
        d0 = date(2026, 1, 5)
        days = [d0 + timedelta(days=i) for i in range(40)]
        # Titre i : rendement quotidien proportionnel à i ; score = i -> IC parfait.
        closes = {t: [(d, 100 * (1 + 0.001 * i) ** k) for k, d in enumerate(days)] for i, t in enumerate(tickers)}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for k, d in enumerate(days[:25]):
                prices = {t: closes[t][k][1] for t in tickers}
                views = {"T7": SimpleNamespace(verdict="Zone d'entrée technique", support=1.0, stop=0.9, resistance=2.0)}
                ev = BestTryRow("T7", "T7", "", 1, Event("T7", days[30], "resultats", "R"), 5, 0.02, 0.1,
                                implied_move=0.05)
                record(root, d, fake_report(d, prices, {t: float(i) for i, t in enumerate(tickers)}), views,
                       {"T7": ev}, "now")
            record(root, days[0], fake_report(days[0], {t: 1.0 for t in tickers}, {t: 0.0 for t in tickers}), {}, {}, "again")
            rows = read(root)
            self.assertEqual(len(rows), 25 * 8)  # la séance réenregistrée remplace l'ancienne
            s = score(rows, closes)
            short = s["scores"][0]
            self.assertGreater(short.value, 0.9)
            self.assertGreater(s["scores"][2].value, 0)  # T7, en « zone », a le meilleur rendement
            self.assertEqual(s["events"]["n"], 1)
            self.assertEqual(s["events"]["scored_implied"], 1)
            self.assertIn("JOURNAL DES PRÉVISIONS", render_text(s))
            self.assertIn("Journal des prévisions", render_html(s))
            self.assertIn("Journal vide", render_text(score([], {})))

    def test_cli_journal_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "daily").mkdir()
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--journal", "--donnees", tmp]), 0)
            self.assertIn("Journal vide", out.getvalue())


if __name__ == "__main__":
    unittest.main()
