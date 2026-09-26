"""Briques communes aux agents : tâche, tableau partagé (blackboard) et contrat d'agent."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..providers.base import DataProvider


class AgentUnavailable(Exception):
    """L'agent ne peut pas s'exécuter dans cet environnement (dépendance, identifiants...)."""


@dataclass(frozen=True)
class Task:
    """Unité de travail confiée à un agent par l'orchestrateur."""

    id: str
    agent: str
    ticker: Optional[str] = None
    depends_on: tuple[str, ...] = ()
    #: Dépendances dont l'échec n'empêche pas la tâche de s'exécuter.
    optional_deps: tuple[str, ...] = ()


@dataclass
class TaskRecord:
    """Trace d'exécution d'une tâche (journal de l'orchestrateur)."""

    task_id: str
    agent: str
    ticker: Optional[str]
    status: str = "pending"  # pending | done | failed | skipped
    attempts: int = 0
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class Blackboard:
    """Mémoire partagée par laquelle les agents se transmettent leurs résultats.

    Chaque tâche publie son résultat sous son identifiant ; un agent lit les
    résultats de ses dépendances. Thread-safe.
    """

    provider: DataProvider
    now: datetime
    _data: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._data


class Agent(ABC):
    """Un agent spécialisé : lit le tableau partagé, produit un résultat."""

    #: Identifiant court, utilisé dans le plan et le journal.
    name: str = "agent"
    #: Rôle en une phrase (affiché dans la trace).
    role: str = ""
    #: Nombre de nouvelles tentatives en cas d'échec (None = valeur de l'orchestrateur).
    retries: Optional[int] = None

    @abstractmethod
    def run(self, task: Task, board: Blackboard) -> Any:
        """Exécute la tâche ; la valeur renvoyée est publiée sous `task.id`."""
