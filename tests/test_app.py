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
