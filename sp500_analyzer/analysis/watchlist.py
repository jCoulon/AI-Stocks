"""Liste de surveillance : pour chaque titre choisi par l'utilisateur, une grille de conditions
d'entrée (support, rapport gain / risque, tendance, macro, avis de l'outil, consensus, résultats
proches) et un statut : « Zone d'entrée technique », « À surveiller », « Attendre la publication »
ou « Pas le moment ».

Ce statut applique des règles fixes et transparentes ; il ne prédit pas le marché. Testée sur deux
ans de cours réels (51 titres, dates espacées de 5 séances), la règle « à ≤ 1 ATR d'un support et
gain / risque ≥ 2 » a fait en moyenne +0,9 % sur 5 séances de plus que les autres titres, t 1,3 :
pas significatif (ENTRY_RULE_TEST ci-dessous). Ce n'est pas un conseil d'investissement.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from ..models import TickerAnalysis

DEFAULT_WATCHLIST = ["FIGR", "AIP", "CBRS", "NBIS", "IREN"]
#: Résultat du test historique de la règle d'entrée (docs/RECHERCHE_IA.md, section liste de surveillance).
ENTRY_RULE_TEST = ("Testée sur 2 ans de cours réels (51 titres) : les titres « en zone d'entrée » ont fait en moyenne "
                   "+0,9 % sur 5 séances et +0,8 % sur 21 séances de plus que les autres, t 1,3 et 0,3 — pas "
                   "significatif ; avec le filtre de tendance, aucun écart (+0,0 %).")
EVENT_DAYS = 10


def watchlist_path() -> Path:
    return Path(os.environ.get("SP500_WATCHLIST") or Path.home() / ".sp500_analyzer" / "watchlist.json")


def load_watchlist(path: Optional[Path] = None) -> list[str]:
    path = path or watchlist_path()
    try:
        tickers = json.loads(path.read_text(encoding="utf-8")).get("tickers", [])
        return [str(t).upper() for t in tickers if str(t).strip()]
    except (OSError, ValueError, AttributeError):
        return list(DEFAULT_WATCHLIST)


def save_watchlist(tickers: list[str], path: Optional[Path] = None) -> list[str]:
    path = path or watchlist_path()
    clean = list(dict.fromkeys(t.strip().upper() for t in tickers if t and t.strip()))[:50]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tickers": clean}, indent=1), encoding="utf-8")
    return clean


@dataclass
class Check:
    name: str
    ok: Optional[bool]   # True favorable, False défavorable, None neutre / inconnu
    detail: str


@dataclass
class EntryView:
    ticker: str
    name: str
    price: float
    verdict: str
    tone: str            # pos | neu | neg (couleur)
    summary: str
    checks: list[Check] = field(default_factory=list)
    support: Optional[float] = None
    resistance: Optional[float] = None
    stop: Optional[float] = None
    reward_risk: Optional[float] = None


def assess(t: TickerAnalysis, fund: Optional[dict] = None, next_event: Optional[tuple[date, str]] = None,
           as_of: Optional[date] = None, macro: Optional[dict] = None) -> EntryView:
    price = t.last_close
    atr_pct = (t.stats.get("atr") or 0) / price if price else 0
    atr_abs = (t.stats.get("atr") or 0)
    levels = t.stock.levels if t.stock else []
    below = sorted((lv for lv in levels if lv.price < price), key=lambda lv: -lv.price)
    above = sorted((lv for lv in levels if lv.price > price), key=lambda lv: lv.price)
    view = EntryView(t.security.ticker, t.security.name, price, "", "neu", "")
    checks = view.checks

    # 1. Support
    on_support = None
    if below and atr_abs:
        s = below[0]
        view.support = s.price
        dist = (price - s.price) / atr_abs
        on_support = dist <= 1
        checks.append(Check("Support proche", on_support,
                            f"{s.label} à {s.price:,.2f} ({price / s.price - 1:+.1%} ; {dist:.1f} ATR)"
                            + (" : cours au contact" if on_support else " : cours encore loin du support")))
    else:
        checks.append(Check("Support proche", None, "aucun support identifiable sous le cours"))

    # 2. Gain / risque
    rr_ok = None
    if view.support and above and atr_abs:
        r = above[0]
        view.resistance, view.stop = r.price, view.support - 0.5 * atr_abs
        risk = price - view.stop
        view.reward_risk = (r.price - price) / risk if risk > 0 else None
        if view.reward_risk is not None:
            rr_ok = view.reward_risk >= 2
            checks.append(Check("Gain / risque", rr_ok,
                                f"objectif {r.label.lower()} {r.price:,.2f} ({r.price / price - 1:+.1%}) vs invalidation "
                                f"sous {view.stop:,.2f} ({view.stop / price - 1:+.1%}) : ratio {view.reward_risk:.1f}"))
    if rr_ok is None and not any(c.name == "Gain / risque" for c in checks):
        checks.append(Check("Gain / risque", None, "pas de résistance ou de support pour le calculer"))

    # 3. Tendance de fond
    s50, s200 = t.stats.get("sma50"), t.stats.get("sma200")
    trend = None
    if s50 and s200:
        up = [price > s200, s50 > s200]
        trend = True if all(up) else False if not any(up) else None
        checks.append(Check("Tendance de fond", trend,
                            f"cours {price / s200 - 1:+.1%} vs MM200 ; MM50 {'au-dessus de' if s50 > s200 else 'sous'} la MM200"))
    else:
        checks.append(Check("Tendance de fond", None, "historique trop court (moins de 200 séances)"))

    # 4. Survente
    rsi = t.stats.get("rsi")
    if rsi is not None:
        checks.append(Check("Survente (RSI 14)", True if rsi <= 35 else False if rsi >= 70 else None,
                            f"RSI {rsi:.0f}" + (" : survendu" if rsi <= 35 else " : suracheté" if rsi >= 70 else "")))

    # 5. Avis court terme de l'outil
    sc = t.short.score
    checks.append(Check("Avis court terme de l'outil", True if sc >= 0.12 else False if sc <= -0.12 else None,
                        f"{t.short.label} ({sc:+.2f})"))

    # 6. Économie / macro
    macro_p = t.pillars.get("macro_court")
    m = macro or {}
    extra = ", ".join(x for x in (f"10 ans {m['us10y']:.2f} %" if "us10y" in m else "",
                                   f"VIX {m['vix']:.1f}" if "vix" in m else "") if x)
    if macro_p is not None:
        ms = macro_p.score
        checks.append(Check("Économie (taux, VIX, pétrole...)", True if ms >= 0.1 else False if ms <= -0.1 else None,
                            f"pilier macro {ms:+.2f}" + (f" ; {extra}" if extra else "")))

    # 7. Consensus des analystes
    f = fund or {}
    if f.get("target_mean"):
        up = f["target_mean"] / price - 1
        checks.append(Check("Consensus des analystes", True if up >= 0.15 else False if up < 0 else None,
                            f"objectif moyen {f['target_mean']:,.2f} ({up:+.0%}, {int(f.get('analysts') or 0)} analystes ; "
                            "objectifs en moyenne trop optimistes)"))

    # 8. Publication proche
    event_soon = False
    if next_event and as_of:
        days = (next_event[0] - as_of).days
        event_soon = 0 < days <= EVENT_DAYS
        checks.append(Check("Pas de résultats imminents", not event_soon,
                            f"{next_event[1]} le {next_event[0]:%d/%m} (J-{days})" if days > 0 else "aucune date connue"))

    against = sum(c.ok is False for c in checks if c.name in ("Tendance de fond", "Avis court terme de l'outil",
                                                                "Économie (taux, VIX, pétrole...)"))
    if event_soon:
        view.verdict, view.tone = "Attendre la publication", "neu"
        view.summary = "résultats dans moins de 10 jours : mouvement binaire possible, niveaux peu fiables d'ici là"
    elif on_support and rr_ok and against <= 1:
        view.verdict, view.tone = "Zone d'entrée technique", "pos"
        view.summary = (f"au contact du support {view.support:,.2f}, gain / risque {view.reward_risk:.1f} ; "
                        f"invalidation sous {view.stop:,.2f}")
    elif against >= 2 and not on_support:
        view.verdict, view.tone = "Pas le moment", "neg"
        view.summary = "tendance, macro ou avis de l'outil défavorables, et cours loin d'un support"
    else:
        view.verdict, view.tone = "À surveiller", "neu"
        view.summary = (f"attendre un retour vers {view.support:,.2f} (support)" if view.support and not on_support
                        else "conditions partagées" + (f" ; {against} défavorable(s) sur tendance / macro / avis" if against else ""))
    if atr_pct > 0.06:
        view.summary += f" ; très volatil ({atr_pct:.1%} par jour en moyenne)"
    return view


def render_text(views: list[EntryView], missing: list[str], as_of: date) -> str:
    out = [f"MA LISTE DE SURVEILLANCE — séance du {as_of:%d/%m/%Y}",
           "Conditions d'entrée selon des règles fixes ; ce n'est pas un conseil d'investissement.", ""]
    for v in views:
        out.append(f"  {v.ticker:6} {v.price:>9,.2f}  {v.verdict.upper()} — {v.summary}")
        for c in v.checks:
            mark = "✓" if c.ok else "✗" if c.ok is False else "·"
            out.append(f"      {mark} {c.name:34} {c.detail}")
        out.append("")
    if missing:
        out.append(f"  Sans données dans l'univers analysé : {', '.join(missing)}")
    out.append("  " + ENTRY_RULE_TEST)
    return "\n".join(out)


def render_html(views: list[EntryView], missing: list[str], as_of: date, tickers: list[str], known: list[str]) -> str:
    from html import escape

    cards = []
    for v in views:
        rows = "".join(
            f"<tr><td>{'<span class=pos>✓</span>' if c.ok else '<span class=neg>✗</span>' if c.ok is False else '<span class=muted>·</span>'}</td>"
            f"<td>{escape(c.name)}</td><td class='small'>{escape(c.detail)}</td></tr>" for c in v.checks)
        levels = ""
        if v.support and v.resistance and v.stop:
            levels = (f"<p class='small'>Support <strong>{v.support:,.2f}</strong> · invalidation sous "
                      f"<strong>{v.stop:,.2f}</strong> · objectif <strong>{v.resistance:,.2f}</strong>"
                      + (f" · gain / risque <strong>{v.reward_risk:.1f}</strong>" if v.reward_risk else "") + "</p>")
        cards.append(
            f"<section class='card'><div style='display:flex;justify-content:space-between;gap:8px;align-items:baseline'>"
            f"<h3><a href='#{escape(v.ticker)}' data-ticker='{escape(v.ticker)}'>{escape(v.ticker)}</a> "
            f"<span class='muted small'>{escape(v.name)} · {v.price:,.2f}</span></h3>"
            f"<button class='watch-remove' data-watch-remove='{escape(v.ticker)}' title='Retirer de la liste'>✕</button></div>"
            f"<p><span class='badge {v.tone}'>{escape(v.verdict)}</span> {escape(v.summary)}</p>{levels}"
            f"<table class='signals'>{rows}</table></section>")
    miss = "".join(f"<li><strong>{escape(t)}</strong> — pas de données dans l'univers affiché "
                   f"<button class='watch-remove' data-watch-remove='{escape(t)}'>✕</button></li>" for t in missing)
    options = "".join(f"<option value='{escape(k)}'>" for k in known)
    return f"""
<h2>Ma liste de surveillance</h2>
<p class="muted small">Séance du {as_of:%d/%m/%Y} · {len(tickers)} titre(s). Pour chaque titre : conditions d'entrée selon
des règles fixes (support, gain / risque, tendance, économie, avis de l'outil, consensus, résultats proches).
Ce n'est pas un conseil d'investissement.</p>
<section class="card"><form id="watch-form" style="display:flex;gap:8px;flex-wrap:wrap">
<input id="watch-input" list="watch-known" placeholder="Ajouter un titre (ex. NVDA)" autocomplete="off" style="flex:1;min-width:160px">
<datalist id="watch-known">{options}</datalist><button type="submit">Ajouter</button></form>
{f'<ul class="small">{miss}</ul>' if miss else ''}</section>
{''.join(cards) or '<p class="empty">Liste vide : ajoutez un titre ci-dessus.</p>'}
<section class="card small"><p><strong>Zone d'entrée technique</strong> : cours à moins d'un ATR (mouvement moyen d'une
séance) au-dessus du support le plus proche, gain potentiel jusqu'à la résistance au moins 2 fois la perte jusqu'au
niveau d'invalidation (support − ½ ATR), et au plus un signal défavorable parmi tendance, économie et avis de l'outil.</p>
<p>⚠ {escape(ENTRY_RULE_TEST)} Ces conditions aident à structurer une décision (où entrer, où se tromper, quel
objectif) ; elles ne disent pas si le cours va monter.</p></section>"""
