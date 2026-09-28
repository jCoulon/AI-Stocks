import io
import json
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sp500_analyzer.analysis.polymarket import (
    bet, build_report, calibration, monitor_rows, persistence, rank_wallets, render_html, render_text, wallet_stats,
)
from sp500_analyzer.cli import main
from sp500_analyzer.providers.polymarket import Market, Trade, parse_market, parse_trade

T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def synthetic(n_markets=90, seed=1):
    """Marchés binaires ; « sharp » achète l'issue gagnante à prix sous-évalué 70 % du temps,
    les autres parient au hasard au prix du marché."""
    rnd = random.Random(seed)
    markets, trades = {}, []
    for k in range(n_markets):
        cid = f"0x{k:04x}"
        end = T0 + timedelta(days=k)
        winner = rnd.randint(0, 1)
        markets[cid] = Market(cid, f"Question {k} ?", f"q-{k}", end, ("Yes", "No"), winner, 1e5,
                              "Politics" if k % 2 else "Sports", (1.0, 0.0) if winner == 0 else (0.0, 1.0))
        ts = int((end - timedelta(days=2, hours=rnd.randint(0, 5))).timestamp())
        pick = winner if rnd.random() < 0.7 else 1 - winner
        trades.append(Trade(ts, "0xsharp", "Sharp", cid, pick, "BUY", 0.5, 100))
        for w in range(30):
            p = rnd.uniform(0.2, 0.8)
            win = rnd.random() < p
            o = winner if win else 1 - winner
            trades.append(Trade(ts + w, f"0xw{w:02d}", "", cid, o, "BUY", p, 50))
    return markets, trades


class ParseTests(unittest.TestCase):
    def test_parse_market_with_json_strings(self):
        m = parse_market({"conditionId": "0xabc", "question": "Will X?", "slug": "x", "closed": True,
                          "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]',
                          "endDate": "2026-09-01T12:00:00Z", "volumeNum": 12345.6,
                          "events": [{"tags": [{"label": "Politics"}]}]})
        self.assertEqual((m.winner, m.outcomes, m.category), (1, ("Yes", "No"), "Politics"))
        self.assertEqual(m.end.year, 2026)
        open_m = parse_market({"conditionId": "0xdef", "closed": False, "outcomes": ["Yes", "No"],
                               "outcomePrices": ["0.62", "0.38"]})
        self.assertIsNone(open_m.winner)
        self.assertEqual(open_m.prices, (0.62, 0.38))
        self.assertIsNone(parse_market({"conditionId": "0x1", "outcomes": '["A","B","C"]'}))

    def test_parse_trade(self):
        t = parse_trade({"proxyWallet": "0xABC", "side": "buy", "conditionId": "0x1", "outcomeIndex": 0,
                         "price": 0.3, "size": 10, "timestamp": 1790000000, "pseudonym": "Fox"})
        self.assertEqual((t.wallet, t.side, t.name), ("0xabc", "BUY", "Fox"))
        self.assertIsNone(parse_trade({"side": "BUY"}))

    def test_bet_buy_and_sell(self):
        m = Market("c", "", "", T0, ("Yes", "No"), 0, 0, "X")
        self.assertEqual(bet(Trade(0, "w", "", "c", 0, "BUY", 0.25, 100), m), (0.25, 25.0, 75.0))
        # Vendre « Yes » à 0,25 = acheter « No » à 0,75, qui perd.
        self.assertEqual(bet(Trade(0, "w", "", "c", 0, "SELL", 0.25, 100), m), (0.75, 75.0, -75.0))


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.markets, self.trades = synthetic()

    def test_skilled_wallet_ranks_first_and_persists(self):
        ranked = rank_wallets(wallet_stats(self.trades, self.markets))
        self.assertEqual(ranked[0]["wallet"], "0xsharp")
        self.assertGreater(ranked[0]["z"], 3)
        p = persistence(self.trades, self.markets, top_n=1)
        self.assertTrue(p["ok"])
        self.assertGreater(p["top_mean_roi"], p["others_mean_roi"])

    def test_sweeper_is_not_ranked_as_skilled(self):
        trades = list(self.trades)
        for cid, m in self.markets.items():
            end = int(m.end.timestamp())
            # Achète l'issue gagnante à 0,98 juste avant la fin, puis à 0,999 une fois le résultat connu.
            trades.append(Trade(end - 600, "0xsweep", "", cid, m.winner, "BUY", 0.98, 5000))
            trades.append(Trade(end + 86400, "0xsweep", "", cid, m.winner, "BUY", 0.99, 50000))
        stats = wallet_stats(trades, self.markets)
        self.assertEqual(stats["0xsweep"]["orders"], len(self.markets))  # ordres tardifs exclus
        self.assertEqual(stats["0xsweep"]["win_rate"], 1.0)
        self.assertLess(stats["0xsweep"]["z"], stats["0xsharp"]["z"])
        self.assertEqual(rank_wallets(stats)[0]["wallet"], "0xsharp")

    def test_infer_category(self):
        from sp500_analyzer.providers.polymarket import infer_category
        self.assertEqual(infer_category("cfb-lsu-miss-2026-09-19", "LSU vs. Ole Miss"), "Sports")
        self.assertEqual(infer_category("x", "Will Bitcoin reach $150k?"), "Crypto")
        self.assertEqual(infer_category("x", "Will Magdalena Andersson be the next Prime Minister of Sweden?"), "Politique")
        self.assertEqual(infer_category("x", "Something else?"), "Autre")

    def test_calibration_matches_fair_prices(self):
        rows = calibration([t for t in self.trades if t.wallet != "0xsharp"], self.markets)
        for r in rows:
            if r["orders"] > 300:
                self.assertLess(abs(r["edge"]), 0.08, r)

    def test_report_render_and_monitor(self):
        r = build_report(self.markets, self.trades, T0 + timedelta(days=100))
        opened = {"0xopen": Market("0xopen", "Open question?", "open", T0 + timedelta(days=120), ("Yes", "No"),
                                   None, 1e4, "Crypto", (0.4, 0.6))}
        now = T0 + timedelta(days=100)
        recent = [Trade(int((now - timedelta(hours=3)).timestamp()), "0xsharp", "Sharp", "0xopen", 1, "SELL", 0.7, 10),
                  Trade(int((now - timedelta(days=20)).timestamp()), "0xsharp", "", "0xopen", 0, "BUY", 0.3, 10)]
        r["monitor"] = monitor_rows(recent, opened, {s["wallet"]: s for s in r["top"]}, now)
        r["monitor_at"] = "2026-10-09 12:00"
        self.assertEqual(len(r["monitor"]), 1)  # l'ordre de 20 jours est ignoré
        m = r["monitor"][0]
        self.assertEqual((m["outcome"], round(m["paid"], 2), m["now"]), ("Yes", 0.3, 0.4))
        html = render_html(json.loads(json.dumps(r, default=str)))
        self.assertIn("Polymarket", html)
        self.assertIn("0xsharp", html)
        self.assertIn("Open question?", html)
        self.assertIn("pas un conseil", html)
        self.assertIn("POLYMARKET", render_text(r))
        self.assertIn("Aucune donnée", render_html(None))

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "polymarket").mkdir()
            (Path(tmp) / "polymarket" / "report.json").write_text(json.dumps(r, default=str))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--polymarket", "--donnees", tmp]), 0)
            self.assertIn("0xsharp", out.getvalue())


if __name__ == "__main__":
    unittest.main()
