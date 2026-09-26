"""Analyse des mouvements des actions du S&P 500.

Croise cours (graphiques), news, réseaux sociaux et données macro-économiques,
vérifie leur cohérence, et produit un avis à court et moyen terme.
Outil d'analyse de données — ce n'est pas un conseil en investissement.
"""

from .engine import run_analysis
from .providers import DataProvider, MockDataProvider

__all__ = ["run_analysis", "DataProvider", "MockDataProvider"]
