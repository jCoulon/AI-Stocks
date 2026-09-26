"""Mise en forme des résultats : terminal, JSON et page HTML autonome."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import date, datetime

from .models import MarketReport, Outlook, TickerAnalysis

DISCLAIMER = (
    "Outil d'analyse de données — PAS un conseil en investissement. Les avis sont des "
    "synthèses statistiques d'indicateurs, sans garantie. Données de démonstration SIMULÉES."
)

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
    out.append(st(DISCLAIMER, "2"))
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

    for ticker in detail or []:
        t = next((x for x in report.tickers if x.security.ticker == ticker.upper()), None)
        if t:
            out.extend(render_detail(t, st))
            out.append(line)
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
        out.append(f"    Fourchette indicative : {o.low:.2f} — {o.high:.2f}")
        out.append("    Contributions : " + ", ".join(f"{k} {v:+.2f}" for k, v in o.contributions.items()))
        horizon = "court" if o is t.short else "moyen"
        for pillar in ("technique", "sentiment", "macro"):
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
    data["disclaimer"] = DISCLAIMER
    return json.dumps(data, default=_default, ensure_ascii=False, indent=2)


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


def _score_badge(o: Outlook) -> str:
    cls = "pos" if o.score >= 0.12 else "neg" if o.score <= -0.12 else "neu"
    arrow = "▲" if cls == "pos" else "▼" if cls == "neg" else "■"
    return (f'<span class="badge {cls}">{arrow} {html.escape(o.label)}</span>'
            f'<span class="num">{o.score:+.2f}</span>'
            f'<span class="conf" title="Confiance">{o.confidence:.0%}</span>')


def _signals_table(t: TickerAnalysis, horizon: str) -> str:
    rows = []
    for pillar in ("technique", "sentiment", "macro"):
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


def render_html(report: MarketReport) -> str:
    idx = report.index
    m = report.macro_summary
    macro_rows = "".join(
        f'<div class="kv"><span>{html.escape(label.strip())}</span><strong>{fmt.format(m[key])}</strong></div>'
        for key, label, fmt in MACRO_LABELS if key in m
    )
    news = "".join(
        f'<li><time>{_jour(n.published.date())}</time> <b>{html.escape(n.source)}</b> '
        f'{html.escape(n.headline)}</li>' for n in report.market_news
    )
    rows, details = [], []
    for t in sorted(report.tickers, key=lambda x: -x.short.score):
        alerts = [f for f in t.flags if f.severity != "info"]
        alert_html = "".join(
            f'<span class="flag {f.severity}" title="{html.escape(f.message)}">'
            f'{SEVERITY_ICON[f.severity]} {html.escape(f.code)}</span>' for f in alerts
        )
        rows.append(
            f'<tr><td><a href="#{t.security.ticker}"><b>{t.security.ticker}</b></a>'
            f'<div class="muted small">{html.escape(t.security.name)}</div></td>'
            f'<td class="muted small">{html.escape(t.security.sector)}</td>'
            f'<td class="num">{t.last_close:,.2f}</td>'
            f'<td class="num {"pos" if t.week_return > 0 else "neg"}">{t.week_return:+.1%}</td>'
            f'<td>{_sparkline(t.week_closes)}</td>'
            f'<td>{_score_badge(t.short)}</td><td>{_score_badge(t.medium)}</td>'
            f'<td class="num">{t.data_quality * t.coherence:.0%}</td><td>{alert_html}</td></tr>'
        )
        flags = "".join(
            f'<li class="flag-line {f.severity}"><span class="flag {f.severity}">{SEVERITY_ICON[f.severity]} '
            f'{SEVERITY_LABEL[f.severity]}</span> {html.escape(f.message)}</li>' for f in t.flags
        )
        details.append(
            f'<details id="{t.security.ticker}"><summary><b>{t.security.ticker}</b> — '
            f'{html.escape(t.security.name)} <span class="muted">· CT {html.escape(t.short.label)} · '
            f'MT {html.escape(t.medium.label)}</span></summary>'
            f'<div class="grid2"><div><h4>Court terme — fourchette {t.short.low:,.2f} – {t.short.high:,.2f}</h4>'
            f'{_signals_table(t, "court")}</div><div><h4>Moyen terme — fourchette '
            f'{t.medium.low:,.2f} – {t.medium.high:,.2f}</h4>{_signals_table(t, "moyen")}</div></div>'
            + (f'<ul class="flags">{flags}</ul>' if flags else "") + '</details>'
        )

    b = report.breadth
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Analyse S&amp;P 500</title>
<style>
:root {{
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f3f2ef; --border: #e2e0da;
  --text: #0b0b0b; --text-2: #52514e; --muted: #7a7873;
  --series-1: #2a78d6; --pos: #1c5cab; --pos-bg: #cde2fb; --neg: #b3302f; --neg-bg: #f9d9d6;
  --neu-bg: #f0efec; --warning: #fab219; --critical: #d03b3b; --info: #2a78d6;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --border: #383835;
    --text: #ffffff; --text-2: #c3c2b7; --muted: #9a998f;
    --series-1: #3987e5; --pos: #86b6ef; --pos-bg: #184f95; --neg: #f0a3a0; --neg-bg: #6e2222;
    --neu-bg: #383835;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #232321; --border: #383835;
  --text: #ffffff; --text-2: #c3c2b7; --muted: #9a998f;
  --series-1: #3987e5; --pos: #86b6ef; --pos-bg: #184f95; --neg: #f0a3a0; --neg-bg: #6e2222;
  --neu-bg: #383835;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--surface); color: var(--text);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }} h2 {{ font-size: 16px; margin: 28px 0 10px; }}
h4 {{ margin: 8px 0; font-size: 13px; color: var(--text-2); }}
.disclaimer {{ background: var(--surface-2); border-left: 3px solid var(--warning); padding: 8px 12px;
  color: var(--text-2); font-size: 13px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
.card {{ background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }}
.card .big {{ font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; }}
.kvs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 4px 20px; }}
.kv {{ display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); padding: 3px 0; }}
.kv span {{ color: var(--text-2); }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: middle; }}
th {{ font-size: 12px; color: var(--text-2); font-weight: 600; white-space: nowrap; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.muted {{ color: var(--muted); }} .small {{ font-size: 12px; }}
td.pos, .signals .pos {{ color: var(--pos); }} td.neg, .signals .neg {{ color: var(--neg); }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }}
.badge.pos {{ background: var(--pos-bg); color: var(--text); }}
.badge.neg {{ background: var(--neg-bg); color: var(--text); }}
.badge.neu {{ background: var(--neu-bg); color: var(--text); }}
.badge + .num {{ margin-left: 6px; }} .conf {{ margin-left: 6px; color: var(--muted); font-size: 12px; }}
.flag {{ display: inline-block; margin: 1px 4px 1px 0; padding: 1px 6px; border-radius: 4px; font-size: 11px;
  border: 1px solid var(--border); white-space: nowrap; color: var(--text); }}
.flag.warning {{ border-color: var(--warning); }} .flag.critical {{ border-color: var(--critical); }}
.flag.info {{ border-color: var(--info); }}
.spark .line {{ fill: none; stroke: var(--series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.spark .dot {{ fill: var(--series-1); stroke: var(--surface); stroke-width: 2; opacity: 0; }}
.spark .hit {{ fill: transparent; }}
.spark .pt:hover .dot {{ opacity: 1; }}
details {{ border: 1px solid var(--border); border-radius: 8px; margin: 8px 0; padding: 8px 12px; background: var(--surface-2); }}
summary {{ cursor: pointer; }}
a {{ color: inherit; }}
.grid2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }}
.signals td {{ font-size: 12px; padding: 4px 6px; }} .signals .pillar td {{ font-weight: 650; background: var(--surface); }}
ul.flags, ul.news {{ padding-left: 18px; }} ul.flags li, ul.news li {{ margin: 4px 0; }}
time {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
@media (max-width: 600px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
</style></head>
<body><main>
<h1>Analyse S&amp;P 500 — semaine au {report.as_of.strftime('%d/%m/%Y')}</h1>
<p class="disclaimer">{html.escape(DISCLAIMER)}</p>

<h2>Marché</h2>
<div class="cards">
  <div class="card"><div class="muted">S&amp;P 500</div><div class="big">{idx.last_close:,.2f}</div>
    <div class="{'pos' if idx.week_return > 0 else 'neg'}">{idx.week_return:+.2%} sur la semaine</div>
    {_sparkline(idx.week_closes, 200, 40)}</div>
  <div class="card"><div class="muted">Court terme (1-2 semaines)</div><p>{_score_badge(idx.short)}</p>
    <div class="small muted">Fourchette {idx.short.low:,.0f} – {idx.short.high:,.0f}</div></div>
  <div class="card"><div class="muted">Moyen terme (1-3 mois)</div><p>{_score_badge(idx.medium)}</p>
    <div class="small muted">Fourchette {idx.medium.low:,.0f} – {idx.medium.high:,.0f}</div></div>
  <div class="card"><div class="muted">Largeur de marché</div>
    <div class="kv"><span>Titres en hausse (sem.)</span><strong>{b['advancers_week']:.0%}</strong></div>
    <div class="kv"><span>Au-dessus MM50</span><strong>{b['above_sma50']:.0%}</strong></div>
    <div class="kv"><span>Au-dessus MM200</span><strong>{b['above_sma200']:.0%}</strong></div></div>
</div>

<h2>Macro &amp; sentiment de marché</h2>
<div class="kvs">{macro_rows}</div>
<h2>News de marché</h2>
<ul class="news">{news}</ul>

<h2>Avis par action</h2>
<div class="scroll"><table>
<thead><tr><th>Titre</th><th>Secteur</th><th class="num">Cours</th><th class="num">Semaine</th><th>5 séances</th>
<th>Court terme</th><th>Moyen terme</th><th class="num">Fiabilité</th><th>Alertes</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>

<h2>Détail par action</h2>
{''.join(details)}
<p class="muted small">Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')} — score de -1 (baissier) à +1 (haussier) ;
la confiance intègre l'accord entre piliers, la qualité et la cohérence des données.</p>
</main></body></html>
"""
