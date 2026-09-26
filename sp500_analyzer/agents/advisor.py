"""Avis de Claude à la demande (bouton de l'application).

Claude reçoit le dossier complet produit par l'équipe d'agents pour une action (ou pour
le marché) et rédige un second avis argumenté. Il peut s'écarter de l'avis de l'outil si
les données le justifient. Il ne calcule rien et ne dispose d'aucune autre source : il
travaille uniquement sur les chiffres fournis. La réponse est diffusée en continu.

Chaque demande est un appel payant à l'API Anthropic : l'application ne l'envoie que
lorsque l'utilisateur clique, et met la réponse en cache.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Optional

from ..models import MarketReport, TickerAnalysis
from .writer import MODEL, SYSTEM_PROMPT as MARKET_PROMPT, build_brief

STOCK_PROMPT = """Tu es un analyste actions expérimenté. Une équipe d'agents a analysé une action
du S&P 500 (graphiques, news, réseaux sociaux, macro-économie, facteurs issus de la recherche
académique) et contrôlé la cohérence des données. Tu reçois leur dossier complet au format JSON.

Donne TON avis, en français, à un investisseur particulier averti. Tu es un second regard :
si les données justifient une lecture différente de celle de l'outil, dis-le et explique pourquoi.

Structure (Markdown simple) :
## Avis de Claude — <titre>
**Court terme (1-2 semaines) :** verdict en une phrase, avec ta conviction (faible, modérée, élevée).
**Moyen terme (1-3 mois) :** idem.
### Ce qui soutient le titre
### Ce qui m'inquiète
### Ce que je surveillerais
(niveaux de cours clés, catalyseurs, alertes de données à lever)
### Accord avec l'outil
Une ou deux phrases : d'accord, en désaccord, ou nuancé, et pourquoi.

Règles :
- Uniquement les chiffres du dossier : n'invente ni cours, ni news, ni chiffre, ni événement.
- Tiens compte des alertes de cohérence (rumeurs écartées, bots, mouvements inexpliqués) : elles
  réduisent la confiance qu'on peut accorder aux données concernées.
- Les facteurs académiques sont des régularités statistiques moyennes, souvent affaiblies sur
  les grandes capitalisations : ne les présente pas comme des certitudes.
- Si "donnees_simulees" est vrai, rappelle en une phrase que les données sont simulées.
- Termine par : « Ceci n'est pas un conseil en investissement. »
- 300 mots maximum."""


class AdvisorUnavailable(Exception):
    """Claude ne peut pas être appelé (paquet absent, identifiants manquants ou invalides)."""

    def __init__(self, message: str, needs_key: bool = False):
        super().__init__(message)
        self.needs_key = needs_key


class AdvisorError(Exception):
    """L'appel a échoué (réseau, limite de débit, refus du modèle…)."""


def _r(v: Optional[float], n: int = 3) -> Optional[float]:
    return None if v is None else round(v, n)


def build_stock_brief(t: TickerAnalysis, report: MarketReport, simulated: bool) -> dict[str, Any]:
    """Dossier complet et déterministe d'une action, transmis tel quel au modèle."""
    sr, rv = t.stock, t.research
    brief: dict[str, Any] = {
        "donnees_simulees": simulated,
        "date": report.as_of.isoformat(),
        "titre": t.security.ticker,
        "nom": t.security.name,
        "secteur": t.security.sector,
        "cours": round(t.last_close, 2),
        "perf_semaine_pct": round(t.week_return * 100, 2),
        "qualite_donnees": round(t.data_quality, 2),
        "coherence_sources": round(t.coherence, 2),
        "avis_outil": {
            h: {"avis": o.label, "score": round(o.score, 3), "confiance": round(o.confidence, 2),
                "fourchette_probable_2_chances_sur_3": [round(o.low, 2), round(o.high, 2)],
                "contributions_par_pilier": {k: round(v, 3) for k, v in o.contributions.items()}}
            for h, o in (("court_terme", t.short), ("moyen_terme", t.medium))
        },
        "signaux": {
            key: [{"signal": s.name, "valeur": _r(s.value), "score": round(s.score, 2), "commentaire": s.comment}
                  for s in p.signals]
            for key, p in sorted(t.pillars.items())
        },
        "alertes_donnees": [{"code": f.code, "gravite": f.severity, "message": f.message} for f in t.flags],
        "contexte_marche": {
            "sp500": {"cours": round(report.index.last_close, 2),
                      "perf_semaine_pct": round(report.index.week_return * 100, 2),
                      "court_terme": report.index.short.label, "moyen_terme": report.index.medium.label},
            "macro": {k: round(v, 3) for k, v in sorted(report.macro_summary.items())},
            "news_marche": [f"{n.published.date().isoformat()} [{n.source}] {n.headline}" for n in report.market_news],
        },
    }
    if sr:
        brief["fiche"] = {
            "these_outil": sr.thesis,
            "points_forts": sr.strengths,
            "risques": sr.risks,
            "performance_pct": {k: round(v * 100, 2) for k, v in sr.performance.items()},
            "surperformance_vs_sp500_pct": {k: round(v * 100, 2) for k, v in sr.relative.items()},
            "risque": {k: round(v, 3) for k, v in sr.risk_metrics.items()},
            "niveaux_cles": [{"niveau": lv.label, "prix": round(lv.price, 2),
                              "ecart_pct": round((lv.price / t.last_close - 1) * 100, 1)} for lv in sr.levels],
            "news_7_jours": [{"date": c.published.isoformat(timespec="minutes"), "source": c.source,
                              "titre": c.headline, "ton": round(c.tone, 2),
                              "reaction_cours_pct": _r(c.reaction * 100 if c.reaction is not None else None, 2),
                              "retenue_par_le_controleur": c.retained} for c in sr.catalysts],
            "reseaux_sociaux": {k: round(v, 3) for k, v in sr.social.items()},
            "pairs_du_secteur": [{"titre": p.ticker, "perf_semaine_pct": round(p.week_return * 100, 2),
                                  "score_court": round(p.short_score, 2), "score_moyen": round(p.medium_score, 2)}
                                 for p in sr.peers],
            "rang_court_terme_dans_le_secteur": list(sr.sector_rank),
        }
    if rv:
        brief["recherche"] = {
            "facteurs": [{"facteur": f.name, "mesure": f.note, "percentile": _r(f.percentile, 2),
                          "score": round(f.score, 2), "source": f.reference}
                         for f in rv.factors if f.value is not None],
            "regime_statistique": {"regime": rv.regime, "ratio_de_variance": round(rv.variance_ratio, 3),
                                   "z_robuste": round(rv.vr_z, 2)},
            "risque_krach_momentum": rv.momentum_crash_risk,
            "volatilite_prevue_garch": ({"5_seances_pct": round(rv.garch.horizon_vol(5) * 100, 2),
                                         "63_seances_pct": round(rv.garch.horizon_vol(63) * 100, 2)}
                                        if rv.garch else None),
        }
    return brief


class ClaudeAdvisor:
    """Envoie un dossier à Claude et renvoie sa réponse morceau par morceau."""

    def __init__(self, client: Any = None, model: str = MODEL, api_key: Optional[str] = None):
        self._client = client
        self.model = model
        self.api_key = api_key

    def set_api_key(self, api_key: str) -> None:
        self.api_key = api_key.strip() or None
        self._client = None  # recréé avec la nouvelle clé

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise AdvisorUnavailable("Le paquet « anthropic » n'est pas installé (pip install anthropic).") from e
            kwargs: dict[str, Any] = {"timeout": 300.0}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def stream(self, report: MarketReport, ticker: Optional[str], simulated: bool) -> Iterator[str]:
        """Itère sur les morceaux de texte de l'avis. `ticker=None` : avis sur le marché.

        Les erreurs survenant avant le premier morceau sont levées dès le premier `next()`,
        ce qui permet à l'appelant de répondre proprement avant d'avoir commencé à diffuser.
        """
        if ticker is None:
            system, brief = MARKET_PROMPT, build_brief(report, simulated)
        else:
            t = next((x for x in report.tickers if x.security.ticker == ticker), None)
            if t is None:
                raise AdvisorError(f"Titre inconnu : {ticker}")
            system, brief = STOCK_PROMPT, build_stock_brief(t, report, simulated)
        return self._stream(system, json.dumps(brief, ensure_ascii=False))

    def _stream(self, system: str, content: str) -> Iterator[str]:
        client = self._get_client()
        try:
            import anthropic
            api_errors: tuple = (anthropic.APIError,)
            auth_error = anthropic.AuthenticationError
            rate_error = anthropic.RateLimitError
            conn_error = anthropic.APIConnectionError
        except ImportError:  # client de test injecté sans le paquet
            api_errors, auth_error, rate_error, conn_error = (), None, None, None
        try:
            with client.beta.messages.stream(
                model=self.model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                # En cas de refus du modèle principal, l'API rejoue la requête sur un modèle de repli.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": content}],
            ) as stream:
                produced = False
                for text in stream.text_stream:
                    produced = True
                    yield text
                final = stream.get_final_message()
            if final.stop_reason == "refusal":
                raise AdvisorError("Claude a refusé de rédiger cet avis.")
            if not produced:
                raise AdvisorError(f"Réponse vide (stop_reason={final.stop_reason}).")
        except TypeError as e:
            # Levée par le SDK quand aucune méthode d'authentification n'est configurée.
            if "authentication" in str(e):
                raise AdvisorUnavailable("Aucune clé API Anthropic configurée.", needs_key=True) from e
            raise
        except api_errors as e:
            if auth_error and isinstance(e, auth_error):
                raise AdvisorUnavailable("Clé API Anthropic refusée (invalide ou révoquée).", needs_key=True) from e
            if rate_error and isinstance(e, rate_error):
                raise AdvisorError("Limite de requêtes atteinte : réessayez dans une minute.") from e
            if conn_error and isinstance(e, conn_error):
                raise AdvisorError("Impossible de joindre l'API Anthropic (connexion réseau ?).") from e
            raise AdvisorError(f"Erreur de l'API Anthropic : {getattr(e, 'message', e)}") from e
