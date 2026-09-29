import json
import unittest
import urllib.error
import urllib.request

from sp500_analyzer.app.server import AppServer, AppState


class AppServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = AppServer(AppState()).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def request(self, path, token=True, method="GET", body=None, host=None):
        headers = {"X-App-Token": self.server.token} if token else {}
        if host:
            headers["Host"] = host
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.server.url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def test_ui_is_served_with_assets_inlined(self):
        status, _, page = self.request("/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.server.token, page)
        self.assertIn("window.initCharts", page)
        self.assertIn("--series-1", page)
        for placeholder in ("/*REPORT_CSS*/", "/*CHART_JS*/", "__TOKEN__"):
            self.assertNotIn(placeholder, page)

    def test_api_requires_token(self):
        for path in ("/api/summary", "/api/market", "/api/stock/AAPL", "/api/export"):
            self.assertEqual(self.request(path, token=False)[0], 403, path)
        self.assertEqual(self.request("/api/refresh", token=False, method="POST", body={})[0], 403)

    def test_foreign_host_rejected(self):
        # Protection contre le DNS rebinding : même avec le jeton, un Host étranger est refusé.
        self.assertEqual(self.request("/", host=f"evil.example:{self.server.port}")[0], 403)
        self.assertEqual(self.request("/api/summary", host="evil.example")[0], 403)

    def test_summary_and_fragments(self):
        status, _, body = self.request("/api/summary")
        summary = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(summary["tickers"]), 30)
        self.assertIn("PAS un conseil", summary["disclaimer"])
        meta = next(t for t in summary["tickers"] if t["ticker"] == "META")
        self.assertEqual(meta["alerts"], 3)
        status, _, market = self.request("/api/market")
        self.assertIn('data-ticker="UNH"', market)
        self.assertIn("Équipe d'agents", market)
        status, _, stock = self.request("/api/stock/unh")
        self.assertEqual(status, 200)
        self.assertIn("UNH", stock)
        self.assertIn("pricechart", stock)
        self.assertEqual(self.request("/api/stock/XYZ")[0], 404)

    def test_export_is_a_download(self):
        status, headers, body = self.request("/api/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertTrue(body.startswith("<!doctype html>"))

    def test_refresh_changes_dataset(self):
        before = json.loads(self.request("/api/summary")[2])
        status, _, body = self.request("/api/refresh", method="POST", body={"seed": 7, "as_of": "2026-09-25"})
        after = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(after["seed"], 7)
        self.assertNotEqual([t["close"] for t in before["tickers"]], [t["close"] for t in after["tickers"]])
        self.request("/api/refresh", method="POST", body={"seed": 42})

    def test_refresh_rejects_bad_parameters(self):
        status, _, body = self.request("/api/refresh", method="POST", body={"as_of": "pas-une-date"})
        self.assertEqual(status, 400)
        self.assertIn("paramètres invalides", json.loads(body)["error"])


if __name__ == "__main__":
    unittest.main()


class RealDataAppTests(unittest.TestCase):
    """Application sur des données réelles (dossier data/ fictif) avec le focus IA."""

    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        from pathlib import Path

        from sp500_analyzer.providers import MockDataProvider
        from sp500_analyzer.providers.realdata import RealDataProvider
        from tests.test_period_backtest import write_stooq_csvs

        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "daily").mkdir()
        write_stooq_csvs(MockDataProvider(history=400), root / "daily")
        shutil.copy(root / "daily" / "AAPL.csv", root / "daily" / "NBIS.csv")  # cours fictifs d'un titre IA
        (root / "fundamentals").mkdir()
        for t in ("NBIS", "NVDA", "AMD"):
            last = RealDataProvider(root, universe="ia").price_history(t)[-1].close
            (root / "fundamentals" / f"{t}.json").write_text(json.dumps({
                "fetched": "2026-09-28", "source": "Nasdaq", "target_mean": last * 1.3, "target_high": last * 2,
                "target_low": last * 0.8, "analysts": 9, "revenue_growth": 0.4, "ev_to_revenue": 10.0}))
        (root / "events").mkdir()
        (root / "events" / "NBIS.json").write_text(json.dumps({
            "fetched": "2026-09-28", "past_earnings": ["2026-08-06"],
            "next_earnings": {"date": "2026-10-29", "estimated": True, "timing": ""}}))
        from datetime import datetime, timezone

        from sp500_analyzer.analysis.polymarket import build_report
        from tests.test_polymarket import synthetic
        (root / "polymarket").mkdir()
        (root / "polymarket" / "report.json").write_text(
            json.dumps(build_report(*synthetic(), datetime(2026, 10, 1, tzinfo=timezone.utc)), default=str))
        cls.server = AppServer(AppState(data_dir=root)).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.tmp.cleanup()

    request = AppServerTests.request

    def test_real_data_ai_universe_and_asymmetry(self):
        s = json.loads(self.request("/api/summary")[2])
        self.assertEqual((s["source"], s["universe"], s["real_available"]), ("reel", "tout", True))
        tickers = {t["ticker"]: t for t in s["tickers"]}
        self.assertIn("NBIS", tickers)
        self.assertEqual(tickers["NBIS"]["theme"], "Néocloud")
        self.assertIsNone(tickers["KO"]["theme"])
        self.assertTrue(s["asymmetry"])
        status, _, html = self.request("/api/asymmetry")
        self.assertEqual(status, 200)
        self.assertIn("Écran d'asymétrie", html)
        self.assertIn('data-ticker="NBIS"', html)
        self.assertIn("pas un conseil", html)

        status, _, body = self.request("/api/refresh", method="POST", body={"universe": "ia"})
        s = json.loads(body)
        self.assertEqual(status, 200, body)
        self.assertEqual(s["universe_label"], "Focus IA")
        self.assertNotIn("KO", {t["ticker"] for t in s["tickers"]})

        # Séance antérieure : vue point-in-time des données réelles.
        s = json.loads(self.request("/api/refresh", method="POST", body={"as_of": "2026-09-18"})[2])
        self.assertEqual(s["as_of"], "2026-09-18")

        # Retour aux données simulées : S&P 500 seulement, pas d'écran d'asymétrie.
        s = json.loads(self.request("/api/refresh", method="POST", body={"source": "simule", "as_of": "2026-01-01"})[2])
        self.assertEqual((s["source"], s["universe"], s["asymmetry"]), ("simule", "sp500", False))
        self.assertEqual(s["as_of"], "2026-09-25")  # date réinitialisée au changement de source
        s = json.loads(self.request("/api/refresh", method="POST", body={"source": "reel"})[2])
        self.assertEqual((s["source"], s["universe"]), ("reel", "tout"))

    def test_besttry_screen(self):
        s = json.loads(self.request("/api/refresh", method="POST", body={"source": "reel", "universe": "tout"})[2])
        self.assertTrue(s["besttry"])
        status, _, html = self.request("/api/besttry")
        self.assertEqual(status, 200)
        self.assertIn("Best try", html)
        self.assertIn('data-ticker="NBIS"', html)
        self.assertIn("29/10", html)

    def test_watchlist_screen(self):
        import tempfile
        from pathlib import Path

        server_state = self.server.state
        with tempfile.TemporaryDirectory() as tmp:
            server_state.watchlist_file = Path(tmp) / "w.json"
            status, _, html = self.request("/api/watchlist")
            self.assertEqual(status, 200)
            self.assertIn("Ma liste de surveillance", html)
            self.assertIn("NBIS", html)  # liste par défaut
            status, _, html = self.request("/api/watchlist", method="POST", body={"add": "nvda"})
            self.assertEqual(status, 200, html)
            self.assertIn("data-watch-remove='NVDA'", html)
            status, _, html = self.request("/api/watchlist", method="POST", body={"remove": "NVDA"})
            self.assertNotIn("data-watch-remove='NVDA'", html)
            server_state.watchlist_file = None

    def test_polymarket_screen(self):
        s = json.loads(self.request("/api/summary")[2])
        self.assertTrue(s["polymarket"])
        status, _, html = self.request("/api/polymarket")
        self.assertEqual(status, 200)
        self.assertIn("0xsharp", html)

    def test_real_mode_refused_without_data(self):
        server = AppServer(AppState()).start()
        try:
            req = urllib.request.Request(server.url + "api/refresh", data=json.dumps({"source": "reel"}).encode(),
                                         headers={"X-App-Token": server.token, "Content-Type": "application/json"},
                                         method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=60)
            self.assertIn("aucun dossier", ctx.exception.read().decode())
        finally:
            server.stop()
