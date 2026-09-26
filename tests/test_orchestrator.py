import json
import threading
import unittest
from types import SimpleNamespace

from sp500_analyzer.agents import Agent, AgentUnavailable, ClaudeWriterAgent, SentimentAnalystAgent
from sp500_analyzer.agents.writer import build_brief
from sp500_analyzer.engine import run_analysis
from sp500_analyzer.orchestrator import OrchestrationError, Orchestrator
from sp500_analyzer.providers import MockDataProvider
from sp500_analyzer.report import render_html, render_text, render_trace


def _scores(report):
    return [(t.security.ticker, t.short.score, t.medium.score, t.short.confidence) for t in [report.index, *report.tickers]]


class Failing(Agent):
    """Agent qui échoue sur les titres donnés (ou sur tous)."""

    def __init__(self, inner: Agent, tickers=None, exc=RuntimeError("panne simulée")):
        self.inner, self.tickers, self.exc = inner, tickers, exc
        self.calls = 0
        self._lock = threading.Lock()

    def run(self, task, board):
        with self._lock:
            self.calls += 1
        if self.tickers is None or task.ticker in self.tickers:
            raise self.exc
        return self.inner.run(task, board)


class Flaky(Agent):
    """Échoue une seule fois par tâche, puis réussit."""

    def __init__(self, inner: Agent):
        self.inner, self.seen = inner, set()
        self._lock = threading.Lock()

    def run(self, task, board):
        with self._lock:
            first = task.id not in self.seen
            self.seen.add(task.id)
        if first:
            raise ConnectionError("coupure réseau")
        return self.inner.run(task, board)


class Recorder(Agent):
    """Enregistre l'ordre d'exécution des tâches."""

    def __init__(self, inner: Agent, log: list, lock: threading.Lock):
        self.inner, self.log, self.lock = inner, log, lock

    def run(self, task, board):
        with self.lock:
            self.log.append(task.id)
        return self.inner.run(task, board)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockDataProvider()

    def test_plan_is_a_valid_dag(self):
        orch = Orchestrator(self.provider)
        tasks = orch.plan(["AAPL", "MSFT"])
        ids = {t.id for t in tasks}
        for t in tasks:
            self.assertTrue(set(t.depends_on) | set(t.optional_deps) <= ids, t.id)
        self.assertIn("strategy:AAPL", ids)
        # macro + collecte indice, 4 tâches pour l'indice, 6 par titre (dont la fiche), chercheur, marché
        self.assertEqual(len(tasks), 2 + 4 + 2 * 6 + 1 + 1)

    def test_dependencies_respected(self):
        log, lock = [], threading.Lock()
        base = Orchestrator(self.provider).agents
        agents = {name: Recorder(agent, log, lock) for name, agent in base.items()}
        Orchestrator(self.provider, agents=agents, max_workers=6).run(["AAPL", "META"])
        pos = {tid: i for i, tid in enumerate(log)}
        for t in ("AAPL", "META", "^GSPC"):
            self.assertLess(pos[f"collect:{t}"], pos[f"quality:{t}"])
            self.assertLess(pos[f"quality:{t}"], pos[f"sentiment:{t}"])
            self.assertLess(pos[f"sentiment:{t}"], pos[f"strategy:{t}"])
            self.assertLess(pos[f"technical:{t}"], pos[f"strategy:{t}"])
            self.assertLess(pos["macro"], pos[f"strategy:{t}"])
        self.assertLess(pos["collect:^GSPC"], pos["technical:AAPL"])

    def test_parallel_equals_sequential(self):
        seq = Orchestrator(self.provider, max_workers=1).run()
        par = Orchestrator(self.provider, max_workers=16).run()
        self.assertEqual(_scores(seq), _scores(par))

    def test_optional_agent_failure_degrades_gracefully(self):
        failing = Failing(SentimentAnalystAgent(), tickers={"NVDA"})
        report = Orchestrator(self.provider, agents={"sentiment": failing}, retries=1).run()
        by = {t.security.ticker: t for t in report.tickers}
        self.assertEqual(len(report.tickers), 30)
        nvda = by["NVDA"]
        self.assertNotIn("sentiment_court", nvda.pillars)
        self.assertIn("AGENT_FAILURE", {f.code for f in nvda.flags})
        self.assertIn("sentiment_court", by["AAPL"].pillars)
        rec = next(r for r in report.trace if r["task_id"] == "sentiment:NVDA")
        self.assertEqual((rec["status"], rec["attempts"]), ("failed", 2))

    def test_failure_lowers_confidence(self):
        normal = {t.security.ticker: t for t in run_analysis(self.provider).tickers}
        degraded = Orchestrator(self.provider, agents={"sentiment": Failing(SentimentAnalystAgent())}).run()
        for t in degraded.tickers:
            self.assertLess(t.coherence, normal[t.security.ticker].coherence + 1e-9)

    def test_required_failure_skips_only_that_ticker(self):
        base = Orchestrator(self.provider).agents["collecteur"]
        report = Orchestrator(self.provider, agents={"collecteur": Failing(base, tickers={"TSLA"})}).run()
        tickers = {t.security.ticker for t in report.tickers}
        self.assertNotIn("TSLA", tickers)
        self.assertEqual(len(tickers), 29)
        status = {r["task_id"]: r["status"] for r in report.trace}
        self.assertEqual(status["collect:TSLA"], "failed")
        for k in ("quality:TSLA", "technical:TSLA", "sentiment:TSLA", "strategy:TSLA", "stock:TSLA"):
            self.assertEqual(status[k], "skipped", k)

    def test_index_failure_aborts_with_trace(self):
        base = Orchestrator(self.provider).agents["collecteur"]
        orch = Orchestrator(self.provider, agents={"collecteur": Failing(base, tickers={"^GSPC"})}, retries=0)
        with self.assertRaises(OrchestrationError) as ctx:
            orch.run()
        self.assertTrue(any(r.task_id == "market" and r.status == "skipped" for r in ctx.exception.records))

    def test_retry_recovers_transient_errors(self):
        base = Orchestrator(self.provider).agents["technicien"]
        report = Orchestrator(self.provider, agents={"technicien": Flaky(base)}, retries=1).run()
        recs = [r for r in report.trace if r["agent"] == "technicien"]
        self.assertTrue(all(r["status"] == "done" and r["attempts"] == 2 for r in recs))
        self.assertEqual(_scores(report), _scores(run_analysis(self.provider)))

    def test_trace_rendering(self):
        report = run_analysis(self.provider)
        text = render_trace(report)
        self.assertIn("strategiste", text)
        self.assertIn("188 tâches", text)
        self.assertIn("Équipe d'agents", render_html(report))


class FakeClient:
    """Imite client.beta.messages.create du SDK Anthropic."""

    def __init__(self, stop_reason="end_turn", text="## Synthèse\nMarché plutôt haussier."):
        self.kwargs = None
        self.stop_reason, self.text = stop_reason, text
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=self.text)])


class WriterAgentTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockDataProvider()

    def test_writer_produces_narrative_from_agent_conclusions(self):
        client = FakeClient()
        orch = Orchestrator(self.provider, agents={"redacteur": ClaudeWriterAgent(client=client)})
        report = orch.run(focus=["META"])
        self.assertEqual(report.narrative, "## Synthèse\nMarché plutôt haussier.")
        kw = client.kwargs
        self.assertEqual(kw["model"], "claude-opus-5")
        self.assertEqual(kw["thinking"], {"type": "adaptive"})
        self.assertEqual(kw["fallbacks"], "default")
        brief = json.loads(kw["messages"][0]["content"])
        self.assertTrue(brief["donnees_simulees"])
        self.assertEqual(len(brief["titres"]), 30)  # le rédacteur voit tout l'univers
        meta = next(t for t in brief["titres"] if t["titre"] == "META")
        self.assertTrue(any("coordonnés" in a for a in meta["alertes"]))
        self.assertIn("SYNTHÈSE DE L'AGENT RÉDACTEUR", render_text(report))

    def test_refusal_is_reported_not_fatal(self):
        orch = Orchestrator(self.provider, agents={"redacteur": ClaudeWriterAgent(client=FakeClient("refusal", ""))})
        report = orch.run()
        self.assertIsNone(report.narrative)
        rec = next(r for r in report.trace if r["agent"] == "redacteur")
        self.assertEqual(rec["status"], "failed")
        self.assertEqual(rec["attempts"], 1)  # pas de nouvelle tentative : le SDK gère ses reprises

    def test_unavailable_writer_is_skipped(self):
        class NoCreds(ClaudeWriterAgent):
            def _get_client(self):
                raise AgentUnavailable("aucun identifiant")

        report = Orchestrator(self.provider, agents={"redacteur": NoCreds()}).run()
        rec = next(r for r in report.trace if r["agent"] == "redacteur")
        self.assertEqual((rec["status"], rec["error"]), ("skipped", "aucun identifiant"))
        self.assertEqual(len(report.tickers), 30)

    def test_brief_is_deterministic(self):
        report = run_analysis(self.provider)
        self.assertEqual(json.dumps(build_brief(report, True)), json.dumps(build_brief(report, True)))


if __name__ == "__main__":
    unittest.main()
