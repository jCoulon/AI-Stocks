"""Pilier « recherche » : facteurs issus de la littérature académique en finance empirique.

Chaque facteur reproduit (sous une forme simplifiée, adaptée aux données disponibles) un
résultat publié dans une revue à comité de lecture. Les facteurs « transversaux » sont
classés en percentiles au sein de l'univers : ce qui compte est le rang relatif du titre,
comme dans les portefeuilles déciles des articles d'origine.

Mises en garde intégrées aux pondérations :
- beaucoup d'anomalies sont plus faibles sur les grandes capitalisations et après leur
  publication (Hou, Xue & Zhang, 2020 ; McLean & Pontiff, 2016) ;
- la dérive / le retournement après news (Chan, 2003) concerne surtout les petites valeurs.
Les poids ci-dessous reflètent donc la robustesse attendue sur des valeurs du S&P 500.

Toutes les fonctions de calcul ne lisent que les données qu'on leur passe : appelées sur
un historique tronqué à une date t, elles n'utilisent aucune information postérieure
(indispensable au backtest, voir analysis/backtest.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from ..models import Bar, NewsItem, PillarResult, Signal, SocialPost
from .coherence import explaining_news
from .indicators import clip, closes_on_calendar, mean, pct_returns, stdev


# --------------------------------------------------------------------------- références

REFERENCES: dict[str, str] = {
    "JT93": "Jegadeesh & Titman (1993), « Returns to Buying Winners and Selling Losers », Journal of Finance",
    "MOP12": "Moskowitz, Ooi & Pedersen (2012), « Time Series Momentum », Journal of Financial Economics",
    "BSC15": "Barroso & Santa-Clara (2015), « Momentum Has Its Moments », Journal of Financial Economics",
    "DM16": "Daniel & Moskowitz (2016), « Momentum Crashes », Journal of Financial Economics",
    "J90": "Jegadeesh (1990), « Evidence of Predictable Behavior of Security Returns », Journal of Finance",
    "L90": "Lehmann (1990), « Fads, Martingales, and Market Efficiency », Quarterly Journal of Economics",
    "GH04": "George & Hwang (2004), « The 52-Week High and Momentum Investing », Journal of Finance",
    "AHXZ06": "Ang, Hodrick, Xing & Zhang (2006), « The Cross-Section of Volatility and Expected Returns », Journal of Finance",
    "FP14": "Frazzini & Pedersen (2014), « Betting Against Beta », Journal of Financial Economics",
    "BCW11": "Bali, Cakici & Whitelaw (2011), « Maxing Out: Stocks as Lotteries and the Cross-Section of Expected Returns », Journal of Financial Economics",
    "GKM01": "Gervais, Kaniel & Mingelgrin (2001), « The High-Volume Return Premium », Journal of Finance",
    "MG99": "Moskowitz & Grinblatt (1999), « Do Industries Explain Momentum? », Journal of Finance",
    "C03": "Chan (2003), « Stock Price Reaction to News and No-News: Drift and Reversal After Headlines », Journal of Financial Economics",
    "DEG11": "Da, Engelberg & Gao (2011), « In Search of Attention », Journal of Finance",
    "BO08": "Barber & Odean (2008), « All That Glitters: The Effect of Attention and News on the Buying Behavior of Individual and Institutional Investors », Review of Financial Studies",
    "LM88": "Lo & MacKinlay (1988), « Stock Market Prices Do Not Follow Random Walks: Evidence from a Simple Specification Test », Review of Financial Studies",
    "B86": "Bollerslev (1986), « Generalized Autoregressive Conditional Heteroskedasticity », Journal of Econometrics",
    "MP16": "McLean & Pontiff (2016), « Does Academic Research Destroy Stock Return Predictability? », Journal of Finance",
    "HXZ20": "Hou, Xue & Zhang (2020), « Replicating Anomalies », Review of Financial Studies",
    "HLZ16": "Harvey, Liu & Zhu (2016), « … and the Cross-Section of Expected Returns », Review of Financial Studies",
}


def short_ref(key: str) -> str:
    """« Jegadeesh & Titman (1993) » à partir de la clé."""
    return REFERENCES[key].split(", «")[0]


@dataclass(frozen=True)
class FactorSpec:
    key: str
    name: str
    horizons: tuple[str, ...]  # "court" et/ou "moyen"
    direction: int  # +1 : valeur élevée => rendement futur plus élevé ; -1 : l'inverse
    weight: float  # robustesse attendue sur grandes capitalisations
    refs: tuple[str, ...]
    cross_sectional: bool = True  # classé en percentile dans l'univers
    price_only: bool = True  # calculable à partir des seuls cours (donc backtestable)


FACTORS: list[FactorSpec] = [
    FactorSpec("mom_12_1", "Momentum 12-1 mois", ("moyen",), +1, 1.0, ("JT93",)),
    FactorSpec("tsmom", "Momentum temporel (ajusté volatilité)", ("moyen",), +1, 0.8, ("MOP12", "BSC15"),
               cross_sectional=False),
    FactorSpec("high52", "Proximité du plus haut 52 sem.", ("moyen",), +1, 0.7, ("GH04",)),
    FactorSpec("ind_mom", "Momentum sectoriel 6 mois", ("moyen",), +1, 0.6, ("MG99",)),
    FactorSpec("ivol", "Volatilité idiosyncratique", ("moyen",), -1, 0.6, ("AHXZ06",)),
    FactorSpec("beta", "Bêta (« betting against beta »)", ("moyen",), -1, 0.4, ("FP14",)),
    FactorSpec("strev", "Retournement 1 mois", ("court",), -1, 0.6, ("J90", "L90")),
    FactorSpec("max", "Effet MAX (rendement journalier max. 1 mois)", ("court", "moyen"), -1, 0.6, ("BCW11",)),
    FactorSpec("abvol", "Prime de volume anormal", ("court",), +1, 0.5, ("GKM01",)),
    FactorSpec("news_drift", "Dérive / retournement après news", ("court", "moyen"), +1, 0.4, ("C03",),
               cross_sectional=False, price_only=False),
    FactorSpec("attention", "Choc d'attention (buzz social)", ("court",), +1, 0.4, ("DEG11", "BO08"),
               cross_sectional=False, price_only=False),
    FactorSpec("attention_rev", "Retournement post-attention", ("moyen",), -1, 0.3, ("DEG11", "BO08"),
               cross_sectional=False, price_only=False),
]
SPECS = {f.key: f for f in FACTORS}


# ------------------------------------------------------------------ données d'entrée

@dataclass
class TickerInputs:
    """Données d'un titre à une date donnée (point-in-time)."""

    bars: list[Bar]
    sector: str
    news: list[NewsItem] = field(default_factory=list)  # news retenues par le contrôleur
    posts: list[SocialPost] = field(default_factory=list)
    now: Optional[datetime] = None


# ------------------------------------------------------------ facteurs sur les cours

def _aligned_returns(bars: list[Bar], index_bars: list[Bar], n: int) -> tuple[list[float], list[float]]:
    """Rendements journaliers du titre et de l'indice sur les dates communes (n dernières)."""
    idx = {b.day: b.close for b in index_bars}
    xs, ys = [], []
    for i in range(max(1, len(bars) - n), len(bars)):
        d0, d1 = bars[i - 1].day, bars[i].day
        if d0 in idx and d1 in idx:
            ys.append(bars[i].close / bars[i - 1].close - 1)
            xs.append(idx[d1] / idx[d0] - 1)
    return ys, xs


def _ols(ys: list[float], xs: list[float]) -> tuple[float, float, list[float]]:
    mx, my = mean(xs), mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 1.0
    alpha = my - beta * mx
    return alpha, beta, [y - alpha - beta * x for x, y in zip(xs, ys)]


def price_factors(bars: list[Bar], index_bars: list[Bar]) -> dict[str, Optional[float]]:
    """Valeurs brutes des facteurs calculables sur les seuls cours et volumes."""
    closes = [b.close for b in bars]
    rets = pct_returns(closes)
    out: dict[str, Optional[float]] = {k: None for k in ("mom_12_1", "tsmom", "high52", "ivol", "beta",
                                                          "strev", "max", "abvol")}
    n = len(closes)
    # Rendements sur N séances mesurés sur le calendrier de l'indice (trous du flux comblés).
    cal = closes_on_calendar(bars, [b.day for b in index_bars]) if index_bars else closes

    def ret(a: int, b: int = 0) -> Optional[float]:
        """Rendement entre t-a et t-b séances."""
        if len(cal) <= a or cal[-a - 1] is None or cal[-b - 1] is None:
            return None
        return cal[-b - 1] / cal[-a - 1] - 1

    if n > 253:
        # Rendement de t-12 mois à t-1 mois : on saute le dernier mois (effet de retournement).
        out["mom_12_1"] = ret(252, 21)
        vol_ann = (stdev(rets[-126:]) or 0.01) * math.sqrt(252)
        # Rendement 12 mois divisé par la volatilité : momentum « à risque constant ».
        r12 = ret(252)
        out["tsmom"] = r12 / vol_ann if r12 is not None else None
    if n >= 252:
        out["high52"] = closes[-1] / max(b.high for b in bars[-252:])
    if n > 22:
        out["strev"] = ret(21)
        out["max"] = max(rets[-21:])
    if n > 60:
        ys, xs = _aligned_returns(bars, index_bars, 63)
        if len(ys) > 30:
            _, _, resid = _ols(ys, xs)
            out["ivol"] = stdev(resid) * math.sqrt(252)
        ys, xs = _aligned_returns(bars, index_bars, 252)
        if len(ys) > 60:
            out["beta"] = _ols(ys, xs)[1]
    if n > 55:
        recent = mean([b.volume for b in bars[-5:]])
        base = mean([b.volume for b in bars[-55:-5]]) or 1
        out["abvol"] = math.log(max(recent, 1) / base)
    return out


def industry_momentum(inputs: dict[str, TickerInputs]) -> dict[str, Optional[float]]:
    """Rendement moyen sur 6 mois du secteur de chaque titre."""
    six_m: dict[str, float] = {}
    for t, x in inputs.items():
        c = [b.close for b in x.bars]
        if len(c) > 127:
            six_m[t] = c[-1] / c[-127] - 1
    by_sector: dict[str, list[float]] = {}
    for t, r in six_m.items():
        by_sector.setdefault(inputs[t].sector, []).append(r)
    return {t: (mean(by_sector[x.sector]) if x.sector in by_sector else None) for t, x in inputs.items()}


# ----------------------------------------------------- facteurs news et attention

def news_drift(bars: list[Bar], news: list[NewsItem]) -> Optional[float]:
    """Chan (2003) : un fort mouvement accompagné d'une news tend à se prolonger (dérive),
    un fort mouvement sans news tend à se retourner. Renvoie None en l'absence de fort mouvement."""
    closes = [b.close for b in bars]
    rets = pct_returns(closes)
    if len(rets) < 70:
        return None
    sd = stdev(rets[-66:-5]) or 0.01
    value, events = 0.0, 0
    for k in range(1, 6):
        r = rets[-k]
        z = r / sd
        if abs(z) < 2:
            continue
        events += 1
        strength = min(abs(z) / 4, 1.0)
        explained = bool(explaining_news(bars, len(bars) - k, news))
        # Continuation si la news explique le mouvement ; retournement (plus faible) sinon.
        value += math.copysign(strength, r) if explained else -0.5 * math.copysign(strength, r)
    return clip(value) if events else None


def attention_shock(posts: list[SocialPost], now: Optional[datetime]) -> Optional[float]:
    """Da, Engelberg & Gao (2011) ; Barber & Odean (2008) : log du buzz (3 j vs 11 j précédents)."""
    if not posts or now is None:
        return None
    # Les comptes de moins de 30 jours sont exclus : une campagne coordonnée (bots)
    # fabrique du buzz sans refléter l'attention réelle des investisseurs.
    genuine = [p for p in posts if p.author_age_days >= 30]
    recent = sum(1 for p in genuine if now - p.posted <= timedelta(days=3))
    older = sum(1 for p in genuine if timedelta(days=3) < now - p.posted <= timedelta(days=14))
    if older == 0:
        return None
    return math.log(max(recent / 3, 0.1) / (older / 11))


# ------------------------------------------------------------------- diagnostics

def variance_ratio(bars: list[Bar], q: int = 5, n: int = 250) -> tuple[float, float]:
    """Test du ratio de variance de Lo & MacKinlay (1988).

    VR > 1 : les rendements s'autocorrèlent positivement (tendance) ;
    VR < 1 : ils se retournent (retour à la moyenne).
    Renvoie (VR, z*) où z* est la statistique robuste à l'hétéroscédasticité de l'article :
    la version homoscédastique signale à tort un régime dans ~10 % des cas sur des rendements
    à volatilité groupée (type GARCH), contre ~6 % pour z* (au seuil nominal de 5 %).
    """
    closes = [b.close for b in bars[-(n + 1):]]
    r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    T = len(r)
    if T < 5 * q:
        return 1.0, 0.0
    mu = mean(r)
    d = [x - mu for x in r]
    ss = sum(x * x for x in d)
    if ss == 0:
        return 1.0, 0.0
    var1 = ss / (T - 1)
    m = q * (T - q + 1) * (1 - q / T)
    varq = sum((sum(r[i:i + q]) - q * mu) ** 2 for i in range(T - q + 1)) / m
    vr = varq / var1
    # θ(q) = Σ_j [2(q-j)/q]² δ(j), δ(j) = T Σ_t d_t² d_{t-j}² / (Σ_t d_t²)²
    theta = sum((2 * (q - j) / q) ** 2 * T * sum(d[t] ** 2 * d[t - j] ** 2 for t in range(j, T)) / ss ** 2
                for j in range(1, q))
    z = (vr - 1) * math.sqrt(T / theta) if theta > 0 else 0.0
    return vr, z


@dataclass
class GarchFit:
    alpha: float
    beta: float
    omega: float
    long_run_var: float
    last_var: float  # variance conditionnelle prévue pour la prochaine séance

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    def horizon_vol(self, h: int) -> float:
        """Volatilité cumulée prévue sur h séances (écart-type du rendement sur h jours)."""
        p = self.persistence
        total = sum(self.long_run_var + p ** (k - 1) * (self.last_var - self.long_run_var) for k in range(1, h + 1))
        return math.sqrt(max(total, 0.0))


def fit_garch(bars: list[Bar], n: int = 500) -> Optional[GarchFit]:
    """GARCH(1,1) de Bollerslev (1986) estimé par maximum de vraisemblance sur une grille,
    avec ciblage de variance (omega = variance de long terme x (1 - alpha - beta))."""
    closes = [b.close for b in bars[-(n + 1):]]
    r = pct_returns(closes)
    if len(r) < 120:
        return None
    mu = mean(r)
    e = [x - mu for x in r]
    var = sum(x * x for x in e) / len(e)
    if var <= 0:
        return None
    def loglik(a: float, b: float) -> tuple[float, float]:
        omega = var * (1 - a - b)
        s2, ll = var, 0.0
        for x in e:
            ll -= 0.5 * (math.log(s2) + x * x / s2)
            s2 = omega + a * x * x + b * s2
        return ll, s2

    def admissible(a: float, b: float) -> bool:
        return a > 0 and b >= 0 and a + b < 0.995

    # 1) grille grossière ; 2) recherche locale par coordonnées autour du meilleur point.
    best: Optional[tuple[float, float, float, float]] = None
    for a in [0.01, 0.02, 0.04, 0.06, 0.08, 0.10, 0.13, 0.16, 0.20, 0.25]:
        for b in [0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.84, 0.87, 0.9, 0.92, 0.94, 0.96, 0.98]:
            if admissible(a, b):
                ll, s2 = loglik(a, b)
                if best is None or ll > best[0]:
                    best = (ll, a, b, s2)
    for step in (0.01, 0.005, 0.0025):
        improved = True
        while improved:
            improved = False
            _, a0, b0, _ = best
            for da, db in ((step, 0), (-step, 0), (0, step), (0, -step), (step, -step), (-step, step)):
                a, b = a0 + da, b0 + db
                if admissible(a, b):
                    ll, s2 = loglik(a, b)
                    if ll > best[0] + 1e-9:
                        best, improved = (ll, a, b, s2), True
    _, a, b, s2_next = best
    return GarchFit(a, b, var * (1 - a - b), var, s2_next)


def momentum_crash_risk(index_bars: list[Bar]) -> bool:
    """Daniel & Moskowitz (2016) : le momentum subit ses pires krachs lors des rebonds
    de marché qui suivent une baisse prolongée. Signal : indice en baisse sur 12 mois
    mais en hausse sur le dernier mois."""
    c = [b.close for b in index_bars]
    if len(c) < 253:
        return False
    return c[-1] / c[-253] - 1 < 0 and c[-1] / c[-22] - 1 > 0


# --------------------------------------------------------------- notation croisée

def percentile_ranks(values: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    """Rang percentile dans [0, 1] (ex æquo : rang moyen)."""
    valid = sorted((v, t) for t, v in values.items() if v is not None)
    out: dict[str, Optional[float]] = {t: None for t in values}
    n = len(valid)
    if n < 2:
        return out
    i = 0
    while i < n:
        j = i
        while j + 1 < n and valid[j + 1][0] == valid[i][0]:
            j += 1
        pct = ((i + j) / 2) / (n - 1)
        for k in range(i, j + 1):
            out[valid[k][1]] = pct
        i = j + 1
    return out


@dataclass
class FactorReading:
    key: str
    name: str
    horizons: tuple[str, ...]
    value: Optional[float]
    percentile: Optional[float]
    score: float
    weight: float
    reference: str
    note: str


@dataclass
class ResearchView:
    factors: list[FactorReading]
    variance_ratio: float
    vr_z: float
    regime: str
    garch: Optional[GarchFit]
    momentum_crash_risk: bool

    def pillars(self) -> tuple[PillarResult, PillarResult]:
        short, medium = PillarResult("recherche", "court"), PillarResult("recherche", "moyen")
        for f in self.factors:
            if f.value is None or f.weight == 0:
                continue
            comment = f"{f.note} — {f.reference}"
            for horizon, pillar in (("court", short), ("moyen", medium)):
                if horizon in f.horizons:
                    pillar.signals.append(Signal(f.name, f.value, f.score, f.weight, comment))
        return short, medium


def _fmt(key: str, v: float) -> str:
    if key == "tsmom":
        return f"rendement 12 mois = {v:+.2f} x la volatilité annuelle"
    if key == "beta":
        return f"bêta {v:.2f}"
    if key == "high52":
        return f"{v:.0%} du plus haut"
    if key == "abvol":
        return f"volume x{math.exp(v):.1f} vs normale"
    if key in ("attention", "attention_rev"):
        return f"buzz x{math.exp(v):.1f} (comptes établis)"
    if key == "news_drift":
        return ("fort mouvement expliqué par une news : continuation attendue" if v > 0
                else "fort mouvement sans news fiable : retournement attendu")
    return f"{v:+.1%}" if key != "ivol" else f"{v:.0%}"


def _note(spec: FactorSpec, value: float, pct: Optional[float], score: float) -> str:
    where = f"{pct:.0%} de l'univers" if pct is not None else ""
    effect = "favorable" if score > 0.15 else "défavorable" if score < -0.15 else "neutre"
    base = f"{_fmt(spec.key, value)}" + (f", percentile {where}" if where else "")
    return f"{base} → {effect}"


def score_universe(
    inputs: dict[str, TickerInputs],
    index_bars: list[Bar],
    include_info: bool = True,
) -> dict[str, dict[str, FactorReading]]:
    """Calcule et note tous les facteurs pour tous les titres (sans diagnostics)."""
    raw: dict[str, dict[str, Optional[float]]] = {t: price_factors(x.bars, index_bars) for t, x in inputs.items()}
    for t, v in industry_momentum(inputs).items():
        raw[t]["ind_mom"] = v
    if include_info:
        for t, x in inputs.items():
            raw[t]["news_drift"] = news_drift(x.bars, x.news)
            shock = attention_shock(x.posts, x.now)
            raw[t]["attention"] = shock
            raw[t]["attention_rev"] = shock

    specs = [s for s in FACTORS if include_info or s.price_only]
    ranks = {s.key: percentile_ranks({t: raw[t].get(s.key) for t in inputs}) for s in specs if s.cross_sectional}
    out: dict[str, dict[str, FactorReading]] = {t: {} for t in inputs}
    for s in specs:
        for t in inputs:
            v = raw[t].get(s.key)
            pct = ranks[s.key][t] if s.cross_sectional else None
            if v is None:
                score = 0.0
            elif s.cross_sectional:
                score = s.direction * (2 * pct - 1) if pct is not None else 0.0
            elif s.key == "tsmom":
                score = math.tanh(v / 1.0)
            elif s.key in ("attention", "attention_rev"):
                score = s.direction * math.tanh(v / math.log(3))
            else:
                score = s.direction * v
            refs = " ; ".join(short_ref(r) for r in s.refs)
            out[t][s.key] = FactorReading(s.key, s.name, s.horizons, v, pct, clip(score),
                                          s.weight if v is not None else 0.0, refs,
                                          _note(s, v, pct, score) if v is not None else "donnée indisponible")
    return out


def build_research(
    inputs: dict[str, TickerInputs],
    index_bars: list[Bar],
) -> dict[str, ResearchView]:
    """Vue « recherche » complète de chaque titre, avec diagnostics de régime et de volatilité."""
    readings = score_universe(inputs, index_bars)
    crash = momentum_crash_risk(index_bars)
    views: dict[str, ResearchView] = {}
    for t, x in inputs.items():
        vr, z = variance_ratio(x.bars)
        regime = "tendance" if z > 1.96 else "retour à la moyenne" if z < -1.96 else "marche aléatoire"
        factors = list(readings[t].values())
        # Le régime statistique module le poids des familles momentum / retournement.
        tilt = clip(z / 2) * 0.5
        for f in factors:
            if f.key in ("mom_12_1", "tsmom", "high52", "ind_mom"):
                f.weight *= (1 + tilt) * (0.5 if crash else 1.0)
            elif f.key in ("strev", "max"):
                f.weight *= (1 - tilt)
        views[t] = ResearchView(factors, vr, z, regime, fit_garch(x.bars), crash)
    return views
