"""Pilier sentiment : news (pondérées par fiabilité et fraîcheur) et réseaux sociaux."""

from __future__ import annotations

import math
import re
from datetime import datetime

from ..models import NewsItem, PillarResult, Signal, SocialPost
from ..universe import EVENT_SOURCES, source_reliability
from .indicators import clip

POSITIVE = {
    "beat", "beats", "raise", "raises", "raised", "upgrade", "upgrades", "record", "surge", "surges",
    "strong", "growth", "buyback", "approval", "approves", "win", "wins", "soar", "soars", "jump",
    "jumps", "rally", "rallies", "outperform", "bullish", "boost", "boosts", "tops", "gain", "gains",
    "rise", "rises", "upbeat", "impresses", "improve", "improves", "breakout", "long", "buy",
    "momentum", "great", "loving", "cools", "dovish", "eases",
}
NEGATIVE = {
    "miss", "misses", "cut", "cuts", "downgrade", "downgrades", "probe", "investigation", "lawsuit",
    "halt", "halts", "recall", "fall", "falls", "plunge", "plunges", "weak", "warning", "warns",
    "slump", "slumps", "decline", "declines", "bearish", "delay", "delays", "layoffs", "fined",
    "fraud", "inspections", "slips", "pressure", "setback", "concerns", "slowing", "overvalued",
    "sold", "risk", "breaking", "dips", "cautious", "away", "sell",
}
# Expressions financières dont le sens diffère de celui des mots isolés (cf. Loughran &
# McDonald, 2011 : un dictionnaire générique classe mal le vocabulaire financier).
# Elles sont reconnues avant les mots et « consomment » leurs mots. Point de vue : actionnaire.
PHRASES: dict[tuple[str, ...], float] = {
    # Politique monétaire et taux : une détente est favorable aux actions.
    ("openness", "to", "cut"): 1.0, ("rate", "cut"): 1.0, ("rate", "cuts"): 1.0,
    ("cut", "rates"): 1.0, ("cuts", "rates"): 1.0, ("yields", "fall"): 1.0, ("yields", "drop"): 1.0,
    ("yields", "rise"): -1.0, ("yields", "jump"): -1.0, ("yields", "surge"): -1.0,
    ("rate", "hike"): -1.0, ("rate", "hikes"): -1.0, ("raises", "rates"): -1.0, ("hikes", "rates"): -1.0,
    # Inflation et emploi : « hausse » est ici une mauvaise nouvelle.
    ("inflation", "cools"): 1.0, ("inflation", "eases"): 1.0, ("inflation", "falls"): 1.0,
    ("inflation", "rises"): -1.0, ("inflation", "accelerates"): -1.0, ("inflation", "jumps"): -1.0,
    ("claims", "rise"): -1.0, ("claims", "jump"): -1.0, ("claims", "fall"): 1.0,
    ("unemployment", "rises"): -1.0, ("unemployment", "falls"): 1.0,
    # Pétrole : une réduction de production n'est pas une « coupe » négative pour l'émetteur.
    ("output", "cuts"): 0.0, ("production", "cuts"): 0.0,
    # Guidance et dividendes.
    ("cuts", "guidance"): -1.5, ("guidance", "cut"): -1.5, ("cuts", "dividend"): -1.5,
    ("raises", "guidance"): 1.5, ("raises", "dividend"): 1.0,
}
_MAX_PHRASE = max(len(k) for k in PHRASES)
NEGATIONS = {"not", "no", "never", "without"}
EMOJI = {"🚀": 0.6, "📈": 0.5, "📉": -0.5, "💀": -0.5}
_WORD = re.compile(r"[a-z']+")


def score_text(text: str) -> float:
    """Score lexical simple dans [-1, 1]."""
    words = _WORD.findall(text.lower())
    total = 0.0
    i = 0
    while i < len(words):
        for size in range(min(_MAX_PHRASE, len(words) - i), 1, -1):
            phrase = tuple(words[i:i + size])
            if phrase in PHRASES:
                v, step = PHRASES[phrase], size
                break
        else:
            w = words[i]
            v, step = (1.0 if w in POSITIVE else -1.0 if w in NEGATIVE else 0.0), 1
        if v and i > 0 and words[i - 1] in NEGATIONS:
            v = -v
        total += v
        i += step
    total += sum(val * text.count(e) for e, val in EMOJI.items())
    return math.tanh(total / 1.5)


def headline_tone(item: NewsItem) -> float:
    """Ton d'un titre : score précalculé (FinBERT) s'il existe, sinon lexique financier."""
    return item.tone if item.tone is not None else score_text(item.headline)


def _age_days(ts: datetime, now: datetime) -> float:
    return max(0.0, (now - ts).total_seconds() / 86400)


def news_score(items: list[NewsItem], now: datetime, half_life: float) -> tuple[float, float]:
    """Moyenne pondérée (fiabilité x décroissance temporelle) et poids total."""
    num = den = 0.0
    for it in items:
        w = source_reliability(it.source) * 0.5 ** (_age_days(it.published, now) / half_life)
        num += w * headline_tone(it)
        den += w
    return (num / den if den else 0.0), den


def social_score(posts: list[SocialPost]) -> tuple[float, float]:
    num = den = 0.0
    for p in posts:
        w = math.log1p(p.likes + 1) * (1.0 if p.author_age_days >= 90 else 0.3)
        num += w * score_text(p.text)
        den += w
    return (num / den if den else 0.0), den


def analyze_sentiment(
    news: list[NewsItem],
    posts: list[SocialPost],
    now: datetime,
    social_trust: float = 1.0,
) -> tuple[PillarResult, PillarResult, dict]:
    """`news` doit déjà être filtré des rumeurs non confirmées (voir coherence)."""
    short = PillarResult("sentiment", "court")
    medium = PillarResult("sentiment", "moyen")

    news = [n for n in news if n.source not in EVENT_SOURCES]
    recent = [n for n in news if _age_days(n.published, now) <= 7]
    s_news, _ = news_score(recent, now, half_life=3.0)
    coverage = _coverage(recent, 1.2)  # peu de news fiables => signal atténué
    short.signals.append(Signal("News 7 jours", s_news, s_news * coverage, 0.6,
                                f"{len(recent)} article(s), ton {_tone(s_news)}"))

    recent_posts = [p for p in posts if _age_days(p.posted, now) <= 3]
    s_soc, _ = social_score(recent_posts)
    older = [p for p in posts if 3 < _age_days(p.posted, now) <= 14]
    buzz = (len(recent_posts) / 3) / (len(older) / 11) if older else 1.0
    short.signals.append(Signal("Réseaux sociaux 3 jours", s_soc, clip(s_soc * social_trust),
                                0.4 * social_trust if recent_posts else 0.0,
                                f"{len(recent_posts)} messages, ton {_tone(s_soc)}, buzz x{buzz:.1f}"
                                + ("" if social_trust > 0.8 else f", confiance réduite ({social_trust:.0%})")))

    month = [n for n in news if _age_days(n.published, now) <= 30]
    s_month, _ = news_score(month, now, half_life=10.0)
    medium.signals.append(Signal("News 30 jours", s_month, s_month * _coverage(month, 2.0), 0.8,
                                 f"{len(month)} article(s), ton {_tone(s_month)}"))
    # Inflexion : ton de la semaine vs ton des 3 semaines précédentes (périodes disjointes).
    # Sans news de part et d'autre, pas d'inflexion mesurable : l'absence d'information
    # ne doit pas être lue comme une dégradation du ton.
    prior = [n for n in month if _age_days(n.published, now) > 7]
    if recent and prior:
        s_prior, _ = news_score(prior, now, half_life=10.0)
        trend = s_news - s_prior
        medium.signals.append(Signal(
            "Inflexion du ton", trend, clip(trend) * min(_coverage(recent, 1.2), _coverage(prior, 1.2)), 0.2,
            "le ton s'améliore" if trend > 0.1 else "le ton se dégrade" if trend < -0.1 else "ton stable"))

    stats = {"news_7d": s_news, "social_3d": s_soc, "buzz": buzz, "news_count_7d": float(len(recent))}
    return short, medium, stats


def _coverage(items: list[NewsItem], full: float) -> float:
    """Somme des fiabilités des sources, rapportée au niveau jugé suffisant."""
    return min(1.0, sum(source_reliability(n.source) for n in items) / full)


def _tone(s: float) -> str:
    return "positif" if s > 0.15 else "négatif" if s < -0.15 else "neutre"
