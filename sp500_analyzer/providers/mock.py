"""Source de données SIMULÉE, déterministe.

Génère un historique de cours crédible (~1 an) puis impose une "semaine
dernière" scénarisée (les 5 dernières séances) avec des événements typiques :
news fortes cohérentes avec le prix, mouvement inexpliqué, rumeur relayée par
des comptes suspects, divergence news/prix, trou dans les données...

Ces cas servent à démontrer le moteur de cohérence. AUCUNE de ces données
n'est réelle.
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ..models import Bar, NewsItem, Security, Series, SocialPost
from ..universe import INDEX, SP500_SAMPLE, SecurityProfile
from .base import DataProvider

US_MARKET_HOLIDAYS = {
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
}

MARKET_DAILY_VOL = 0.0085
INDEX_TARGET_LEVEL = 6640.0


def trading_calendar(end: date, count: int) -> list[date]:
    days: list[date] = []
    d = end
    while len(days) < count:
        if d.weekday() < 5 and d not in US_MARKET_HOLIDAYS:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


def _stable_seed(*parts: object) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


@dataclass
class Scenario:
    """Événement imposé sur une séance de la semaine dernière (0 = lundi)."""

    ticker: str
    day: int
    ret: float  # rendement idiosyncratique ajouté
    vol_mult: float = 1.0
    headlines: list[tuple[str, str]] = field(default_factory=list)
    social_bias: float = 0.0
    social_boost: float = 1.0
    bot_campaign: bool = False
    drop_bar: bool = False


LAST_WEEK_MARKET = [-0.0062, 0.0031, 0.0108, -0.0041, 0.0052]

SCENARIOS: list[Scenario] = [
    Scenario("NVDA", 1, 0.045, 2.2, [
        ("Reuters", "Nvidia shares jump as major cloud providers raise AI capex guidance"),
        ("Bloomberg", "Hyperscalers boost data-center spending, strong demand outlook for Nvidia"),
    ], social_bias=0.6, social_boost=3.0),
    Scenario("TSLA", 2, -0.072, 3.0, [
        ("Reuters", "Tesla cuts full-year delivery guidance, shares slump"),
        ("WSJ", "Tesla warns of weak demand in Europe and China"),
    ], social_bias=-0.5, social_boost=4.0),
    Scenario("PFE", 0, -0.055, 2.8, [
        ("Reuters", "Pfizer halts late-stage trial after safety review"),
        ("FiercePharma", "Pfizer trial halt is a setback for its pipeline, analysts downgrade"),
    ], social_bias=-0.4, social_boost=2.0),
    Scenario("JPM", 3, 0.031, 1.8, [
        ("Bloomberg", "JPMorgan announces record buyback and raises dividend"),
        ("CNBC", "JPMorgan boosts shareholder returns after strong stress test"),
    ], social_bias=0.4, social_boost=1.5),
    Scenario("XOM", 2, 0.022, 1.6, [
        ("Reuters", "Oil rallies as OPEC+ agrees to extend output cuts, Exxon gains"),
    ], social_bias=0.3),
    Scenario("CVX", 2, 0.018, 1.5, [
        ("Bloomberg", "Chevron rises with crude after OPEC+ extends output cuts"),
    ], social_bias=0.3),
    # Divergence : news négative de source fiable mais le titre monte.
    Scenario("UNH", 2, 0.035, 1.6, [
        ("Bloomberg", "UnitedHealth faces expanded DOJ probe into Medicare billing"),
    ], social_bias=-0.2),
    # Mouvement violent sans aucune news : anomalie à signaler.
    Scenario("AMD", 3, 0.088, 3.2, [], social_bias=0.3, social_boost=1.5),
    # Rumeur non confirmée + campagne de comptes suspects, prix quasi inchangé.
    Scenario("META", 3, 0.002, 1.0, [
        ("StockBuzzDaily", "META rumored to acquire major gaming studio, insiders say"),
    ], social_bias=0.9, social_boost=3.0, bot_campaign=True),
    Scenario("AAPL", 4, 0.015, 1.4, [
        ("Bloomberg", "Apple iPhone demand tops estimates in early sales data"),
    ], social_bias=0.4, social_boost=1.5),
    Scenario("BA", 1, -0.031, 2.0, [
        ("Reuters", "FAA orders new inspections on Boeing 737 MAX fleet"),
    ], social_bias=-0.4, social_boost=2.0),
    Scenario("LLY", 3, 0.032, 2.0, [
        ("Reuters", "Eli Lilly obesity pill shows strong results in phase 3 trial"),
        ("STAT", "Lilly's oral GLP-1 data impresses analysts"),
    ], social_bias=0.5, social_boost=2.0),
    # Séance manquante dans le flux de cours (problème de qualité de données).
    Scenario("INTC", 1, 0.0, 1.0, [], drop_bar=True),
]

MARKET_HEADLINES: list[tuple[int, str, str]] = [
    (0, "Reuters", "Wall Street dips as investors turn cautious ahead of Fed decision"),
    (2, "Reuters", "Fed holds rates steady, signals openness to cut later this year"),
    (2, "Bloomberg", "Treasury yields fall after dovish Fed statement"),
    (2, "Reuters", "Oil rallies as OPEC+ agrees to extend output cuts"),
    (3, "CNBC", "Jobless claims rise slightly, labor market cooling gradually"),
    (4, "Reuters", "PCE inflation cools more than expected in August"),
]

POSITIVE_TEMPLATES = [
    "{name} beats expectations as margins improve",
    "Analysts upgrade {name}, citing strong growth",
    "{name} gains after upbeat guidance",
    "{name} wins major contract, shares rise",
]
NEGATIVE_TEMPLATES = [
    "{name} slips after analyst downgrade",
    "{name} faces margin pressure, outlook weak",
    "{name} shares fall on cautious guidance",
    "Concerns grow over {name} slowing demand",
]
NEUTRAL_TEMPLATES = [
    "{name} to present at industry conference next month",
    "{name} announces executive appointment",
    "{name} files quarterly report with regulators",
]
BACKGROUND_SOURCES = ["Reuters", "Bloomberg", "CNBC", "MarketWatch", "Barron's", "Seeking Alpha"]

SOCIAL_POSITIVE = [
    "${t} looking strong, adding more 📈",
    "Bullish on ${t}, great momentum",
    "${t} breakout confirmed, long here",
    "Loving the ${t} setup, buy the dip",
]
SOCIAL_NEGATIVE = [
    "${t} looks weak, taking profits",
    "Bearish on ${t}, this is overvalued 📉",
    "Sold my ${t}, too much risk here",
    "${t} breaking down, stay away",
]
SOCIAL_NEUTRAL = [
    "Watching ${t} today",
    "Anyone holding ${t} into next week?",
    "${t} chart for reference",
]
BOT_TEXTS = [
    "$META acquisition coming this week 🚀🚀 load up before announcement",
    "$META acquisition coming this week!! 🚀🚀 load up before the announcement",
    "$META ACQUISITION COMING THIS WEEK 🚀🚀 load up before announcement",
]


class MockDataProvider(DataProvider):
    """Données simulées reproductibles (même graine = mêmes données)."""

    def __init__(self, as_of: date = date(2026, 9, 25), seed: int = 42, history: int = 300):
        self.as_of = as_of
        self.seed = seed
        self._days = trading_calendar(as_of, history)
        self._last_week = self._days[-5:]
        self._profiles = {p.security.ticker: p for p in SP500_SAMPLE}
        self._scenarios: dict[str, list[Scenario]] = {}
        for sc in SCENARIOS:
            self._scenarios.setdefault(sc.ticker, []).append(sc)

        rng = random.Random(seed)
        n = len(self._days)
        self._market = [rng.gauss(0.0006, MARKET_DAILY_VOL) for _ in range(n)]
        # Petite correction il y a ~3 mois pour donner du relief à l'historique.
        for i in range(n - 70, n - 55):
            self._market[i] -= 0.0045
        self._market[-5:] = LAST_WEEK_MARKET

        self._bars: dict[str, list[Bar]] = {}
        self._returns: dict[str, list[float]] = {}
        for ticker, prof in self._profiles.items():
            self._bars[ticker], self._returns[ticker] = self._simulate(prof)
        self._bars[INDEX.ticker] = self._simulate_index()

        self._news = self._generate_news()
        self._social = self._generate_social()
        self._macro = self._generate_macro()

    # ------------------------------------------------------------------ API

    def universe(self) -> list[Security]:
        return [p.security for p in SP500_SAMPLE]

    def index(self) -> Security:
        return INDEX

    def trading_days(self) -> list[date]:
        return list(self._days)

    def price_history(self, ticker: str) -> list[Bar]:
        return list(self._bars[ticker])

    def news(self, ticker: str | None, since: datetime) -> list[NewsItem]:
        return [n for n in self._news if n.ticker == ticker and n.published >= since]

    def social_posts(self, ticker: str, since: datetime) -> list[SocialPost]:
        return [p for p in self._social.get(ticker, []) if p.posted >= since]

    def macro(self) -> dict[str, Series]:
        return {k: list(v) for k, v in self._macro.items()}

    # ------------------------------------------------------------ Simulation

    def _simulate(self, prof: SecurityProfile) -> tuple[list[Bar], list[float]]:
        t = prof.security.ticker
        rng = random.Random(_stable_seed(self.seed, t))
        n = len(self._days)
        daily_vol = prof.vol / math.sqrt(252)
        systematic = prof.security.beta * MARKET_DAILY_VOL
        idio_sd = math.sqrt(max(daily_vol**2 - systematic**2, (0.35 * daily_vol) ** 2))
        drift = prof.drift / 252

        events = {sc.day: sc for sc in self._scenarios.get(t, [])}
        returns, vol_mults = [], []
        for i in range(n):
            week_idx = i - (n - 5)
            noise_scale = 0.3 if week_idx >= 0 else 1.0
            r = prof.security.beta * self._market[i] + drift + rng.gauss(0, idio_sd * noise_scale)
            vm = 1.0
            if week_idx in events:
                r += events[week_idx].ret
                vm = events[week_idx].vol_mult
            returns.append(r)
            vol_mults.append(vm)

        closes, price = [], 100.0
        for r in returns:
            price *= 1 + r
            closes.append(price)
        scale = prof.price * (1 + rng.gauss(0, 0.03)) / closes[-1]

        bars: list[Bar] = []
        prev = 100.0 * scale
        drop = {self._last_week[sc.day] for sc in self._scenarios.get(t, []) if sc.drop_bar}
        for i, d in enumerate(self._days):
            close = closes[i] * scale
            open_ = prev * (1 + returns[i] * 0.4 + rng.gauss(0, idio_sd * 0.2))
            high = max(open_, close) * (1 + abs(rng.gauss(0, daily_vol * 0.4)))
            low = min(open_, close) * (1 - abs(rng.gauss(0, daily_vol * 0.4)))
            surprise = abs(returns[i] - prof.security.beta * self._market[i]) / daily_vol
            volume = prof.avg_volume * max(0.3, 1 + 0.2 * rng.gauss(0, 1)) * (1 + 0.15 * surprise) * vol_mults[i]
            prev = close
            if d in drop:
                continue
            bars.append(Bar(d, round(open_, 2), round(high, 2), round(low, 2), round(close, 2), int(volume)))
        return bars, returns

    def _simulate_index(self) -> list[Bar]:
        rng = random.Random(_stable_seed(self.seed, INDEX.ticker))
        growth = math.prod(1 + r for r in self._market)
        level = INDEX_TARGET_LEVEL / growth
        bars = []
        for d, r in zip(self._days, self._market):
            open_ = level * (1 + r * 0.3)
            close = level * (1 + r)
            high = max(open_, close) * (1 + abs(rng.gauss(0, 0.003)))
            low = min(open_, close) * (1 - abs(rng.gauss(0, 0.003)))
            volume = int(3_800_000_000 * (1 + 0.15 * rng.gauss(0, 1) + 20 * abs(r)))
            bars.append(Bar(d, round(open_, 2), round(high, 2), round(low, 2), round(close, 2), volume))
            level = close
        return bars

    def _at(self, d: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(d, time(hour, minute))

    def _generate_news(self) -> list[NewsItem]:
        rng = random.Random(_stable_seed(self.seed, "news"))
        items: list[NewsItem] = []

        for sc in SCENARIOS:
            d = self._last_week[sc.day]
            for k, (source, headline) in enumerate(sc.headlines):
                items.append(NewsItem(sc.ticker, self._at(d, 7 + k, 30), source, headline))

        for day, source, headline in MARKET_HEADLINES:
            items.append(NewsItem(None, self._at(self._last_week[day], 14 + day % 3), source, headline))

        # Fond de news des 6 dernières semaines, globalement cohérent avec les cours.
        n = len(self._days)
        for ticker, prof in self._profiles.items():
            rets = self._returns[ticker]
            i = n - 30 - rng.randint(0, 4)
            while i < n - 5:
                recent = sum(rets[i - 5:i])
                bias = math.tanh(recent / (prof.vol / math.sqrt(252) * 3)) + rng.gauss(0, 0.5)
                if bias > 0.35:
                    tpl = rng.choice(POSITIVE_TEMPLATES)
                elif bias < -0.35:
                    tpl = rng.choice(NEGATIVE_TEMPLATES)
                else:
                    tpl = rng.choice(NEUTRAL_TEMPLATES)
                items.append(NewsItem(
                    ticker, self._at(self._days[i], rng.randint(6, 18)),
                    rng.choice(BACKGROUND_SOURCES), tpl.format(name=prof.security.name),
                ))
                i += rng.randint(3, 6)

        items.sort(key=lambda x: x.published)
        return items

    def _generate_social(self) -> dict[str, list[SocialPost]]:
        rng = random.Random(_stable_seed(self.seed, "social"))
        out: dict[str, list[SocialPost]] = {}
        n = len(self._days)
        window = self._days[-10:]
        for ticker, prof in self._profiles.items():
            posts: list[SocialPost] = []
            events = {sc.day: sc for sc in self._scenarios.get(ticker, [])}
            daily_vol = prof.vol / math.sqrt(252)
            for j, d in enumerate(window):
                week_idx = j - 5
                r = self._returns[ticker][n - 10 + j]
                bias = 0.6 * math.tanh(r / daily_vol)
                count = prof.popularity * 2
                sc = events.get(week_idx) or events.get(week_idx - 1)  # buzz jusqu'au lendemain
                if sc:
                    bias = 0.4 * bias + sc.social_bias
                    count = int(count * sc.social_boost)
                for _ in range(max(1, int(count * rng.uniform(0.7, 1.3)))):
                    tone = bias + rng.gauss(0, 0.6)
                    pool = SOCIAL_POSITIVE if tone > 0.3 else SOCIAL_NEGATIVE if tone < -0.3 else SOCIAL_NEUTRAL
                    author = f"user{rng.randint(1, 5000)}"
                    posts.append(SocialPost(
                        ticker, self._at(d, rng.randint(8, 21), rng.randint(0, 59)),
                        rng.choice(["X", "Reddit", "StockTwits"]), author,
                        _stable_seed(author) % 3000 + 60, int(rng.expovariate(1 / 25)),
                        rng.choice(pool).replace("{t}", ticker),
                    ))
                if sc and sc.bot_campaign and sc is events.get(week_idx):
                    for b in range(45):
                        posts.append(SocialPost(
                            ticker, self._at(d, rng.randint(9, 20), rng.randint(0, 59)),
                            rng.choice(["X", "StockTwits"]), f"alpha_trader_{rng.randint(100, 999)}",
                            rng.randint(1, 20), rng.randint(0, 4), BOT_TEXTS[b % len(BOT_TEXTS)],
                        ))
            posts.sort(key=lambda p: p.posted)
            out[ticker] = posts
        return out

    def _generate_macro(self) -> dict[str, Series]:
        rng = random.Random(_stable_seed(self.seed, "macro"))
        days, n = self._days, len(self._days)
        macro: dict[str, Series] = {}

        # Taux 10 ans : marche aléatoire puis détente sur le dernier mois (Fed accommodante).
        y10, y10s = 4.35, []
        last_week_moves = [-0.03, -0.01, -0.07, 0.02, -0.02]
        for i in range(n):
            if i >= n - 5:
                y10 += last_week_moves[i - (n - 5)]
            else:
                y10 += rng.gauss(-0.006 if i >= n - 25 else 0.0, 0.035)
            y10s.append(round(y10, 3))
        macro["us10y"] = list(zip(days, y10s))
        spread = [0.30 + 0.15 * i / n + rng.gauss(0, 0.02) for i in range(n)]
        macro["us2y"] = [(d, round(y - s, 3)) for d, y, s in zip(days, y10s, spread)]

        fed_cut = days[n - 70]
        macro["fed_funds"] = [(d, 4.00 if d < fed_cut else 3.75) for d in days]

        # VIX dérivé de la volatilité réalisée du marché.
        vix = []
        for i in range(n):
            w = self._market[max(0, i - 19):i + 1]
            m = sum(w) / len(w)
            rv = math.sqrt(sum((x - m) ** 2 for x in w) / max(1, len(w) - 1)) * math.sqrt(252) * 100
            vix.append(round(max(11.0, 1.1 * rv + 4 + rng.gauss(0, 0.6)), 2))
        vix[-5:] = [18.4, 17.6, 15.9, 16.4, 15.7]
        macro["vix"] = list(zip(days, vix))

        wti, wtis = 66.0, []
        oil_week = [0.012, 0.008, 0.031, 0.003, 0.006]
        for i in range(n):
            wti *= 1 + (oil_week[i - (n - 5)] if i >= n - 5 else rng.gauss(0, 0.017))
            wtis.append(round(wti, 2))
        macro["wti"] = list(zip(days, wtis))

        pc = [round(0.86 + rng.gauss(0, 0.07), 2) for _ in range(n)]
        pc[-5:] = [1.04, 0.97, 0.88, 0.91, 0.84]
        macro["put_call"] = list(zip(days, pc))

        months = [date(self.as_of.year - (1 if m > self.as_of.month else 0), m, 1)
                  for m in list(range(self.as_of.month + 1, 13)) + list(range(1, self.as_of.month + 1))]
        cpi = [3.1, 3.1, 3.0, 3.0, 2.9, 3.0, 2.9, 2.9, 2.8, 2.8, 2.7, 2.6]
        unemployment = [4.1, 4.1, 4.2, 4.2, 4.2, 4.2, 4.3, 4.3, 4.3, 4.3, 4.4, 4.4]
        pmi = [49.0, 48.7, 48.4, 48.1, 48.5, 48.3, 48.9, 49.2, 49.6, 50.1, 50.4, 51.0]
        macro["cpi_yoy"] = list(zip(months, cpi))
        macro["unemployment"] = list(zip(months, unemployment))
        macro["ism_pmi"] = list(zip(months, pmi))

        thursdays = [d for d in days if d.weekday() == 3][-26:]
        aaii = [round(5 + 8 * math.sin(k / 4) + rng.gauss(0, 4), 1) for k in range(len(thursdays))]
        aaii[-1] = 14.2
        macro["aaii_spread"] = list(zip(thursdays, aaii))
        return macro
