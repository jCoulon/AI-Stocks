"""Combine les piliers en un avis court terme (1-2 semaines) et moyen terme (1-3 mois)."""

from __future__ import annotations

import math

from ..models import Outlook, PillarResult

# Poids de chaque pilier selon l'horizon.
WEIGHTS = {
    "court": {"technique": 0.40, "sentiment": 0.25, "macro": 0.15, "recherche": 0.20},
    # À moyen terme, « technique » regroupe toute la tendance (technique + facteurs académiques
    # de momentum) ; « recherche » ne garde que les anomalies non liées à la tendance.
    "moyen": {"technique": 0.35, "sentiment": 0.10, "macro": 0.30, "recherche": 0.25},
}
HORIZON_DAYS = {"court": 5, "moyen": 63}


def label_for(score: float) -> str:
    if score >= 0.35:
        return "Haussier"
    if score >= 0.12:
        return "Plutôt haussier"
    if score > -0.12:
        return "Neutre"
    if score > -0.35:
        return "Plutôt baissier"
    return "Baissier"


def build_outlook(
    horizon: str,
    pillars: dict[str, PillarResult],
    last_close: float,
    daily_vol: float,
    data_quality: float,
    coherence: float,
    trust: dict[str, float] | None = None,
    horizon_vol: float | None = None,
) -> Outlook:
    """`trust` réduit le poids d'un pilier jugé peu fiable par le moteur de cohérence."""
    trust = trust or {}
    weights = {k: w * trust.get(k, 1.0) for k, w in WEIGHTS[horizon].items() if k in pillars}
    total = sum(weights.values()) or 1.0
    contrib = {k: w / total * pillars[k].score for k, w in weights.items()}
    score = sum(contrib.values())

    # Accord entre piliers : 1 si tous tirent dans le même sens.
    abs_sum = sum(abs(v) for v in contrib.values())
    agreement = abs(score) / abs_sum if abs_sum > 1e-9 else 0.0
    conviction = min(1.0, abs(score) / 0.4)
    # Plafonnée à 80 % : aucun modèle ne "sait" ce que fera le marché.
    confidence = (0.2 + 0.35 * agreement + 0.25 * conviction) * data_quality * (0.5 + 0.5 * coherence)
    confidence = max(0.05, min(0.8, confidence))

    # Fourchette d'incertitude à ±1 écart-type (≈ 2 chances sur 3) : prévision GARCH si
    # disponible, sinon volatilité historique x racine du nombre de séances. Elle est centrée
    # sur le cours actuel : le score n'ayant pas de pouvoir prédictif démontré (voir le
    # backtest), le décaler dans le sens de l'avis en ferait à tort un objectif de cours.
    # Couverture hors échantillon mesurée : 65-71 % des rendements réalisés (cible 68 %).
    band = horizon_vol if horizon_vol else daily_vol * math.sqrt(HORIZON_DAYS[horizon])
    low = last_close * (1 - band)
    high = last_close * (1 + band)
    return Outlook(horizon, score, label_for(score), confidence, low, high, contrib)
