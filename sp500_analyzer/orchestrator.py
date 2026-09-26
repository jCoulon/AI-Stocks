"""Orchestrateur : planifie le travail des agents et l'exécute en parallèle.

Plan (un graphe de tâches par titre, plus des tâches globales) :

    collecteur(^GSPC) ──────────────┐
    economiste (macro) ─────────────┼─────────────────────┐
    collecteur(T) ─┬─ controleur(T) ─┴─ sentiment(T)* ─┐   │
                   └─ technicien(T) ───────────────────┴─ strategiste(T) ─┐
                                                                         ├─ chef-strategiste ─┬─ redacteur*
                        (idem pour chaque titre et pour l'indice) ───────┘                    └─ analyste-titre(T)
    * tâche facultative : son échec n'empêche pas la suite, l'avis est rendu sans ce pilier.

Chaque tâche est lancée dès que ses dépendances sont terminées. Une tâche en
échec est retentée ; si elle échoue définitivement, les tâches qui en dépendent
obligatoirement sont annulées (« skipped ») tandis que les dépendances
facultatives laissent la suite s'exécuter en mode dégradé.
"""

from __future__ import annotations

import time as _time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import datetime, time
from typing import Callable, Optional

from .agents.base import Agent, AgentUnavailable, Blackboard, Task, TaskRecord
from .agents.specialists import (
    DataCollectorAgent,
    MacroEconomistAgent,
    MarketStrategistAgent,
    QualityControlAgent,
    SentimentAnalystAgent,
    StockAnalystAgent,
    StrategistAgent,
    TechnicalAnalystAgent,
)
from .agents.writer import ClaudeWriterAgent
from .models import MarketReport
from .providers.base import DataProvider

Listener = Callable[[TaskRecord], None]


class OrchestrationError(RuntimeError):
    def __init__(self, message: str, records: list[TaskRecord]):
        super().__init__(message)
        self.records = records


class Orchestrator:
    def __init__(
        self,
        provider: DataProvider,
        agents: Optional[dict[str, Agent]] = None,
        max_workers: int = 8,
        retries: int = 1,
        use_llm: bool = False,
        listener: Optional[Listener] = None,
    ):
        self.provider = provider
        self.max_workers = max_workers
        self.retries = retries
        self.use_llm = use_llm
        self.listener = listener
        self.agents: dict[str, Agent] = {
            "collecteur": DataCollectorAgent(),
            "economiste": MacroEconomistAgent(),
            "controleur": QualityControlAgent(),
            "technicien": TechnicalAnalystAgent(),
            "sentiment": SentimentAnalystAgent(),
            "strategiste": StrategistAgent(),
            "analyste-titre": StockAnalystAgent(),
        }
        if use_llm:
            self.agents["redacteur"] = ClaudeWriterAgent()
        self.agents.update(agents or {})

    # ------------------------------------------------------------ planning

    def plan(self, tickers: list[str]) -> list[Task]:
        index = self.provider.index().ticker
        tasks = [Task("macro", "economiste"), Task(f"collect:{index}", "collecteur", index)]
        for t in [index, *tickers]:
            if t != index:
                tasks.append(Task(f"collect:{t}", "collecteur", t))
            tasks += [
                Task(f"quality:{t}", "controleur", t, (f"collect:{t}",)),
                Task(f"technical:{t}", "technicien", t, (f"collect:{t}", f"collect:{index}")),
                Task(f"sentiment:{t}", "sentiment", t, (f"quality:{t}",)),
                Task(f"strategy:{t}", "strategiste", t,
                     (f"collect:{t}", f"quality:{t}", f"technical:{t}"),
                     optional_deps=("macro", f"sentiment:{t}")),
            ]
        tasks.append(Task("market", "chef-strategiste", None, (f"strategy:{index}",),
                          optional_deps=tuple(f"strategy:{t}" for t in tickers) + ("macro",)))
        tasks += [Task(f"stock:{t}", "analyste-titre", t, ("market", f"collect:{t}", f"quality:{t}"))
                  for t in tickers]
        if "redacteur" in self.agents:
            tasks.append(Task("writer", "redacteur", None, ("market",)))
        return tasks

    # ----------------------------------------------------------- exécution

    def execute(self, tasks: list[Task], board: Blackboard) -> dict[str, TaskRecord]:
        by_id = {t.id: t for t in tasks}
        records = {t.id: TaskRecord(t.id, t.agent, t.ticker) for t in tasks}
        for t in tasks:
            unknown = [d for d in (*t.depends_on, *t.optional_deps) if d not in by_id]
            if unknown or t.agent not in self.agents:
                raise ValueError(f"Plan invalide pour {t.id} : dépendances {unknown} / agent {t.agent}")

        pending = set(by_id)
        running: dict[Future, str] = {}

        def finished(tid: str) -> bool:
            return records[tid].status in ("done", "failed", "skipped")

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            while pending or running:
                # Une annulation peut en débloquer d'autres : on repasse jusqu'à stabilité.
                progressed = True
                while progressed:
                    progressed = False
                    for tid in sorted(pending):
                        task = by_id[tid]
                        deps = (*task.depends_on, *task.optional_deps)
                        if not all(finished(d) for d in deps):
                            continue
                        pending.discard(tid)
                        progressed = True
                        broken = [d for d in task.depends_on if records[d].status != "done"]
                        if broken:
                            self._finish(records[tid], "skipped", f"dépendance indisponible : {', '.join(broken)}")
                            continue
                        running[pool.submit(self._run_task, task, board)] = tid

                if not running:
                    if pending:  # cycle : rien n'est exécutable
                        raise ValueError(f"Dépendances circulaires : {sorted(pending)}")
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for fut in done:
                    tid = running.pop(fut)
                    status, attempts, ms, error, value = fut.result()
                    rec = records[tid]
                    rec.attempts, rec.duration_ms = attempts, ms
                    if status == "done":
                        board.put(tid, value)
                    self._finish(rec, status, error)
        return records

    def _run_task(self, task: Task, board: Blackboard):
        agent = self.agents[task.agent]
        start = _time.perf_counter()
        error = ""
        retries = self.retries if agent.retries is None else agent.retries
        for attempt in range(1, retries + 2):
            try:
                value = agent.run(task, board)
                return "done", attempt, (_time.perf_counter() - start) * 1000, "", value
            except AgentUnavailable as e:
                return "skipped", attempt, (_time.perf_counter() - start) * 1000, str(e), None
            except Exception as e:  # noqa: BLE001 — un agent défaillant ne doit pas arrêter l'équipe
                error = f"{type(e).__name__}: {e}"
        return "failed", retries + 1, (_time.perf_counter() - start) * 1000, error, None

    def _finish(self, rec: TaskRecord, status: str, error: str = "") -> None:
        rec.status, rec.error = status, error
        if self.listener:
            self.listener(rec)

    # --------------------------------------------------------------- run

    def run(self, tickers: Optional[list[str]] = None, focus: Optional[list[str]] = None) -> MarketReport:
        """Analyse `tickers` (défaut : tout l'univers). `focus` limite les titres affichés
        dans le rapport sans changer la largeur de marché, calculée sur tout l'univers."""
        universe = [s.ticker for s in self.provider.universe()]
        tickers = tickers or universe
        board = Blackboard(self.provider, datetime.combine(self.provider.as_of, time(22, 0)))
        self.agents["chef-strategiste"] = MarketStrategistAgent(tickers)

        records = self.execute(self.plan(tickers), board)
        trace = [asdict(r) for r in records.values()]
        report: Optional[MarketReport] = board.get("market")
        if report is None:
            raise OrchestrationError("L'orchestration n'a pas pu produire de rapport", list(records.values()))
        for t in report.tickers:
            t.stock = board.get(f"stock:{t.security.ticker}")
        report.narrative = board.get("writer")
        report.trace = trace
        if focus:
            wanted = {f.upper() for f in focus}
            report.tickers = [t for t in report.tickers if t.security.ticker in wanted]
        return report
