"""Écran d'asymétrie : où le potentiel décrit (analystes, croissance, valorisation) est-il grand
par rapport au risque de baisse — et quels pièges accompagnent ce profil ?

Un prix unitaire bas n'est PAS une asymétrie : une action à 5 $ n'est pas « moins chère »
qu'une action à 500 $. Seuls comptent la valorisation et le potentiel rapportés au risque.

Composantes du score (rangs dans l'univers analysé, 0 à 1, moyenne des disponibles) :
  - potentiel selon le consensus : objectif moyen des analystes / cours − 1 ;
  - asymétrie des analystes : (objectif haut − cours) / (cours − objectif bas) ;
  - croissance bon marché : croissance du CA / (valeur d'entreprise / CA).
Alertes (non intégrées au score, mais à lire) :
  - profil « loterie » : volatilité > 80 %, asymétrie des rendements > 1 ou hausse
    journalière max du mois > 15 % — historiquement, ces titres sous-performent en moyenne
    (Bali, Cakici & Whitelaw, 2011 ; Boyer, Mitton & Vorkink, 2010) ;
  - trésorerie < 2 ans de consommation : augmentation de capital (dilution) probable ;
  - moins de 5 analystes : consensus peu fiable ; les objectifs de cours sont en moyenne
    trop optimistes (Bradshaw, Brown & Huang, 2013).
Les données fondamentales sont une photographie du jour : cet écran décrit, il n'a pas été
validé par un backtest et ne constitue pas un conseil d'investissement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..models import Bar
from .indicators import mean, stdev


@dataclass
class AsymmetryRow:
    ticker: str
    name: str
    theme: str
    price: float
    pos_52w: Optional[float]          # 0 = plus bas sur 1 an, 1 = plus haut
    drawdown: Optional[float]         # cours / plus haut 1 an − 1
    vol: Optional[float]              # volatilité annualisée (1 an)
    skew: Optional[float]             # asymétrie des rendements journaliers (1 an)
    max_ret: Optional[float]          # plus forte hausse journalière sur 21 séances
    target_upside: Optional[float] = None
    analyst_ratio: Optional[float] = None
    analysts: Optional[int] = None
    revenue_growth: Optional[float] = None
    ev_to_revenue: Optional[float] = None
    growth_per_multiple: Optional[float] = None
    cash_years: Optional[float] = None  # années de trésorerie au rythme de consommation actuel
    short_float: Optional[float] = None
    fetched: Optional[str] = None
    source: Optional[str] = None
    score: Optional[float] = None
    short_label: str = ""
    medium_label: str = ""
    flags: list[str] = field(default_factory=list)


def _skew(xs: list[float]) -> Optional[float]:
    if len(xs) < 30:
        return None
    m, s = mean(xs), stdev(xs)
    return sum((x - m) ** 3 for x in xs) / len(xs) / s ** 3 if s else None


def price_metrics(bars: list[Bar]) -> dict[str, Optional[float]]:
    closes = [b.close for b in bars]
    year = bars[-252:]
    high, low, p = max(b.high for b in year), min(b.low for b in year), closes[-1]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(max(1, len(closes) - 252), len(closes))]
    return {
        "price": p,
        "pos_52w": (p - low) / (high - low) if high > low else None,
        "drawdown": p / high - 1,
        "vol": stdev(rets) * math.sqrt(252) if len(rets) > 20 else None,
        "skew": _skew(rets),
        "max_ret": max(math.exp(r) - 1 for r in rets[-21:]) if len(rets) >= 21 else None,
    }


def build_row(ticker: str, name: str, theme: str, bars: list[Bar], fund: Optional[dict]) -> AsymmetryRow:
    m = price_metrics(bars)
    row = AsymmetryRow(ticker, name, theme, m["price"], m["pos_52w"], m["drawdown"], m["vol"], m["skew"], m["max_ret"])
    f = fund or {}
    p = row.price
    if f.get("target_mean"):
        row.target_upside = f["target_mean"] / p - 1
    th, tl = f.get("target_high"), f.get("target_low")
    if th and tl:
        down = p - tl
        row.analyst_ratio = (th - p) / down if down > 0 else math.inf
    row.analysts = int(f["analysts"]) if f.get("analysts") else None
    row.revenue_growth, row.ev_to_revenue = f.get("revenue_growth"), f.get("ev_to_revenue")
    if row.revenue_growth is not None and row.ev_to_revenue and row.ev_to_revenue > 0:
        row.growth_per_multiple = row.revenue_growth / row.ev_to_revenue
    fcf, cash = f.get("free_cash_flow"), f.get("cash")
    if fcf is not None and fcf < 0 and cash is not None:
        row.cash_years = cash / -fcf
    row.short_float, row.fetched, row.source = f.get("short_float"), f.get("fetched"), f.get("source")

    if (row.vol or 0) > 0.8 or (row.skew or 0) > 1 or (row.max_ret or 0) > 0.15:
        row.flags.append("profil loterie")
    if row.cash_years is not None and row.cash_years < 2:
        row.flags.append(f"trésorerie {row.cash_years:.1f} an(s) : dilution probable")
    if row.analysts is not None and row.analysts < 5:
        row.flags.append("peu d'analystes")
    if row.analyst_ratio == math.inf:
        row.flags.append("cours sous l'objectif le plus bas")
    if (row.short_float or 0) > 0.15:
        row.flags.append(f"vente à découvert {row.short_float:.0%}")
    if not fund:
        row.flags.append("fondamentaux absents")
    return row


def _ranks(values: dict[str, float]) -> dict[str, float]:
    order = sorted(values, key=lambda k: values[k])
    n = len(order)
    return {k: (i / (n - 1) if n > 1 else 0.5) for i, k in enumerate(order)}


def score_rows(rows: list[AsymmetryRow]) -> list[AsymmetryRow]:
    """Score = moyenne des rangs disponibles (potentiel, asymétrie analystes, croissance / multiple)."""
    comps = []
    for attr in ("target_upside", "analyst_ratio", "growth_per_multiple"):
        vals = {r.ticker: min(getattr(r, attr), 50.0) for r in rows if getattr(r, attr) is not None}
        comps.append(_ranks(vals) if len(vals) >= 3 else {})
    for r in rows:
        got = [c[r.ticker] for c in comps if r.ticker in c]
        r.score = mean(got) if len(got) >= 2 else None
    return sorted(rows, key=lambda r: (r.score is None, -(r.score or 0)))


def _pct(x: Optional[float], signed: bool = True) -> str:
    return "—" if x is None else (f"{x:+.0%}" if signed else f"{x:.0%}")


def render_asymmetry(rows: list[AsymmetryRow]) -> str:
    fetched = sorted({r.fetched for r in rows if r.fetched})
    sources = sorted({r.source for r in rows if r.source})
    out = ["ÉCRAN D'ASYMÉTRIE — FOCUS IA" + (f" (fondamentaux du {fetched[-1]}" + (f", {', '.join(sources)}" if sources else "")
                                              + ")" if fetched else ""),
           "Descriptif, non validé par backtest : ce n'est pas un conseil d'investissement.", "",
           f"  {'Titre':6} {'Thème':24} {'Cours':>8} {'52 sem.':>7} {'Vol.':>5} {'Objectif':>8} "
           f"{'Haut/bas':>8} {'Croiss.':>7} {'VE/CA':>6} {'Score':>5}  {'Avis CT / MT':34} Alertes"]
    for r in rows:
        ratio = "—" if r.analyst_ratio is None else ("∞" if r.analyst_ratio == math.inf else f"{r.analyst_ratio:.1f}x")
        out.append(
            f"  {r.ticker:6} {r.theme[:24]:24} {r.price:8.2f} {_pct(r.pos_52w, False):>7} {_pct(r.vol, False):>5} "
            f"{_pct(r.target_upside):>8} {ratio:>8} {_pct(r.revenue_growth):>7} "
            f"{'—' if r.ev_to_revenue is None else f'{r.ev_to_revenue:.1f}':>6} "
            f"{'—' if r.score is None else f'{r.score:.2f}':>5}  {(r.short_label + ' / ' + r.medium_label)[:34]:34} "
            f"{', '.join(r.flags)}")
    lottery = sum("profil loterie" in r.flags for r in rows)
    out += ["",
            "  52 sem. : position du cours entre le plus bas (0 %) et le plus haut (100 %) d'un an.",
            "  Objectif : objectif moyen des analystes vs cours. Haut/bas : gain vers l'objectif le plus haut",
            "  rapporté à la perte vers l'objectif le plus bas. Croiss. : croissance annuelle du CA (dernier",
            "  exercice avec Nasdaq, dernier trimestre sur un an avec Yahoo).",
            "  VE/CA : valeur d'entreprise / chiffre d'affaires. Score : rang moyen dans l'univers (1 = profil",
            "  le plus asymétrique selon ces critères), sans prise en compte des alertes.",
            "",
            "  ⚠ Un cours unitaire bas ne signifie pas « pas cher » : seule la valorisation compte.",
            f"  ⚠ {lottery} titre(s) au profil « loterie » : en moyenne, ces titres sous-performent ensuite",
            "    (Bali, Cakici & Whitelaw, 2011). Leur potentiel apparent se paie par un risque de perte élevé.",
            "  ⚠ Les objectifs des analystes sont en moyenne trop optimistes (Bradshaw, Brown & Huang, 2013)."]
    return "\n".join(out)


def html_asymmetry(rows: list[AsymmetryRow]) -> str:
    """Écran d'asymétrie au format HTML (application, rapports)."""
    from html import escape

    fetched = sorted({r.fetched for r in rows if r.fetched})
    sources = sorted({r.source for r in rows if r.source})
    lottery = sum("profil loterie" in r.flags for r in rows)

    def cell(v, cls=""):
        return f'<td class="num {cls}">{v}</td>'

    def signed(x):
        return "—" if x is None else f'<span class="{"pos" if x >= 0 else "neg"}">{x:+.0%}</span>'

    body = []
    for r in rows:
        ratio = "—" if r.analyst_ratio is None else ("∞" if r.analyst_ratio == math.inf else f"{r.analyst_ratio:.1f}x")
        flags = " ".join(f'<span class="badge neu">{escape(f)}</span>' for f in r.flags)
        body.append(
            f'<tr><td><a href="#{escape(r.ticker)}" data-ticker="{escape(r.ticker)}"><strong>{escape(r.ticker)}</strong></a>'
            f'<div class="muted small">{escape(r.theme)}</div></td>'
            + cell(f"{r.price:,.2f}") + cell(_pct(r.pos_52w, False)) + cell(_pct(r.vol, False))
            + cell(signed(r.target_upside)) + cell(ratio) + cell(signed(r.revenue_growth))
            + cell("—" if r.ev_to_revenue is None else f"{r.ev_to_revenue:.1f}")
            + cell("—" if r.score is None else f"<strong>{r.score:.2f}</strong>")
            + f'<td class="small">{escape(r.short_label)} / {escape(r.medium_label)}</td><td class="small">{flags}</td></tr>')
    head = ("<tr><th>Titre</th><th class='num'>Cours</th><th class='num' title='Position entre le plus bas (0 %) et le plus "
            "haut (100 %) d&#39;un an'>52 sem.</th><th class='num'>Vol.</th><th class='num' title='Objectif moyen des "
            "analystes vs cours'>Objectif</th><th class='num' title='Gain vers l&#39;objectif le plus haut / perte vers le "
            "plus bas'>Haut/bas</th><th class='num'>Croiss. CA</th><th class='num' title='Valeur d&#39;entreprise / "
            "chiffre d&#39;affaires'>VE/CA</th><th class='num'>Score</th><th>Avis CT / MT</th><th>Alertes</th></tr>")
    note = (f"Fondamentaux du {fetched[-1]} ({', '.join(sources)})" if fetched else "Fondamentaux absents") + \
        " · cours de la dernière séance analysée."
    return f"""
<h2>Écran d'asymétrie — focus IA</h2>
<p class="muted small">{escape(note)} Descriptif, non validé par backtest : ce n'est pas un conseil d'investissement.</p>
<section class="card"><div class="scroll"><table class="signals">{head}{"".join(body)}</table></div></section>
<section class="card small">
  <p><strong>Score</strong> : rang moyen dans l'univers (1 = profil le plus asymétrique) selon le potentiel du consensus,
  l'écart entre objectifs haut et bas et la croissance rapportée à la valorisation, sans tenir compte des alertes.</p>
  <p>⚠ Un cours unitaire bas ne signifie pas « pas cher » : seule la valorisation compte.</p>
  <p>⚠ {lottery} titre(s) au profil « loterie » : en moyenne, ces titres sous-performent ensuite
  (Bali, Cakici &amp; Whitelaw, 2011) — leur potentiel apparent se paie par un risque de perte élevé.</p>
  <p>⚠ Les objectifs des analystes sont en moyenne trop optimistes (Bradshaw, Brown &amp; Huang, 2013) ;
  une trésorerie courte annonce souvent une augmentation de capital (dilution).</p>
</section>"""
