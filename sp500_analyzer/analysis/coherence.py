"""Moteur de cohérence : vérifie la qualité de chaque source et leur accord.

Objectif : ne retenir que les données de marché cohérentes entre elles.
  1. Qualité des cours   : séances manquantes, OHLC incohérents, données périmées.
  2. Mouvements anormaux : un gros mouvement doit être expliqué par une news.
  3. News                : une info relayée uniquement par des sources peu fiables
                           est traitée comme une rumeur et exclue du calcul.
  4. Réseaux sociaux     : détection de messages dupliqués / comptes récents
                           (campagnes coordonnées, bots) => poids réduit.
  5. Croisement          : prix, news et social vont-ils dans le même sens ?
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..models import Bar, Flag, NewsItem, SocialPost
from ..universe import RELIABLE_THRESHOLD, UNRELIABLE_THRESHOLD, source_reliability
from .indicators import mean, pct_returns, stdev
from .sentiment import score_text, social_score

_NORMALIZE = re.compile(r"[^a-z0-9$ ]+")


@dataclass
class CoherenceResult:
    flags: list[Flag] = field(default_factory=list)
    data_quality: float = 1.0
    coherence: float = 1.0
    trusted_news: list[NewsItem] = field(default_factory=list)
    social_trust: float = 1.0
    price_trust: float = 1.0
    stats: dict[str, float] = field(default_factory=dict)

    def add(self, code: str, severity: str, message: str) -> None:
        self.flags.append(Flag(code, severity, message))


def check_prices(bars: list[Bar], calendar: list[date], as_of: date, res: CoherenceResult) -> None:
    have = {b.day for b in bars}
    window = [d for d in calendar if bars and d >= bars[0].day]
    missing = [d for d in window if d not in have]
    if missing:
        recent = [d for d in missing if d >= calendar[-min(20, len(calendar))]]
        res.add("MISSING_BARS", "warning" if recent else "info",
                f"{len(missing)} séance(s) manquante(s) dans les cours"
                + (f" dont {', '.join(d.isoformat() for d in recent)}" if recent else ""))
        res.data_quality -= min(0.3, 0.05 * len(missing) + 0.1 * len(recent))

    broken = [b for b in bars if b.low > min(b.open, b.close) or b.high < max(b.open, b.close) or b.close <= 0]
    if broken:
        res.add("OHLC_INCONSISTENT", "critical", f"{len(broken)} barre(s) OHLC incohérente(s)")
        res.data_quality -= min(0.4, 0.1 * len(broken))

    if not bars or bars[-1].day < as_of:
        res.add("STALE_PRICES", "critical", "Le dernier cours disponible n'est pas celui de la dernière séance")
        res.data_quality -= 0.4


# Seuils de l'alerte « mouvement inexpliqué » (voir docs/AUDIT.md pour leur calibration).
UNEXPLAINED_Z = 4.0
UNEXPLAINED_VOLUME = 2.5


def check_abnormal_moves(bars: list[Bar], news: list[NewsItem], res: CoherenceResult) -> None:
    """Un mouvement > UNEXPLAINED_Z écarts-types ou un volume > UNEXPLAINED_VOLUME fois la
    normale doit être expliqué par une news."""
    closes = [b.close for b in bars]
    rets = pct_returns(closes)
    if len(rets) < 70:
        return
    for k in range(1, 6):
        i = len(bars) - k
        base = rets[i - 61:i - 1]
        sd = stdev(base) or 0.01
        r = rets[i - 1]
        z = r / sd
        vol_ratio = bars[i].volume / (mean([b.volume for b in bars[i - 51:i - 1]]) or 1)
        if abs(z) < UNEXPLAINED_Z and vol_ratio < UNEXPLAINED_VOLUME:
            continue
        day = bars[i].day
        if explaining_news(bars, i, news):
            continue
        res.add("UNEXPLAINED_MOVE", "warning",
                f"Mouvement de {r * 100:+.1f}% ({z:+.1f} σ, volume x{vol_ratio:.1f}) le {day.isoformat()} "
                "sans news fiable pour l'expliquer (fuite, erreur de flux ou flux spéculatif ?)")
        res.price_trust -= 0.3
        res.coherence -= 0.2


def filter_news(news: list[NewsItem], now: datetime, res: CoherenceResult) -> None:
    """Exclut les infos que seules des sources peu fiables rapportent.

    Les sources intermédiaires (fiabilité >= 0,4) sont conservées : leur poids
    réduit est appliqué dans le calcul du sentiment.
    """
    for item in news:
        if source_reliability(item.source) >= UNRELIABLE_THRESHOLD:
            res.trusted_news.append(item)
            continue
        window = timedelta(hours=48)
        confirmed = any(
            other is not item
            and source_reliability(other.source) >= RELIABLE_THRESHOLD
            and abs(other.published - item.published) <= window
            and (score_text(other.headline) > 0) == (score_text(item.headline) > 0)
            for other in news
        )
        if confirmed:
            res.trusted_news.append(item)
        elif now - item.published <= timedelta(days=14):
            res.add("UNCONFIRMED_RUMOR", "warning",
                    f"Info non confirmée par une source fiable ({item.source}) : « {item.headline} » — exclue")
            res.coherence -= 0.15


def check_social(posts: list[SocialPost], now: datetime, res: CoherenceResult) -> None:
    recent = [p for p in posts if now - p.posted <= timedelta(days=3)]
    if len(recent) < 5:
        res.stats["bot_score"] = 0.0
        return
    # Regroupe les messages quasi identiques (texte normalisé, 6 premiers mots).
    clusters: dict[str, list[SocialPost]] = {}
    for p in recent:
        key = " ".join(_NORMALIZE.sub("", p.text.lower()).split()[:6])
        clusters.setdefault(key, []).append(p)
    # Un message banal repris par des comptes établis est normal ; un même message
    # martelé majoritairement par des comptes récents signale une campagne coordonnée.
    coordinated = sum(
        len(c) for c in clusters.values()
        if len(c) >= 5 and sum(p.author_age_days < 30 for p in c) / len(c) > 0.5
    ) / len(recent)
    young = sum(1 for p in recent if p.author_age_days < 30) / len(recent)
    bot_score = min(1.0, 1.5 * coordinated + 0.5 * young)
    res.stats["bot_score"] = bot_score
    if bot_score > 0.3:
        res.add("SUSPECTED_BOTS", "warning",
                f"{coordinated:.0%} de messages coordonnés, {young:.0%} de comptes de moins de 30 jours : "
                "possible campagne de manipulation — poids des réseaux sociaux réduit")
        res.social_trust = max(0.1, 1 - bot_score)
        res.coherence -= 0.15


def reaction_index(bars: list[Bar], published: datetime) -> int | None:
    """Indice de la séance où le marché réagit à une news.

    Publiée après la clôture (16h) => la réaction se lit à la séance suivante.
    """
    day = published.date() + (timedelta(days=1) if published.hour >= 16 else timedelta())
    i = bisect_left(bars, day, key=lambda b: b.day)  # recherche dichotomique : O(log n)
    return i if i < len(bars) else None


def explaining_news(bars: list[Bar], i: int, news: list[NewsItem]) -> list[NewsItem]:
    """News de source fiable pouvant expliquer le mouvement de la séance i.

    Une news explique la séance où le marché y réagit (voir reaction_index : après 16h ou
    le week-end, c'est la séance suivante), ou la séance d'après (réaction étalée sur deux
    jours). Une news publiée après la clôture de la séance i ne peut pas l'expliquer.
    """
    out = []
    for n in news:
        if source_reliability(n.source) < RELIABLE_THRESHOLD:
            continue
        j = reaction_index(bars, n.published)
        if j is not None and i - 1 <= j <= i:
            out.append(n)
    return out


def cross_check(bars: list[Bar], posts: list[SocialPost], now: datetime, res: CoherenceResult) -> None:
    """Croise les sources : la réaction du prix confirme-t-elle les news ? le social ?"""
    closes = [b.close for b in bars]
    if len(closes) < 60:
        return
    rets = pct_returns(closes)
    sd = stdev(rets[-61:-1]) or 0.01

    # 1. Réaction du prix le jour de chaque news fiable et tranchée de la semaine.
    confirmed, divergent = [], []
    strong_tones = []
    for n in res.trusted_news:
        tone = score_text(n.headline)
        if now - n.published > timedelta(days=7) or abs(tone) <= 0.3:
            continue
        strong_tones.append(tone)
        i = reaction_index(bars, n.published)
        if i is None or i == 0:
            continue
        z = rets[i - 1] / sd
        if abs(z) < 1:
            continue
        (confirmed if z * tone > 0 else divergent).append((n, rets[i - 1]))

    news_dir = mean(strong_tones) if strong_tones else 0.0
    recent = [p for p in posts if now - p.posted <= timedelta(days=3)]
    soc, _ = social_score(recent)
    r5 = closes[-1] / closes[-6] - 1
    price_dir = r5 / (sd * 5 ** 0.5)
    res.stats.update({"price_z_5d": price_dir, "news_dir": news_dir, "social_dir": soc})

    for n, r in divergent[:1]:
        res.add("PRICE_NEWS_DIVERGENCE", "warning",
                f"Le titre a fait {r * 100:+.1f}% le jour de la news « {n.headline} » ({n.source}), "
                "à l'inverse de son ton : information déjà intégrée ou marché sceptique")
        res.coherence -= 0.2
    if confirmed and not divergent:
        n, r = confirmed[0]
        res.add("CONFIRMED_BY_NEWS", "info",
                f"Mouvement de {r * 100:+.1f}% cohérent avec la news « {n.headline} » ({n.source})")

    # 2. Réseaux sociaux vs news et prix.
    if abs(soc) > 0.4 and not strong_tones and res.social_trust < 1:
        res.add("HYPE_WITHOUT_CONFIRMATION", "warning",
                "Engouement social fort sans news fiable ni mouvement de prix correspondant")
        res.coherence -= 0.1
    elif abs(soc) > 0.4 and abs(price_dir) > 0.8 and soc * price_dir < 0:
        res.add("PRICE_SOCIAL_DIVERGENCE", "info", "Le ton des réseaux sociaux contredit le mouvement du prix")
        res.coherence -= 0.05


def assess(
    bars: list[Bar],
    calendar: list[date],
    news: list[NewsItem],
    posts: list[SocialPost],
    as_of: date,
    now: datetime,
) -> CoherenceResult:
    res = CoherenceResult()
    check_prices(bars, calendar, as_of, res)
    check_abnormal_moves(bars, news, res)
    filter_news(news, now, res)
    check_social(posts, now, res)
    cross_check(bars, posts, now, res)
    res.data_quality = max(0.1, min(1.0, res.data_quality))
    res.coherence = max(0.1, min(1.0, res.coherence))
    res.price_trust = max(0.3, res.price_trust)
    return res
