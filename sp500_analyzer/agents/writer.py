"""Agent rédacteur (optionnel) : Claude rédige une synthèse en français du rapport.

Il ne calcule rien : il reçoit uniquement les conclusions chiffrées des autres
agents et les met en mots. Nécessite le paquet `anthropic` et des identifiants
(ANTHROPIC_API_KEY ou profil `ant auth login`).
"""

from __future__ import annotations

import json
from typing import Any

from ..models import MarketReport, TickerAnalysis
from .base import Agent, AgentUnavailable, Blackboard, Task

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """Tu es le rédacteur d'une équipe d'analyse des marchés actions américains.
D'autres agents ont déjà analysé les données (graphiques, news, réseaux sociaux, macro-économie)
et contrôlé leur cohérence. Tu reçois leurs conclusions au format JSON.

Rédige en français une synthèse claire destinée à un investisseur particulier averti :
1. Le contexte de marché de la semaine (indice, macro, faits marquants).
2. Les titres les plus orientés à la hausse et à la baisse, à court et moyen terme, avec la raison principale.
3. Les alertes de cohérence des données et ce qu'elles impliquent pour la confiance.
4. Les principaux risques pour la suite.

Règles :
- Appuie-toi uniquement sur les chiffres fournis ; n'invente ni cours, ni news, ni chiffre.
- Donne des avis nuancés et mentionne le niveau de confiance ; ce n'est pas un conseil en investissement.
- Signale que les données sont simulées si le champ "donnees_simulees" est vrai.
- 350 mots maximum, en Markdown simple (titres courts et listes)."""


def _brief(t: TickerAnalysis) -> dict[str, Any]:
    return {
        "titre": t.security.ticker,
        "nom": t.security.name,
        "secteur": t.security.sector,
        "cours": round(t.last_close, 2),
        "perf_semaine_pct": round(t.week_return * 100, 2),
        "court_terme": {"avis": t.short.label, "score": round(t.short.score, 2), "confiance": round(t.short.confidence, 2),
                        "contributions": {k: round(v, 2) for k, v in t.short.contributions.items()}},
        "moyen_terme": {"avis": t.medium.label, "score": round(t.medium.score, 2), "confiance": round(t.medium.confidence, 2),
                        "contributions": {k: round(v, 2) for k, v in t.medium.contributions.items()}},
        "alertes": [f.message for f in t.flags if f.severity != "info"],
        "confirmations": [f.message for f in t.flags if f.severity == "info"],
    }


def build_brief(report: MarketReport, simulated: bool) -> dict[str, Any]:
    """Résumé compact et déterministe du rapport transmis au modèle."""
    return {
        "date": report.as_of.isoformat(),
        "donnees_simulees": simulated,
        "indice": _brief(report.index),
        "macro": {k: round(v, 3) for k, v in sorted(report.macro_summary.items())},
        "largeur_marche": {k: round(v, 2) for k, v in report.breadth.items()},
        "news_marche": [f"{n.published.date().isoformat()} [{n.source}] {n.headline}" for n in report.market_news],
        "titres": [_brief(t) for t in sorted(report.tickers, key=lambda x: -x.short.score)],
    }


class ClaudeWriterAgent(Agent):
    name = "redacteur"
    role = "Rédige la synthèse finale en langage naturel (Claude)"
    retries = 0  # le SDK Anthropic gère déjà les reprises (429, 5xx, réseau)

    def __init__(self, client: Any = None, model: str = MODEL):
        self._client = client
        self.model = model

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise AgentUnavailable("paquet 'anthropic' non installé (pip install anthropic)") from e
            try:
                self._client = anthropic.Anthropic(timeout=300.0)
            except anthropic.AnthropicError as e:
                raise AgentUnavailable(f"identifiants Anthropic introuvables : {e}") from e
        return self._client

    def run(self, task: Task, board: Blackboard) -> str:
        report: MarketReport = board.get("market")
        from ..providers.mock import MockDataProvider

        brief = build_brief(report, simulated=isinstance(board.provider, MockDataProvider))
        client = self._get_client()
        try:
            response = self._create(client, brief)
        except TypeError as e:
            # Levée par le SDK quand aucune méthode d'authentification n'est configurée.
            if "authentication" in str(e):
                raise AgentUnavailable("aucun identifiant Anthropic (définir ANTHROPIC_API_KEY)") from e
            raise
        if response.stop_reason == "refusal":
            raise RuntimeError("le modèle a refusé de rédiger la synthèse")
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise RuntimeError(f"réponse vide (stop_reason={response.stop_reason})")
        return text

    def _create(self, client: Any, brief: dict[str, Any]):
        return client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            # En cas de refus du modèle principal, l'API rejoue la requête sur un modèle de repli.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(brief, ensure_ascii=False)}],
        )
