import json
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace

from sp500_analyzer.agents.advisor import (
    AdvisorError, AdvisorUnavailable, ClaudeAdvisor, STOCK_PROMPT, build_stock_brief,
)
from sp500_analyzer.app.server import MARKET, AppServer, AppState
from sp500_analyzer.engine import run_analysis
from sp500_analyzer.providers import MockDataProvider


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.chunks, self.stop_reason = chunks, stop_reason

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        yield from self.chunks

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason)


class FakeClient:
    """Imite client.beta.messages.stream du SDK Anthropic."""

    def __init__(self, chunks=("## Avis", " de Claude\n", "- point"), stop_reason="end_turn", error=None):
        self.calls = []
        self.chunks, self.stop_reason, self.error = list(chunks), stop_reason, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeStream(self.chunks, self.stop_reason)


class AdvisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_analysis(MockDataProvider())

    def test_stock_brief_contains_the_full_dossier(self):
        meta = next(t for t in self.report.tickers if t.security.ticker == "META")
        brief = build_stock_brief(meta, self.report, simulated=True)
        self.assertTrue(brief["donnees_simulees"])
        self.assertIn("SUSPECTED_BOTS", {a["code"] for a in brief["alertes_donnees"]})
        self.assertIn("recherche", brief)
        self.assertIn("niveaux_cles", brief["fiche"])
        self.assertFalse(brief["fiche"]["news_7_jours"][0]["retenue_par_le_controleur"])  # rumeur écartée
        self.assertEqual(set(brief["avis_outil"]), {"court_terme", "moyen_terme"})
        json.dumps(brief, allow_nan=False)  # JSON standard, déterministe
        self.assertEqual(json.dumps(brief), json.dumps(build_stock_brief(meta, self.report, True)))

    def test_stream_sends_stock_dossier_with_expected_settings(self):
        client = FakeClient()
        text = "".join(ClaudeAdvisor(client=client).stream(self.report, "NVDA", True))
        self.assertEqual(text, "## Avis de Claude\n- point")
        kw = client.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5")
        self.assertEqual(kw["thinking"], {"type": "adaptive"})
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["system"], STOCK_PROMPT)
        self.assertEqual(json.loads(kw["messages"][0]["content"])["titre"], "NVDA")

    def test_market_advice_uses_market_brief(self):
        client = FakeClient()
        "".join(ClaudeAdvisor(client=client).stream(self.report, None, True))
        self.assertEqual(len(json.loads(client.calls[0]["messages"][0]["content"])["titres"]), 30)

    def test_errors_are_explicit(self):
        with self.assertRaises(AdvisorError):
            "".join(ClaudeAdvisor(client=FakeClient(stop_reason="refusal")).stream(self.report, "AAPL", True))
        with self.assertRaises(AdvisorError):
            "".join(ClaudeAdvisor(client=FakeClient(chunks=())).stream(self.report, "AAPL", True))
        no_key = FakeClient(error=TypeError("Could not resolve authentication method"))
        with self.assertRaises(AdvisorUnavailable) as ctx:
            "".join(ClaudeAdvisor(client=no_key).stream(self.report, "AAPL", True))
        self.assertTrue(ctx.exception.needs_key)


class AdviceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(chunks=["Avis ", "sur ", "le titre."])
        self.server = AppServer(AppState(advisor=ClaudeAdvisor(client=self.client))).start()

    def tearDown(self):
        self.server.stop()

    def call(self, path, body=None, token=True):
        headers = {"X-App-Token": self.server.token} if token else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.server.url.rstrip("/") + path, data=data, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_advice_is_streamed_then_cached(self):
        self.assertEqual(self.call("/api/advice/NVDA")[0], 404)  # rien en cache : aucun appel payant
        self.assertEqual(self.call("/api/advice", {"ticker": "NVDA"}), (200, "Avis sur le titre."))
        self.assertEqual(self.call("/api/advice", {"ticker": "NVDA"}), (200, "Avis sur le titre."))
        self.assertEqual(len(self.client.calls), 1)  # second clic servi par le cache
        status, body = self.call("/api/advice/NVDA")
        self.assertEqual((status, json.loads(body)["text"]), (200, "Avis sur le titre."))
        self.call("/api/advice", {"ticker": "NVDA", "refresh": True})
        self.assertEqual(len(self.client.calls), 2)  # « Régénérer » : nouvel appel

    def test_new_analysis_invalidates_cache(self):
        self.call("/api/advice", {"ticker": "AAPL"})
        self.call("/api/refresh", {"seed": 7})
        self.assertEqual(self.call("/api/advice/AAPL")[0], 404)

    def test_market_advice(self):
        status, body = self.call("/api/advice", {"ticker": MARKET})
        self.assertEqual((status, body), (200, "Avis sur le titre."))

    def test_errors_and_security(self):
        self.assertEqual(self.call("/api/advice", {"ticker": "NVDA"}, token=False)[0], 403)
        self.assertEqual(self.call("/api/credentials", {"api_key": "x"}, token=False)[0], 403)
        self.assertEqual(self.call("/api/advice", {"ticker": "XYZ"})[0], 404)
        self.assertEqual(self.call("/api/credentials", {"api_key": ""})[0], 400)
        self.client.error = TypeError("Could not resolve authentication method")
        status, body = self.call("/api/advice", {"ticker": "NVDA"})
        self.assertEqual(status, 503)
        self.assertTrue(json.loads(body)["needs_key"])

    def test_credentials_are_kept_in_memory(self):
        advisor = ClaudeAdvisor()
        server = AppServer(AppState(advisor=advisor)).start()
        try:
            req = urllib.request.Request(server.url + "api/credentials", data=b'{"api_key": " sk-ant-test "}',
                                         headers={"X-App-Token": server.token, "Content-Type": "application/json"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                self.assertEqual(r.status, 200)
            self.assertEqual(advisor.api_key, "sk-ant-test")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
