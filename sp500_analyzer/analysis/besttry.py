"""Écran « Best try » : titres ayant un catalyseur daté prochainement (résultats, fin de
lock-up...) capable de faire bouger fortement le cours — dans un sens OU dans l'autre.

Mouvement attendu d'un événement :
  - résultats : médiane des réactions passées du titre à ses publications (variation absolue
    de la clôture de la veille à celle du lendemain, 2 séances) ; sans historique, ordre de
    grandeur = 2 × le mouvement normal sur 2 séances ;
  - fin de lock-up : mouvement normal sur 2 séances, avec un biais baissier documenté
    (rendement anormal moyen d'environ −1 à −3 % autour de l'échéance, surtout pour les
    sociétés financées par capital-risque : Field & Hanka, 2001 ; Ofek & Richardson, 2000).
« Multiple » = mouvement attendu / mouvement normal sur 2 séances : > 1,5 signale un
événement qui fait nettement plus bouger le titre qu'une séance ordinaire.

Le SENS du mouvement n'est pas prévisible par cet écran : la réaction aux résultats dépend de
l'écart aux attentes, inconnu à l'avance ; les avis CT/MT affichés sont ceux de l'outil, qui
n'ont pas montré de pouvoir prédictif sur données réelles. Descriptif, pas un conseil.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Optional

from ..models import Bar
from ..providers.events import Event

EARNINGS_FALLBACK_MULTIPLE = 2.0


@dataclass
class BestTryRow:
    ticker: str
    name: str
    theme: str
    price: float
    event: Event
    days: int
    normal_move: Optional[float]           # |variation| médiane sur 2 séances (1 an)
    expected_move: Optional[float]
    past_moves: list[float] = field(default_factory=list)  # réactions passées (signées)
    estimated_move: bool = False
    bias: str = ""
    short_label: str = ""
    medium_label: str = ""
    links: str = ""
    flags: list[str] = field(default_factory=list)
    implied_move: Optional[float] = None   # mouvement de l'événement anticipé par les options
    implied_expiry: str = ""

    @property
    def pricing(self) -> str:
        """Historique du titre vs options : « sous-évalué » quand le titre bouge d'habitude nettement
        plus que ce que les options anticipent, « surévalué » dans le cas inverse."""
        if self.implied_move is None or self.expected_move is None or self.estimated_move:
            return ""
        if self.implied_move <= 0 or self.expected_move >= 1.25 * self.implied_move:
            return "sous-évalué"
        if self.expected_move <= 0.8 * self.implied_move:
            return "surévalué"
        return "cohérent"

    @property
    def multiple(self) -> Optional[float]:
        if self.expected_move is None or not self.normal_move:
            return None
        return self.expected_move / self.normal_move


def two_day_moves(bars: list[Bar], days: int = 252) -> list[float]:
    closes = [b.close for b in bars[-days - 2:]]
    return [closes[i + 2] / closes[i] - 1 for i in range(len(closes) - 2)]


def earnings_reactions(bars: list[Bar], report_days: list[date]) -> list[float]:
    """Réaction du cours à chaque publication passée : clôture de la séance précédant la date
    de publication -> clôture de la séance suivante (couvre publication avant ouverture ou
    après clôture)."""
    dates = [b.day for b in bars]
    out = []
    for d in report_days:
        i = bisect_left(dates, d)  # première séance >= d
        if i == 0 or i >= len(dates) or (dates[i] - d).days > 4:
            continue
        j = i + 1 if dates[i] == d else i  # publication un jour sans séance : réaction à la séance suivante
        if j >= len(dates):
            continue
        out.append(bars[j].close / bars[i - 1].close - 1)
    return out


def build_rows(ticker: str, name: str, theme: str, bars: list[Bar], events: list[Event], as_of: date,
               horizon: int, past_reports: list[date], fund: Optional[dict] = None, links: str = "") -> list[BestTryRow]:
    """Une ligne par événement du titre dans l'horizon (jours calendaires après as_of)."""
    bars = [b for b in bars if b.day <= as_of]
    if len(bars) < 30:
        return []
    normal = [abs(m) for m in two_day_moves(bars)]
    normal_move = median(normal) if normal else None
    reactions = earnings_reactions(bars, [d for d in past_reports if d <= as_of])
    rows = []
    for ev in events:
        days = (ev.day - as_of).days
        if not 0 < days <= horizon:
            continue
        row = BestTryRow(ticker, name, theme, bars[-1].close, ev, days, normal_move, None, links=links)
        if ev.kind == "resultats":
            row.past_moves = reactions[-8:]
            if reactions:
                row.expected_move = median(abs(r) for r in reactions[-8:])
            elif normal_move:
                row.expected_move, row.estimated_move = EARNINGS_FALLBACK_MULTIPLE * normal_move, True
            ups = sum(r > 0 for r in row.past_moves)
            if len(row.past_moves) >= 3:
                row.bias = f"{ups} hausse(s) / {len(row.past_moves) - ups} baisse(s) aux dernières publications"
        elif ev.kind == "lockup":
            row.expected_move, row.estimated_move = normal_move, True
            row.bias = "biais baissier documenté (offre de titres des initiés)"
        elif ev.kind == "lie":
            row.expected_move, row.estimated_move = normal_move, True
            row.bias = "sens selon le contenu de l'annonce (produits, contrats, financement)"
        else:
            row.expected_move, row.estimated_move = normal_move, True
        f = fund or {}
        if (f.get("short_float") or 0) > 0.15:
            row.flags.append(f"vente à découvert {f['short_float']:.0%} : mouvements amplifiés possibles")
        if not ev.confirmed:
            row.flags.append("date non confirmée")
        if normal_move and normal_move > 0.08:
            row.flags.append("titre très volatil au quotidien")
        rows.append(row)
    return rows


def rank(rows: list[BestTryRow]) -> list[BestTryRow]:
    """Plus grand mouvement attendu d'abord ; à égalité, l'événement le plus proche."""
    return sorted(rows, key=lambda r: (r.expected_move is None, -(r.expected_move or 0), r.days))


def _pct(x: Optional[float], signed: bool = False) -> str:
    return "—" if x is None else (f"{x:+.1%}" if signed else f"{x:.1%}")


def _event_text(r: BestTryRow) -> str:
    return (f"{r.event.label} {r.event.day:%d/%m}" + (" (estimée)" if not r.event.confirmed and "estimée" not in r.event.label else "")
            + (f", {r.event.timing}" if r.event.timing else ""))


def render_besttry(rows: list[BestTryRow], as_of: date, horizon: int, market: list[Event]) -> str:
    out = [f"BEST TRY — CATALYSEURS DES {horizon} PROCHAINS JOURS (au {as_of:%d/%m/%Y})",
           "Potentiel de mouvement rapide, à la hausse COMME à la baisse. Descriptif : ce n'est pas un conseil.", "",
           f"  {'Titre':6} {'Événement':46} {'J-':>4} {'Mvt att.':>8} {'Options':>7} {'Lecture':12} {'Normal':>7} "
           f"{'Mult.':>5} {'Réactions passées':30} {'Avis CT / MT':30} Remarques"]
    for r in rows:
        mult = "—" if r.multiple is None else f"{r.multiple:.1f}x"
        past = " ".join(f"{m:+.0%}" for m in r.past_moves[-5:]) or "—"
        exp = _pct(r.expected_move) + ("*" if r.estimated_move else "")
        notes = "; ".join(x for x in [r.bias, r.links, *r.flags] if x)
        out.append(f"  {r.ticker:6} {_event_text(r)[:46]:46} {r.days:>4} {exp:>8} {_pct(r.implied_move):>7} "
                   f"{r.pricing:12} {_pct(r.normal_move):>7} {mult:>5} "
                   f"{past[:30]:30} {(r.short_label + ' / ' + r.medium_label)[:30]:30} {notes}")
    if not rows:
        out.append("  (aucun catalyseur daté dans l'horizon — lancez le workflow « Données de marché réelles »)")
    if market:
        out += ["", "  Événements de marché (touchent tous les titres) :"]
        out += [f"    {e.day:%d/%m/%Y} (J-{(e.day - as_of).days}) {e.label}" + (f" — {e.note}" if e.note else "")
                for e in market]
    out += ["",
            "  Mvt att. : variation absolue attendue sur 2 séances autour de l'événement (médiane des réactions",
            "  passées du titre ; * = estimation faute d'historique). Normal : médiane sur 2 séances ordinaires.",
            "  Mult. : Mvt att. / Normal. Réactions passées : variations signées aux dernières publications.",
            "  Options : mouvement de l'événement seul anticipé par les options (straddle à la monnaie de la 1re",
            "  échéance après l'événement, moins la variance des séances ordinaires). Lecture : « sous-évalué »",
            "  si le titre bouge d'habitude ≥ 1,25 × ce que les options anticipent, « surévalué » si ≤ 0,8 ×",
            "  (sur 4 réactions passées seulement : indice fragile, suivi dans le journal des prévisions).",
            "  ⚠ Le sens de la réaction aux résultats dépend de l'écart aux attentes, inconnu à l'avance.",
            "  ⚠ Fin de lock-up : baisse moyenne d'environ 1 à 3 % autour de l'échéance (Field & Hanka, 2001).",
            "  ⚠ Un mouvement attendu élevé est un risque autant qu'une opportunité ; écran non validé par backtest."]
    return "\n".join(out)


def html_besttry(rows: list[BestTryRow], as_of: date, horizon: int, market: list[Event], fetched: str = "") -> str:
    from html import escape

    def signed(x):
        return f'<span class="{"pos" if x >= 0 else "neg"}">{x:+.0%}</span>'

    body = []
    for r in rows:
        mult = "—" if r.multiple is None else (f"<strong>{r.multiple:.1f}x</strong>" if r.multiple >= 1.5
                                                else f"{r.multiple:.1f}x")
        past = " ".join(signed(m) for m in r.past_moves[-5:]) or "—"
        exp = _pct(r.expected_move) + ('<span title="estimation faute d&#39;historique">*</span>' if r.estimated_move else "")
        notes = " ".join(f'<span class="badge neu">{escape(x)}</span>' for x in r.flags)
        extra = "".join(f'<div class="muted small">{escape(x)}</div>' for x in (r.bias, r.links, r.event.note) if x)
        soon = ' class="pos"' if r.days <= 7 else ""
        body.append(
            f'<tr><td><a href="#{escape(r.ticker)}" data-ticker="{escape(r.ticker)}"><strong>{escape(r.ticker)}</strong></a>'
            f'<div class="muted small">{escape(r.theme)}</div></td>'
            f'<td>{escape(_event_text(r))}{extra}</td><td class="num"><span{soon}>J-{r.days}</span></td>'
            f'<td class="num"><strong>±{exp}</strong></td>'
            f'<td class="num">{"—" if r.implied_move is None else "±" + _pct(r.implied_move)}'
            + (f'<div class="small"><span class="badge {"pos" if r.pricing == "sous-évalué" else "neg" if r.pricing == "surévalué" else "neu"}">{r.pricing}</span></div>' if r.pricing else "")
            + f'</td><td class="num">±{_pct(r.normal_move)}</td>'
            f'<td class="num">{mult}</td><td class="num small">{past}</td>'
            f'<td class="small">{escape(r.short_label)} / {escape(r.medium_label)}</td><td class="small">{notes}</td></tr>')
    if not body:
        body.append('<tr><td colspan="10" class="muted">Aucun catalyseur daté dans l\'horizon (calendrier des résultats '
                    'absent ? lancez le workflow « Données de marché réelles »).</td></tr>')
    head = ("<tr><th>Titre</th><th>Catalyseur</th><th class='num'>Dans</th>"
            "<th class='num' title='Variation absolue attendue sur 2 séances autour de l&#39;événement'>Mvt attendu</th>"
            "<th class='num' title='Mouvement de l&#39;événement anticipé par les options (straddle à la monnaie)'>Options</th>"
            "<th class='num' title='Variation absolue médiane sur 2 séances ordinaires'>Normal</th>"
            "<th class='num' title='Mouvement attendu / normal'>Mult.</th>"
            "<th class='num'>Réactions passées</th><th>Avis CT / MT</th><th>Remarques</th></tr>")
    mk = "".join(f"<li><strong>{e.day:%d/%m/%Y}</strong> (J-{(e.day - as_of).days}) {escape(e.label)}"
                 + (f" — <span class='muted'>{escape(e.note)}</span>" if e.note else "") + "</li>" for e in market)
    market_html = (f'<section class="card"><h3>Événements de marché</h3><p class="muted small">Touchent tous les '
                   f'titres, les plus volatils davantage.</p><ul>{mk}</ul></section>') if market else ""
    src = f"Calendrier Nasdaq du {fetched}" if fetched else "Calendrier des résultats absent"
    return f"""
<h2>Best try — catalyseurs des {horizon} prochains jours</h2>
<p class="muted small">Au {as_of:%d/%m/%Y} · {escape(src)} · classement par mouvement attendu. Potentiel de mouvement
rapide à la hausse <strong>comme</strong> à la baisse — descriptif, non validé par backtest : ce n'est pas un conseil
d'investissement.</p>
<section class="card"><div class="scroll"><table class="signals">{head}{"".join(body)}</table></div></section>
{market_html}
<section class="card small">
  <p><strong>Mouvement attendu</strong> : médiane des variations absolues du titre sur 2 séances (veille → lendemain)
  lors de ses dernières publications de résultats ; * = ordre de grandeur faute d'historique (2 × le mouvement normal).
  <strong>Mult.</strong> : combien de fois un mouvement ordinaire sur 2 séances.</p>
  <p>⚠ Le <strong>sens</strong> de la réaction aux résultats dépend de l'écart aux attentes, inconnu à l'avance : les
  réactions passées montrent l'amplitude, pas la direction à venir. Les avis CT/MT de l'outil n'ont pas montré de
  pouvoir prédictif sur données réelles.</p>
  <p>⚠ Fin de lock-up : les initiés peuvent vendre ; baisse moyenne d'environ 1 à 3 % autour de l'échéance
  (Field &amp; Hanka, 2001), date à vérifier dans le prospectus.</p>
  <p>⚠ Un fort mouvement attendu est un risque autant qu'une opportunité ; les options se renchérissent à l'approche
  des résultats puis perdent cette prime juste après.</p>
</section>"""


def add_implied(row: BestTryRow, snap: Optional[dict], bars: list[Bar], as_of: date) -> None:
    """Mouvement anticipé par les options, si le relevé est contemporain de la date d'analyse."""
    from ..providers.options import implied_event_move
    from .indicators import stdev

    if not snap or row.event.kind not in ("resultats", "lockup", "lie"):
        return
    fetched = date.fromisoformat(snap["fetched"])
    if not -1 <= (fetched - as_of).days <= 4:  # relevé d'une autre période : non comparable
        return
    closes = [b.close for b in bars if b.day <= as_of][-61:]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    im = implied_event_move(snap, row.event.day, max(as_of, fetched), stdev(rets) if len(rets) > 20 else None)
    if im:
        row.implied_move, row.implied_expiry = im["event_move"], im["expiry"]


def screen(provider, root, horizon: int = 60, labels: Optional[dict] = None, only: Optional[set] = None
           ) -> tuple[list[BestTryRow], list[Event], str]:
    """Écran complet pour un fournisseur de données réelles (CsvPriceProvider / RealDataProvider)."""
    from pathlib import Path

    from ..providers.events import load_events, market_events, ticker_events
    from ..providers.fundamentals import load_fundamentals
    from ..providers.options import load_options
    from ..universe import AI_THEME, LINKS

    root = Path(root)
    as_of = provider.as_of
    histories = {s.ticker: provider.price_history(s.ticker) for s in provider.universe()}
    firsts = [h[0].day for h in histories.values() if h]
    history_start = min(firsts) if firsts else None
    rows, fetched = [], set()
    for sec in provider.universe():
        if only is not None and sec.ticker not in only:
            continue
        bars = histories[sec.ticker]
        if not bars:
            continue
        data = load_events(root, sec.ticker) or {}
        if data.get("fetched"):
            fetched.add(data["fetched"])
        events = ticker_events(root, sec.ticker, bars[0].day, history_start, as_of)
        links = ", ".join(f"lié à {l.name}" for l in LINKS.get(sec.ticker, []))
        for row in build_rows(sec.ticker, sec.name, AI_THEME.get(sec.ticker, sec.sector), bars, events, as_of, horizon,
                              [date.fromisoformat(d) for d in data.get("past_earnings", [])],
                              load_fundamentals(root, sec.ticker), links):
            row.short_label, row.medium_label = (labels or {}).get(sec.ticker, ("", ""))
            add_implied(row, load_options(root, sec.ticker), bars, as_of)
            rows.append(row)
    return rank(rows), market_events(root, as_of, horizon), max(fetched) if fetched else ""

