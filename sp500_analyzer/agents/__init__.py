"""Équipe d'agents spécialisés coordonnés par l'orchestrateur."""

from .base import Agent, AgentUnavailable, Blackboard, Task, TaskRecord
from .specialists import (
    DataCollectorAgent,
    MacroEconomistAgent,
    MarketStrategistAgent,
    QualityControlAgent,
    QuantResearchAgent,
    SentimentAnalystAgent,
    StockAnalystAgent,
    StrategistAgent,
    TechnicalAnalystAgent,
)
from .writer import ClaudeWriterAgent

__all__ = [
    "Agent", "AgentUnavailable", "Blackboard", "Task", "TaskRecord",
    "DataCollectorAgent", "MacroEconomistAgent", "MarketStrategistAgent", "QualityControlAgent", "QuantResearchAgent",
    "SentimentAnalystAgent", "StockAnalystAgent", "StrategistAgent", "TechnicalAnalystAgent", "ClaudeWriterAgent",
]
