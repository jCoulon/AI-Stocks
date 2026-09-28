"""Mise en forme des résultats : terminal, JSON et page HTML autonome."""

from __future__ import annotations

import html
import json
import textwrap
from dataclasses import asdict
from datetime import date, datetime

from .models import MarketReport, Outlook, TickerAnalysis

DISCLAIMER_BASE = (
    "Outil d'analyse de données — PAS un conseil en investissement. Les avis sont des "
    "synthèses statistiques d'indicateurs, sans garantie."
)
DISCLAIMER = DISCLAIMER_BASE + " Données de démonstration SIMULÉES."
DISCLAIMER_REAL = DISCLAIMER_BASE + " Données de marché réelles, qui peuvent comporter des erreurs ou des retards."


def disclaimer(report: MarketReport) -> str:
    return DISCLAIMER if report.simulated else DISCLAIMER_REAL

JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def _jour(d: date) -> str:
    return f"{JOURS[d.weekday()]} {d.strftime('%d/%m')}"


SEVERITY_ICON = {"info": "ℹ", "warning": "⚠", "critical": "✖"}
SEVERITY_LABEL = {"info": "Info", "warning": "Attention", "critical": "Critique"}

MACRO_LABELS = [
    ("fed_funds", "Taux Fed", "{:.2f}%"),
    ("us10y", "Taux 10 ans US", "{:.2f}%"),
    ("us10y_chg_5d", "Taux 10 ans · var. 5j", "{:+.2f} pt"),
    ("curve_10y_2y", "Courbe 10a-2a", "{:+.2f} pt"),
    ("cpi_yoy", "Inflation (CPI a/a)", "{:.1f}%"),
    ("unemployment", "Chômage", "{:.1f}%"),
    ("ism_pmi", "ISM manufacturier", "{:.1f}"),
    ("vix", "VIX", "{:.1f}"),
    ("vix_chg_5d", "VIX · var. 5j", "{:+.1f}"),
    ("wti", "Pétrole WTI", "{:.2f} $"),
    ("wti_chg_5d", "WTI · var. 5j", "{:+.2f} $"),
    ("put_call", "Put/Call ratio", "{:.2f}"),
    ("aaii_spread", "AAII bull-bear", "{:+.1f} pt"),
]


# ---------------------------------------------------------------- terminal

class _Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def score(self, text: str, score: float) -> str:
        return self(text, "32" if score >= 0.12 else "31" if score <= -0.12 else "33")


def _outlook_cell(o: Outlook) -> str:
    return f"{o.label:<16} {o.score:+.2f} ({o.confidence:.0%})"


def render_text(report: MarketReport, color: bool = False, detail: list[str] | None = None) -> str:
    st = _Style(color)
    out: list[str] = []
    line = "─" * 104
    out.append(st(f"ANALYSE S&P 500 — semaine au {report.as_of.strftime('%d/%m/%Y')}", "1"))
    out.append(st(disclaimer(report), "2"))
    out.append(line)

    idx = report.index
    out.append(st("MARCHÉ", "1"))
    out.append(f"  S&P 500 : {idx.last_close:,.2f}  ({idx.week_return:+.2%} sur la semaine)")
    out.append("  Séances : " + "  ".join(f"{_jour(d)} {c:,.0f}" for d, c in idx.week_closes[1:]))
    out.append("  Court terme (1-2 sem.) : " + st.score(_outlook_cell(idx.short), idx.short.score))
    out.append("  Moyen terme (1-3 mois) : " + st.score(_outlook_cell(idx.medium), idx.medium.score))
    b = report.breadth
    out.append(f"  Largeur : {b['advancers_week']:.0%} des titres en hausse sur la semaine, "
               f"{b['above_sma50']:.0%} au-dessus de la MM50, {b['above_sma200']:.0%} au-dessus de la MM200")
    out.append("")
    out.append(st("MACRO & SENTIMENT DE MARCHÉ", "1"))
    m = report.macro_summary
    rows = [f"{label:<22} {fmt.format(m[key]):>10}" for key, label, fmt in MACRO_LABELS if key in m]
    for i in range(0, len(rows), 3):
        out.append("  " + "   ".join(rows[i:i + 3]))
    if report.market_news:
        out.append("")
        out.append(st("NEWS DE MARCHÉ", "1"))
        for n in report.market_news:
            out.append(f"  {_jour(n.published.date())}  [{n.source}] {n.headline}")
    out.append(line)

    out.append(st("AVIS PAR ACTION", "1") + "   (score de -1 à +1, confiance entre parenthèses)")
    out.append(f"  {'Titre':<6} {'Cours':>9} {'Sem.':>7}  {'Court terme':<30} {'Moyen terme':<30} {'Fiabil.':>7}  Alertes")
    for t in sorted(report.tickers, key=lambda x: -x.short.score):
        alerts = [f.code for f in t.flags if f.severity != "info"]
        out.append(
            f"  {t.security.ticker:<6} {t.last_close:>9.2f} {t.week_return:>+7.1%}  "
            + st.score(f"{_outlook_cell(t.short):<30}", t.short.score) + " "
            + st.score(f"{_outlook_cell(t.medium):<30}", t.medium.score)
            + f" {t.data_quality * t.coherence:>7.0%}  "
            + (st(", ".join(alerts), "35") if alerts else "")
        )
    out.append(line)

    flagged = [t for t in report.tickers if any(f.severity != "info" for f in t.flags)]
    if flagged:
        out.append(st("CONTRÔLE DE COHÉRENCE DES DONNÉES", "1"))
        for t in flagged:
            for f in t.flags:
                if f.severity != "info":
                    out.append(f"  {SEVERITY_ICON[f.severity]} {t.security.ticker:<5} {f.message}")
        out.append(line)

    if report.narrative:
        out.append(st("SYNTHÈSE DE L'AGENT RÉDACTEUR (Claude)", "1"))
        out.extend("  " + l for l in report.narrative.splitlines())
        out.append(line)

    for ticker in detail or []:
        t = next((x for x in report.tickers if x.security.ticker == ticker.upper()), None)
        if t:
            out.extend(render_stock(t, st))
            out.append(line)
    return "\n".join(out)


def summarize_trace(trace: list[dict]) -> list[dict]:
    """Agrège le journal de l'orchestrateur par agent."""
    by_agent: dict[str, dict] = {}
    for r in trace:
        a = by_agent.setdefault(r["agent"], {"agent": r["agent"], "done": 0, "failed": 0, "skipped": 0,
                                             "ms": 0.0, "errors": []})
        a[r["status"]] = a.get(r["status"], 0) + 1
        a["ms"] += r["duration_ms"]
        if r["error"]:
            a["errors"].append(f"{r['task_id']} : {r['error']}")
    return list(by_agent.values())


def render_trace(report: MarketReport, verbose: bool = False) -> str:
    rows = summarize_trace(report.trace)
    out = ["JOURNAL DE L'ORCHESTRATEUR",
           f"  {'Agent':<18} {'OK':>5} {'Échec':>6} {'Annulé':>7} {'Temps cumulé':>13}"]
    for a in rows:
        out.append(f"  {a['agent']:<18} {a['done']:>5} {a['failed']:>6} {a['skipped']:>7} {a['ms']:>10.0f} ms")
        for e in a["errors"][: None if verbose else 3]:
            out.append(f"      ↳ {e}")
    out.append(f"  {len(report.trace)} tâches au total")
    return "\n".join(out)


def _pct(v: float) -> str:
    return f"{v:+.1%}"


def render_stock(t: TickerAnalysis, st: _Style | None = None) -> list[str]:
    """Fiche complète d'une action : synthèse de l'analyste-titre puis détail des signaux."""
    st = st or _Style(False)
    sr = t.stock
    if sr is None:
        return render_detail(t, st)
    s = t.security
    out = [st(f"FICHE {s.ticker} — {s.name} ({s.sector})", "1"),
           f"  Cours {t.last_close:,.2f}  |  semaine {t.week_return:+.2%}  |  "
           f"qualité des données {t.data_quality:.0%}  |  cohérence des sources {t.coherence:.0%}", ""]
    out += ["  " + line for line in textwrap.wrap(sr.thesis, 100)]
    out.append("")
    out.append("  " + st.score(f"Court terme : {_outlook_cell(t.short)}", t.short.score)
               + f"   fourchette probable (2 chances sur 3) {t.short.low:,.2f} – {t.short.high:,.2f}")
    out.append("  " + st.score(f"Moyen terme : {_outlook_cell(t.medium)}", t.medium.score)
               + f"   fourchette probable (2 chances sur 3) {t.medium.low:,.2f} – {t.medium.high:,.2f}")

    out += ["", st("  Points forts", "1")] + [f"    + {x}" for x in sr.strengths or ["aucun signal nettement positif"]]
    out += [st("  Risques / points de vigilance", "1")] + [f"    - {x}" for x in sr.risks or ["aucun signal nettement négatif"]]

    out += ["", st("  Performance", "1") + f"      {'titre':>8} {'vs S&P':>8}"]
    for label, v in sr.performance.items():
        rel = sr.relative.get(label)
        out.append(f"    {label:<14} {_pct(v):>8} {_pct(rel) if rel is not None else '':>8}")

    out += ["", st("  Risque", "1")]
    for label, v in sr.risk_metrics.items():
        val = f"{v:.2f}" if label.startswith("Bêta") else f"{v:.1%}"
        out.append(f"    {label:<24} {val:>8}")

    out += ["", st("  Niveaux clés", "1")]
    for lv in sr.levels:
        out.append(f"    {lv.label:<20} {lv.price:>10,.2f}  {lv.price / t.last_close - 1:+7.1%}")
    out.insert(len(out) - sum(1 for lv in sr.levels if lv.price < t.last_close),
               f"    {'— cours actuel —':<20} {t.last_close:>10,.2f}")

    out += ["", st("  Catalyseurs (7 derniers jours)", "1")]
    if not sr.catalysts:
        out.append("    aucune news sur la période")
    for c in sr.catalysts:
        reaction = f"réaction {c.reaction:+.1%}" if c.reaction is not None else "réaction n/d"
        status = "" if c.retained else "  [écartée : source non confirmée]"
        out.append(f"    {_jour(c.published.date())}  [{c.source}] {c.headline}")
        out.append(f"               ton {c.tone:+.2f}, {reaction}{status}")

    out += ["", st("  Réseaux sociaux", "1")]
    so = sr.social
    out.append(f"    {so['Messages (3 j)']:.0f} messages sur 3 jours, ton {so['Ton social (3 j)']:+.2f}, "
               f"buzz x{so['Buzz vs normale']:.1f}, comptes récents {so['Comptes < 30 jours']:.0%}, "
               f"score de manipulation {so['Score de manipulation']:.2f}")

    out += render_research(t, st)

    rank, total = sr.sector_rank
    out += ["", st(f"  Pairs du secteur (rang court terme : {rank}/{total})", "1")]
    for p in sr.peers:
        out.append(f"    {p.ticker:<6} semaine {_pct(p.week_return):>7}   CT {p.short_score:+.2f}   MT {p.medium_score:+.2f}")
    out += ["", st("  Détail des signaux", "1")]
    out += render_detail(t, st)[2:]
    return out


def _research_diagnostics(rv) -> list[str]:
    lines = [f"Régime statistique : {rv.regime} (ratio de variance {rv.variance_ratio:.2f}, z = {rv.vr_z:+.2f} ; "
             "Lo & MacKinlay, 1988)"]
    if rv.garch:
        g = rv.garch
        lines.append(f"Volatilité prévue (GARCH(1,1), Bollerslev, 1986) : ±{g.horizon_vol(5):.1%} sur 5 séances, "
                     f"±{g.horizon_vol(63):.1%} sur 3 mois (persistance {g.persistence:.2f})")
    if rv.momentum_crash_risk:
        lines.append("Risque de krach du momentum : marché en rebond après une baisse sur 12 mois — "
                     "poids du momentum divisé par deux (Daniel & Moskowitz, 2016)")
    return lines


def render_research(t: TickerAnalysis, st: _Style | None = None) -> list[str]:
    st = st or _Style(False)
    rv = t.research
    if rv is None:
        return []
    out = ["", st("  Facteurs de recherche (littérature académique)", "1")]
    for f in rv.factors:
        if f.value is None:
            continue
        horizon = "/".join("CT" if h == "court" else "MT" for h in f.horizons)
        out.append(f"    {f.name:<46} {horizon:<5} " + st.score(f"{f.score:+.2f}", f.score) + f"  {f.note}")
        out.append(f"    {'':<46} {'':<5}        {f.reference}")
    out += ["    " + line for line in _research_diagnostics(rv)]
    return out


def render_stock_sheets(report: MarketReport, tickers: list[str], color: bool = False) -> str:
    st = _Style(color)
    line = "─" * 104
    out = [st(f"ANALYSE PAR ACTION — séance du {report.as_of.strftime('%d/%m/%Y')}", "1"), st(disclaimer(report), "2"), line]
    idx = report.index
    out.append(f"Contexte : S&P 500 {idx.last_close:,.2f} ({idx.week_return:+.2%} sur la semaine) — "
               f"court terme {idx.short.label.lower()}, moyen terme {idx.medium.label.lower()}")
    out.append(line)
    by = {t.security.ticker: t for t in report.tickers}
    for ticker in tickers:
        t = by.get(ticker.upper())
        if t:
            out += render_stock(t, st)
            out.append(line)
    if report.narrative:
        out.append(st("SYNTHÈSE DE L'AGENT RÉDACTEUR (Claude)", "1"))
        out.extend("  " + l for l in report.narrative.splitlines())
    return "\n".join(out)


def render_detail(t: TickerAnalysis, st: _Style | None = None) -> list[str]:
    st = st or _Style(False)
    s = t.security
    out = [st(f"{s.ticker} — {s.name} ({s.sector})", "1"),
           f"  Cours {t.last_close:.2f}  |  semaine {t.week_return:+.2%}  |  "
           f"qualité des données {t.data_quality:.0%}  |  cohérence des sources {t.coherence:.0%}"]
    for o, title in ((t.short, "Court terme (1-2 semaines)"), (t.medium, "Moyen terme (1-3 mois)")):
        out.append("")
        out.append("  " + st.score(f"{title} : {o.label}  score {o.score:+.2f}  confiance {o.confidence:.0%}", o.score))
        out.append(f"    Fourchette probable (≈ 2 chances sur 3, volatilité GARCH) : {o.low:.2f} — {o.high:.2f}")
        out.append("    Contributions : " + ", ".join(f"{k} {v:+.2f}" for k, v in o.contributions.items()))
        horizon = "court" if o is t.short else "moyen"
        for pillar in ("technique", "sentiment", "macro", "recherche"):
            p = t.pillars.get(f"{pillar}_{horizon}")
            if not p:
                continue
            out.append(f"    ▸ {pillar.capitalize()} ({p.score:+.2f})")
            for sig in p.signals:
                val = "" if sig.value is None else f"{sig.value:,.2f}"
                out.append(f"        {sig.name:<28} {val:>10}  " + st.score(f"{sig.score:+.2f}", sig.score)
                           + f"  {sig.comment}")
    if t.flags:
        out.append("")
        out.append("  Contrôles de cohérence :")
        for f in t.flags:
            out.append(f"    {SEVERITY_ICON[f.severity]} [{SEVERITY_LABEL[f.severity]}] {f.message}")
    return out


# -------------------------------------------------------------------- JSON

def _default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def to_json(report: MarketReport) -> str:
    data = asdict(report)
    data["disclaimer"] = disclaimer(report)
    # allow_nan=False : garantit un JSON standard (NaN/Infinity y sont interdits).
    return json.dumps(data, default=_default, ensure_ascii=False, indent=2, allow_nan=False)


# -------------------------------------------------------------------- HTML

def _sparkline(points: list[tuple[date, float]], width: int = 120, height: int = 34) -> str:
    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pad = 4
    xs = [pad + i * (width - 2 * pad) / max(1, len(values) - 1) for i in range(len(values))]
    ys = [height - pad - (v - lo) / span * (height - 2 * pad) for v in values]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    hits = "".join(
        f'<g class="pt"><circle cx="{x:.1f}" cy="{y:.1f}" r="9" class="hit"/>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="dot"/>'
        f'<title>{_jour(d)} : {v:,.2f}</title></g>'
        for (d, v), x, y in zip(points, xs, ys)
    )
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" aria-label="Clôtures de la semaine">'
            f'<path d="{path}" class="line"/>{hits}</svg>')


MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
CHART_SERIES = [("Cours", "series-1", ""), ("Moy. 50 j", "series-2", ""), ("Moy. 200 j", "series-3", "4 3")]


def _dash(dash: str) -> str:
    return f' stroke-dasharray="{dash}"' if dash else ""


def _price_chart(t: TickerAnalysis) -> str:
    """Graphique 6 mois : cours, moyennes 50/200 j et niveaux clés proches, avec info-bulle."""
    hist = t.stock.history
    w, h, left, right, top, bottom = 640, 260, 8, 78, 12, 24
    values = [v for row in hist for v in row[1:] if v is not None]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    n = len(hist)

    def x(i: int) -> float:
        return left + i * (w - left - right) / max(1, n - 1)

    def y(v: float) -> float:
        return top + (hi - v) / (hi - lo) * (h - top - bottom)

    parts = []
    # Grille horizontale et graduations (encre discrète).
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        parts.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text class="tick" x="{w - right + 6}" y="{y(v) + 4:.1f}">{v:,.0f}</text>')
    prev_month = None
    for i, row in enumerate(hist):
        if row[0].month != prev_month:
            if prev_month is not None:
                parts.append(f'<text class="tick" x="{x(i):.1f}" y="{h - 6}" text-anchor="middle">'
                             f'{MOIS[row[0].month - 1]}</text>')
            prev_month = row[0].month
    # Supports / résistances visibles dans la fenêtre.
    last_label_y = None
    for lv in t.stock.levels:
        if lv.kind in ("support", "resistance") and lo < lv.price < hi:
            ly = y(lv.price)
            parts.append(f'<line class="level {lv.kind}" x1="{left}" x2="{w - right}" y1="{ly:.1f}" y2="{ly:.1f}"/>')
            # Libellé omis s'il chevaucherait le précédent (le niveau reste listé dans le tableau).
            if last_label_y is None or abs(ly - last_label_y) >= 14:
                parts.append(f'<text class="level-label" x="{left + 4}" y="{ly - 4:.1f}">'
                             f'{html.escape(lv.label)} {lv.price:,.2f}</text>')
                last_label_y = ly
    # Séries : un tracé par série, étiquette directe en bout de courbe.
    ends = []
    for col, (label, var, dash) in enumerate(CHART_SERIES, start=1):
        pts = [(x(i), y(row[col])) for i, row in enumerate(hist) if row[col] is not None]
        if not pts:
            continue
        d = " ".join(f"{'M' if j == 0 else 'L'}{px:.1f},{py:.1f}" for j, (px, py) in enumerate(pts))
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(f'<path class="series" d="{d}" style="stroke: var(--{var})"{dash_attr}/>')
        ends.append([pts[-1][1], label, var])
    # Étiquettes directes : on écarte celles qui se chevauchent.
    ends.sort()
    for j in range(1, len(ends)):
        ends[j][0] = max(ends[j][0], ends[j - 1][0] + 12)
    for yy, label, var in ends:
        parts.append(f'<circle class="end-dot" cx="{w - right + 2}" cy="{yy:.1f}" r="3" style="fill: var(--{var})"/>')
    data = json.dumps([[r[0].strftime("%d/%m/%Y"), r[1], r[2], r[3]] for r in hist])
    legend = "".join(
        f'<span class="key"><svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" '
        f'style="stroke: var(--{var})" stroke-width="2"{_dash(dash)}/>'
        f'</svg>{label}</span>' for label, var, dash in CHART_SERIES
    )
    return (
        f'<div class="chart-wrap"><div class="legend">{legend}</div>'
        f'<svg class="pricechart" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="Cours de {html.escape(t.security.name)} sur 6 mois avec moyennes mobiles" '
        f'data-points=\'{html.escape(data)}\' data-left="{left}" data-right="{w - right}" data-lo="{lo}" '
        f'data-hi="{hi}" data-top="{top}" data-bottom="{h - bottom}">'
        + "".join(parts)
        + f'<line class="xhair" y1="{top}" y2="{h - bottom}" x1="-10" x2="-10"/>'
        + "".join(f'<circle class="hover-dot" r="4" cx="-10" cy="-10" style="fill: var(--{var})"/>'
                  for _, var, _ in CHART_SERIES)
        + f'<rect class="hit" x="{left}" y="{top}" width="{w - left - right}" height="{h - top - bottom}"/>'
        + '</svg><div class="tooltip" hidden></div></div>'
    )


def _kv_rows(items) -> str:
    return "".join(f'<div class="kv"><span>{html.escape(k)}</span><strong>{v}</strong></div>' for k, v in items)


def _stock_html(t: TickerAnalysis) -> str:
    sr = t.stock
    if sr is None:
        return ""
    perf_rows = "".join(
        f'<tr><td>{html.escape(k)}</td><td class="num {"pos" if v > 0 else "neg"}">{v:+.1%}</td>'
        f'<td class="num">{(f"{sr.relative[k]:+.1%}" if k in sr.relative else "")}</td></tr>'
        for k, v in sr.performance.items()
    )
    risk = _kv_rows((k, f"{v:.2f}" if k.startswith("Bêta") else f"{v:.1%}") for k, v in sr.risk_metrics.items())
    levels = "".join(
        f'<tr class="lv-{lv.kind}"><td>{html.escape(lv.label)}</td><td class="num">{lv.price:,.2f}</td>'
        f'<td class="num muted">{lv.price / t.last_close - 1:+.1%}</td></tr>' for lv in sr.levels
    )
    excluded = ' · <span class="flag warning">⚠ écartée : source non confirmée</span>'
    cats = "".join(
        f'<li><time>{_jour(c.published.date())}</time> <b>{html.escape(c.source)}</b> {html.escape(c.headline)}'
        f'<div class="small muted">ton {c.tone:+.2f} · réaction '
        f'{(f"{c.reaction:+.1%}" if c.reaction is not None else "n/d")}'
        f'{"" if c.retained else excluded}</div></li>'
        for c in sr.catalysts
    ) or '<li class="muted">Aucune news sur la période</li>'
    so = sr.social
    social = _kv_rows([
        ("Messages (3 j)", f"{so['Messages (3 j)']:.0f}"),
        ("Ton", f"{so['Ton social (3 j)']:+.2f}"),
        ("Buzz vs normale", f"x{so['Buzz vs normale']:.1f}"),
        ("Comptes < 30 jours", f"{so['Comptes < 30 jours']:.0%}"),
        ("Score de manipulation", f"{so['Score de manipulation']:.2f}"),
    ])
    peers = "".join(
        f'<tr><td><a href="#{p.ticker}">{p.ticker}</a></td><td class="num">{p.week_return:+.1%}</td>'
        f'<td class="num">{p.short_score:+.2f}</td><td class="num">{p.medium_score:+.2f}</td></tr>' for p in sr.peers
    )
    li = lambda items, empty: "".join(f"<li>{html.escape(x)}</li>" for x in items) or f'<li class="muted">{empty}</li>'
    rank, total = sr.sector_rank
    return f"""
<p class="thesis">{html.escape(sr.thesis)}</p>
{_price_chart(t)}
<div class="grid2">
  <div><h4>▲ Points forts</h4><ul class="pros">{li(sr.strengths, "Aucun signal nettement positif")}</ul></div>
  <div><h4>▼ Risques et points de vigilance</h4><ul class="cons">{li(sr.risks, "Aucun signal nettement négatif")}</ul></div>
</div>
<div class="grid3">
  <div><h4>Performance</h4><table class="signals"><tr><th></th><th class="num">Titre</th><th class="num">vs S&amp;P</th></tr>{perf_rows}</table></div>
  <div><h4>Niveaux clés (cours {t.last_close:,.2f})</h4><table class="signals">{levels}</table></div>
  <div><h4>Risque</h4>{risk}<h4>Réseaux sociaux</h4>{social}</div>
</div>
<div class="grid2">
  <div><h4>Catalyseurs (7 derniers jours)</h4><ul class="news">{cats}</ul></div>
  <div><h4>Pairs du secteur — rang {rank}/{total} à court terme</h4><table class="signals">
    <tr><th>Titre</th><th class="num">Semaine</th><th class="num">CT</th><th class="num">MT</th></tr>{peers}</table></div>
</div>
{_research_html(t)}
<h4>Détail des signaux</h4>"""


def _research_html(t: TickerAnalysis) -> str:
    rv = t.research
    if rv is None:
        return ""
    rows = []
    for f in rv.factors:
        if f.value is None:
            continue
        horizon = " / ".join("CT" if h == "court" else "MT" for h in f.horizons)
        cls = "pos" if f.score >= 0.12 else "neg" if f.score <= -0.12 else "neu"
        pct = f"{f.percentile:.0%}" if f.percentile is not None else "—"
        rows.append(f'<tr><td>{html.escape(f.name)}</td><td class="muted">{horizon}</td>'
                    f'<td>{html.escape(f.note.split(" → ")[0].split(", percentile")[0])}</td>'
                    f'<td class="num">{pct}</td><td class="num {cls}">{f.score:+.2f}</td>'
                    f'<td class="muted small">{html.escape(f.reference)}</td></tr>')
    diag = "".join(f"<li>{html.escape(line)}</li>" for line in _research_diagnostics(rv))
    return (f'<h4>Facteurs de recherche (littérature académique)</h4><div class="scroll"><table class="signals">'
            f'<tr><th>Facteur</th><th>Horizon</th><th>Mesure</th><th class="num">Percentile</th>'
            f'<th class="num">Score</th><th>Source</th></tr>{"".join(rows)}</table></div>'
            f'<ul class="news">{diag}</ul>')


CHART_JS = """
// Active les graphiques de cours (info-bulle, taille des textes) présents sous `root`.
window.initCharts = function (root) {
(root || document).querySelectorAll('svg.pricechart:not([data-ready])').forEach(function (svg) {
  svg.dataset.ready = '1';
  var pts = JSON.parse(svg.dataset.points), left = +svg.dataset.left, right = +svg.dataset.right;
  var lo = +svg.dataset.lo, hi = +svg.dataset.hi, top = +svg.dataset.top, bottom = +svg.dataset.bottom;
  var xhair = svg.querySelector('.xhair'), dots = svg.querySelectorAll('.hover-dot');
  var tip = svg.parentNode.querySelector('.tooltip');
  var names = ['Cours', 'Moy. 50 j', 'Moy. 200 j'];
  // Garde textes et points à taille constante à l'écran, quelle que soit la largeur du graphique.
  new ResizeObserver(function () {
    var wpx = svg.getBoundingClientRect().width;
    if (wpx) svg.style.setProperty('--k', svg.viewBox.baseVal.width / wpx);
  }).observe(svg);
  function y(v) { return top + (hi - v) / (hi - lo) * (bottom - top); }
  function fmt(v) { return v == null ? '–' : v.toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function move(ev) {
    var box = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
    var sx = (ev.clientX - box.left) * vb.width / box.width;
    var i = Math.max(0, Math.min(pts.length - 1, Math.round((sx - left) / (right - left) * (pts.length - 1))));
    var p = pts[i], px = left + i * (right - left) / (pts.length - 1);
    xhair.setAttribute('x1', px); xhair.setAttribute('x2', px);
    dots.forEach(function (d, k) {
      var v = p[k + 1];
      d.setAttribute('cx', v == null ? -10 : px); d.setAttribute('cy', v == null ? -10 : y(v));
    });
    tip.innerHTML = '<b>' + p[0] + '</b>' + names.map(function (n, k) {
      return '<div><span class="sw s' + (k + 1) + '"></span>' + n + ' <b>' + fmt(p[k + 1]) + '</b></div>';
    }).join('');
    tip.hidden = false;
    var tx = px * box.width / vb.width;
    tip.style.left = Math.min(tx + 12, box.width - tip.offsetWidth - 4) + 'px';
    tip.style.top = '28px';
  }
  var hit = svg.querySelector('.hit');
  hit.addEventListener('pointermove', move);
  hit.addEventListener('pointerleave', function () {
    tip.hidden = true; xhair.setAttribute('x1', -10); xhair.setAttribute('x2', -10);
    dots.forEach(function (d) { d.setAttribute('cx', -10); });
  });
});
};
"""
CHART_SCRIPT = f"<script>{CHART_JS}\ninitCharts(document);</script>"


def _score_badge(o: Outlook) -> str:
    cls = "pos" if o.score >= 0.12 else "neg" if o.score <= -0.12 else "neu"
    arrow = "▲" if cls == "pos" else "▼" if cls == "neg" else "■"
    return (f'<span class="badge {cls}">{arrow} {html.escape(o.label)}</span>'
            f'<span class="num">{o.score:+.2f}</span>'
            f'<span class="conf" title="Confiance">{o.confidence:.0%}</span>')


def _signals_table(t: TickerAnalysis, horizon: str) -> str:
    rows = []
    for pillar in ("technique", "sentiment", "macro", "recherche"):
        p = t.pillars.get(f"{pillar}_{horizon}")
        if not p:
            continue
        rows.append(f'<tr class="pillar"><td colspan="3">{pillar.capitalize()}</td>'
                    f'<td class="num">{p.score:+.2f}</td></tr>')
        for s in p.signals:
            val = "" if s.value is None else f"{s.value:,.2f}"
            cls = "pos" if s.score >= 0.12 else "neg" if s.score <= -0.12 else "neu"
            rows.append(f'<tr><td>{html.escape(s.name)}</td><td class="num">{val}</td>'
                        f'<td class="muted">{html.escape(s.comment)}</td>'
                        f'<td class="num {cls}">{s.score:+.2f}</td></tr>')
    return f'<table class="signals">{"".join(rows)}</table>'


REPORT_CSS = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f3f2ef; --border: #e2e0da;
  --text: #0b0b0b; --text-2: #52514e; --muted: #7a7873;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --pos: #1c5cab; --pos-bg: #cde2fb; --neg: #b3302f; --neg-bg: #f9d9d6;
  --neu-bg: #f0efec; --warning: #fab219; --critical: #d03b3b; --info: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --border: #383835;
    --text: #ffffff; --text-2: #c3c2b7; --muted: #9a998f;
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --pos: #86b6ef; --pos-bg: #184f95; --neg: #f0a3a0; --neg-bg: #6e2222;
    --neu-bg: #383835;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #232321; --border: #383835;
  --text: #ffffff; --text-2: #c3c2b7; --muted: #9a998f;
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --pos: #86b6ef; --pos-bg: #184f95; --neg: #f0a3a0; --neg-bg: #6e2222;
  --neu-bg: #383835;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 10px; }
h4 { margin: 8px 0; font-size: 13px; color: var(--text-2); }
.disclaimer { background: var(--surface-2); border-left: 3px solid var(--warning); padding: 8px 12px;
  color: var(--text-2); font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.card .big { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; }
.kvs { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 4px 20px; }
.kv { display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); padding: 3px 0; }
.kv span { color: var(--text-2); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: middle; }
th { font-size: 12px; color: var(--text-2); font-weight: 600; white-space: nowrap; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.muted { color: var(--muted); } .small { font-size: 12px; }
td.pos, .signals .pos { color: var(--pos); } td.neg, .signals .neg { color: var(--neg); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.badge.pos { background: var(--pos-bg); color: var(--text); }
.badge.neg { background: var(--neg-bg); color: var(--text); }
.badge.neu { background: var(--neu-bg); color: var(--text); }
.badge + .num { margin-left: 6px; } .conf { margin-left: 6px; color: var(--muted); font-size: 12px; }
.flag { display: inline-block; margin: 1px 4px 1px 0; padding: 1px 6px; border-radius: 4px; font-size: 11px;
  border: 1px solid var(--border); white-space: nowrap; color: var(--text); }
.flag.warning { border-color: var(--warning); } .flag.critical { border-color: var(--critical); }
.flag.info { border-color: var(--info); }
.spark .line { fill: none; stroke: var(--series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.spark .dot { fill: var(--series-1); stroke: var(--surface); stroke-width: 2; opacity: 0; }
.spark .hit { fill: transparent; }
.spark .pt:hover .dot { opacity: 1; }
details { border: 1px solid var(--border); border-radius: 8px; margin: 8px 0; padding: 8px 12px; background: var(--surface-2); }
summary { cursor: pointer; }
a { color: inherit; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
.signals td { font-size: 12px; padding: 4px 6px; } .signals .pillar td { font-weight: 650; background: var(--surface); }
ul.flags, ul.news { padding-left: 18px; } ul.flags li, ul.news li { margin: 4px 0; }
.thesis { font-size: 15px; margin: 10px 0 14px; }
.grid3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
.chart-wrap { position: relative; margin: 8px 0 12px; }
.legend { display: flex; gap: 16px; font-size: 12px; color: var(--text-2); margin-bottom: 4px; flex-wrap: wrap; }
.legend .key { display: inline-flex; align-items: center; gap: 6px; }
.pricechart { width: 100%; height: auto; display: block; }
.pricechart .series { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round;
  vector-effect: non-scaling-stroke; }
.pricechart line { vector-effect: non-scaling-stroke; }
.pricechart .grid { stroke: var(--border); stroke-width: 1; }
.pricechart .tick { fill: var(--muted); font-size: calc(11px * var(--k, 1)); }
.pricechart .level { stroke: var(--text-2); stroke-width: 1; stroke-dasharray: 2 4; opacity: .7; }
.pricechart .level-label { fill: var(--text-2); font-size: calc(10px * var(--k, 1)); }
.pricechart .xhair { stroke: var(--text-2); stroke-width: 1; }
.pricechart .hover-dot { stroke: var(--surface-2); stroke-width: 2; r: calc(4px * var(--k, 1));
  vector-effect: non-scaling-stroke; }
.pricechart .end-dot { r: calc(3px * var(--k, 1)); }
.pricechart .hit { fill: transparent; cursor: crosshair; }
.tooltip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 8px; font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.15); }
.tooltip .sw { display: inline-block; width: 10px; height: 3px; margin-right: 6px; vertical-align: middle; }
.tooltip .s1 { background: var(--series-1); } .tooltip .s2 { background: var(--series-2); }
.tooltip .s3 { background: var(--series-3); }
ul.pros, ul.cons { padding-left: 18px; margin: 4px 0; } ul.pros li, ul.cons li { margin: 3px 0; }
.signals th { font-size: 11px; }
tr.lv-support td:first-child, tr.lv-resistance td:first-child { font-weight: 600; }
.narrative p { margin: 6px 0; white-space: pre-line; }
time { color: var(--muted); font-variant-numeric: tabular-nums; }
@media (max-width: 600px) { .grid2 { grid-template-columns: 1fr; } .pricechart .level-label { display: none; } }
"""


def _flags_list(t: TickerAnalysis) -> str:
    items = "".join(
        f'<li class="flag-line {f.severity}"><span class="flag {f.severity}">{SEVERITY_ICON[f.severity]} '
        f'{SEVERITY_LABEL[f.severity]}</span> {html.escape(f.message)}</li>' for f in t.flags
    )
    return f'<ul class="flags">{items}</ul>' if items else ""


def html_stock_detail(t: TickerAnalysis) -> str:
    """Fiche d'une action (sans enveloppe) : synthèse, graphique, signaux, alertes."""
    return (
        _stock_html(t)
        + f'<div class="grid2"><div><h4>Court terme — fourchette {t.short.low:,.2f} – {t.short.high:,.2f}</h4>'
        f'{_signals_table(t, "court")}</div><div><h4>Moyen terme — fourchette '
        f'{t.medium.low:,.2f} – {t.medium.high:,.2f}</h4>{_signals_table(t, "moyen")}</div></div>'
        + _flags_list(t)
    )


def html_stock_header(t: TickerAnalysis) -> str:
    s = t.security
    return (f'<h1>{html.escape(s.ticker)} <span class="muted">— {html.escape(s.name)}</span></h1>'
            f'<p class="muted">{html.escape(s.sector)} · cours {t.last_close:,.2f} · semaine {t.week_return:+.2%} · '
            f'qualité des données {t.data_quality:.0%} · cohérence des sources {t.coherence:.0%}</p>'
            f'<div class="cards"><div class="card"><div class="muted">Court terme (1-2 semaines)</div>'
            f'<p>{_score_badge(t.short)}</p><div class="small muted" title="±1 écart-type de volatilité prévue (GARCH)">'
            f'Fourchette probable (2 chances sur 3) {t.short.low:,.2f} – {t.short.high:,.2f}</div></div>'
            f'<div class="card"><div class="muted">Moyen terme (1-3 mois)</div><p>{_score_badge(t.medium)}</p>'
            f'<div class="small muted" title="±1 écart-type de volatilité prévue (GARCH)">'
            f'Fourchette probable (2 chances sur 3) {t.medium.low:,.2f} – {t.medium.high:,.2f}</div></div></div>')


def html_agents(report: MarketReport) -> str:
    rows = "".join(
        f'<tr><td>{html.escape(a["agent"])}</td><td class="num">{a["done"]}</td><td class="num">{a["failed"]}</td>'
        f'<td class="num">{a["skipped"]}</td><td class="num">{a["ms"]:.0f} ms</td></tr>'
        for a in summarize_trace(report.trace)
    )
    return ('<h2>Équipe d\'agents</h2><div class="scroll"><table><thead><tr><th>Agent</th><th class="num">Réussies</th>'
            '<th class="num">Échecs</th><th class="num">Annulées</th><th class="num">Temps cumulé</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def html_market(report: MarketReport) -> str:
    """Vue marché : indice, macro, news, synthèse éventuelle et tableau des avis."""
    idx = report.index
    m = report.macro_summary
    b = report.breadth
    macro_rows = "".join(
        f'<div class="kv"><span>{html.escape(label.strip())}</span><strong>{fmt.format(m[key])}</strong></div>'
        for key, label, fmt in MACRO_LABELS if key in m
    )
    news = "".join(
        f'<li><time>{_jour(n.published.date())}</time> <b>{html.escape(n.source)}</b> '
        f'{html.escape(n.headline)}</li>' for n in report.market_news
    )
    rows = []
    for t in sorted(report.tickers, key=lambda x: -x.short.score):
        alert_html = "".join(
            f'<span class="flag {f.severity}" title="{html.escape(f.message)}">'
            f'{SEVERITY_ICON[f.severity]} {html.escape(f.code)}</span>' for f in t.flags if f.severity != "info"
        )
        rows.append(
            f'<tr><td><a href="#{t.security.ticker}" data-ticker="{t.security.ticker}"><b>{t.security.ticker}</b></a>'
            f'<div class="muted small">{html.escape(t.security.name)}</div></td>'
            f'<td class="muted small">{html.escape(t.security.sector)}</td>'
            f'<td class="num">{t.last_close:,.2f}</td>'
            f'<td class="num {"pos" if t.week_return > 0 else "neg"}">{t.week_return:+.1%}</td>'
            f'<td>{_sparkline(t.week_closes)}</td>'
            f'<td>{_score_badge(t.short)}</td><td>{_score_badge(t.medium)}</td>'
            f'<td class="num">{t.data_quality * t.coherence:.0%}</td><td>{alert_html}</td></tr>'
        )
    narrative_html = ""
    if report.narrative:
        paras = "".join(f"<p>{html.escape(p)}</p>" for p in report.narrative.split("\n\n") if p.strip())
        narrative_html = f'<h2>Synthèse de l\'agent rédacteur (Claude)</h2><div class="card narrative">{paras}</div>'
    return f"""
<h2>Marché</h2>
<div class="cards">
  <div class="card"><div class="muted">S&amp;P 500</div><div class="big">{idx.last_close:,.2f}</div>
    <div class="{'pos' if idx.week_return > 0 else 'neg'}">{idx.week_return:+.2%} sur la semaine</div>
    {_sparkline(idx.week_closes, 200, 40)}</div>
  <div class="card"><div class="muted">Court terme (1-2 semaines)</div><p>{_score_badge(idx.short)}</p>
    <div class="small muted">Fourchette probable (2 chances sur 3) {idx.short.low:,.0f} – {idx.short.high:,.0f}</div></div>
  <div class="card"><div class="muted">Moyen terme (1-3 mois)</div><p>{_score_badge(idx.medium)}</p>
    <div class="small muted">Fourchette probable (2 chances sur 3) {idx.medium.low:,.0f} – {idx.medium.high:,.0f}</div></div>
  <div class="card"><div class="muted">Largeur de marché</div>
    <div class="kv"><span>Titres en hausse (sem.)</span><strong>{b['advancers_week']:.0%}</strong></div>
    <div class="kv"><span>Au-dessus MM50</span><strong>{b['above_sma50']:.0%}</strong></div>
    <div class="kv"><span>Au-dessus MM200</span><strong>{b['above_sma200']:.0%}</strong></div></div>
</div>
<h2>Macro &amp; sentiment de marché</h2>
<div class="kvs">{macro_rows}</div>
<h2>News de marché</h2>
<ul class="news">{news}</ul>
{narrative_html}
<h2>Avis par action</h2>
<div class="scroll"><table>
<thead><tr><th>Titre</th><th>Secteur</th><th class="num">Cours</th><th class="num">Semaine</th><th>5 séances</th>
<th>Court terme</th><th>Moyen terme</th><th class="num">Fiabilité</th><th>Alertes</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def render_html(report: MarketReport) -> str:
    details = "".join(
        f'<details id="{t.security.ticker}"{" open" if len(report.tickers) <= 3 else ""}><summary>'
        f'<b>{t.security.ticker}</b> — {html.escape(t.security.name)} <span class="muted">· CT '
        f'{html.escape(t.short.label)} · MT {html.escape(t.medium.label)}</span></summary>'
        f'{html_stock_detail(t)}</details>'
        for t in sorted(report.tickers, key=lambda x: -x.short.score)
    )
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Analyse S&amp;P 500</title>
<style>{REPORT_CSS}</style></head>
<body><main>
<h1>Analyse S&amp;P 500 — semaine au {report.as_of.strftime('%d/%m/%Y')}</h1>
<p class="disclaimer">{html.escape(disclaimer(report))}</p>
{html_market(report)}
<h2>Détail par action</h2>
{details}
{html_agents(report)}
<p class="muted small">Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')} — score de -1 (baissier) à +1 (haussier) ;
la confiance intègre l'accord entre piliers, la qualité et la cohérence des données.</p>
</main>{CHART_SCRIPT}</body></html>
"""
