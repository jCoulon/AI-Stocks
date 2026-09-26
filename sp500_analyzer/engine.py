"""Point d'entrée programmatique : délègue le travail à l'orchestrateur d'agents."""

from __future__ import annotations

from .models import MarketReport
from .orchestrator import Orchestrator
from .providers.base import DataProvider


def run_analysis(
    provider: DataProvider,
    tickers: list[str] | None = None,
    *,
    use_llm: bool = False,
    max_workers: int = 8,
) -> MarketReport:
    """Analyse tout l'univers ; `tickers` restreint les titres présentés dans le rapport.

    La largeur de marché est toujours calculée sur l'univers complet.
    """
    orchestrator = Orchestrator(provider, use_llm=use_llm, max_workers=max_workers)
    return orchestrator.run(focus=tickers)
