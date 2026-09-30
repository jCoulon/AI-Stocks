"""Journal des prévisions : chaque jour, l'outil enregistre ses avis (court et moyen terme), le statut
de la grille d'entrée de chaque titre et, pour les catalyseurs datés, le mouvement attendu d'après
l'historique et d'après les options. Les prévisions sont ensuite notées automatiquement quand les
cours suivants sont connus : c'est la seule mesure honnête de l'outil sur des données qu'il n'a
jamais vues (aucun réglage n'est fait sur le journal).

Fichier : <dossier>/journal/calls.csv (une ligne par titre et par séance ; un nouvel
enregistrement pour une même séance remplace le précédent).
"""

from __future__ import annotations

import csv
import math
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, median, stdev
from typing import Optional

FIELDS = ["Date", "Ticker", "Price", "ShortScore", "ShortLabel", "MediumScore", "MediumLabel", "Status",
          "Support", "Stop", "Target", "EventDate", "EventKind", "HistMove", "ImpliedMove", "Recorded"]


def journal_path(root: Path) -> Path:
    return Path(root) / "journal" / "calls.csv"


def _f(x: Optional[float], nd: int = 4) -> str:
    return "" if x is None else f"{x:.{nd}f}"


def record(root: Path, as_of: date, report, views: dict, events: dict, recorded: str) -> int:
    """Ajoute (ou remplace) les prévisions de la séance as_of.

    views : ticker -> EntryView (grille d'entrée) ; events : ticker -> BestTryRow du prochain catalyseur."""
    path = journal_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in read(root) if r["Date"] != as_of.isoformat()]
    new = []
    for t in report.tickers:
        tk = t.security.ticker
        v, e = views.get(tk), events.get(tk)
        new.append({
            "Date": as_of.isoformat(), "Ticker": tk, "Price": _f(t.last_close),
            "ShortScore": _f(t.short.score), "ShortLabel": t.short.label,
            "MediumScore": _f(t.medium.score), "MediumLabel": t.medium.label,
            "Status": v.verdict if v else "", "Support": _f(v.support if v else None),
            "Stop": _f(v.stop if v else None), "Target": _f(v.resistance if v else None),
            "EventDate": e.event.day.isoformat() if e else "", "EventKind": e.event.kind if e else "",
            "HistMove": _f(e.expected_move if e and not e.estimated_move else None),
            "ImpliedMove": _f(e.implied_move if e else None), "Recorded": recorded})
    rows += new
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["Date"], r["Ticker"])))
    return len(new)


def read(root: Path) -> list[dict]:
    path = journal_path(root)
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(s: str) -> Optional[float]:
    try:
        return float(s) if s not in ("", None) else None
    except ValueError:
        return None


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> Optional[float]:
    if len(a) < 5:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def _t(xs: list[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    s = stdev(xs)
    return mean(xs) / s * math.sqrt(len(xs)) if s else None


@dataclass
class Score:
    name: str
    n: int                      # nombre de séances (ou d'événements) notées
    value: Optional[float]      # IC moyen, écart de rendement ou erreur
    t: Optional[float]
    detail: str


def score(rows: list[dict], closes: dict[str, list[tuple[date, float]]]) -> dict:
    """Note les prévisions dont l'échéance est passée.

    - avis : IC de Spearman quotidien (score vs rendement relatif à l'univers), 5 et 21 séances,
      t calculé sur des séances espacées de l'horizon (fenêtres disjointes) ;
    - statut « Zone d'entrée technique » : rendement à 5 séances vs les autres titres, même séance ;
    - catalyseurs : mouvement réel sur 2 séances autour de l'événement vs mouvement attendu
      (historique, options) — erreur absolue moyenne ; le meilleur des deux est le plus bas."""
    series = {t: ([d for d, _ in v], [c for _, c in v]) for t, v in closes.items()}

    def fwd(t: str, d: date, h: int) -> Optional[float]:
        s = series.get(t)
        if not s:
            return None
        i = bisect_left(s[0], d)
        if i >= len(s[0]) or s[0][i] != d or i + h >= len(s[0]):
            return None
        return s[1][i + h] / s[1][i] - 1

    by_date = defaultdict(list)
    for r in rows:
        by_date[date.fromisoformat(r["Date"])].append(r)
    days = sorted(by_date)
    out: dict = {"first": days[0].isoformat() if days else None, "last": days[-1].isoformat() if days else None,
                 "sessions": len(days), "rows": len(rows), "scores": []}
    for key, h, label in (("ShortScore", 5, "Avis court terme → rendement à 5 séances"),
                          ("MediumScore", 21, "Avis moyen terme → rendement à 21 séances")):
        ics = {}
        for d in days:
            pairs = [(_num(r[key]), fwd(r["Ticker"], d, h)) for r in by_date[d]]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            if len(pairs) >= 5:
                avg = mean(b for _, b in pairs)
                ic = spearman([a for a, _ in pairs], [b - avg for _, b in pairs])
                if ic is not None:
                    ics[d] = ic
        spaced = [ics[d] for d in sorted(ics)][::h]
        out["scores"].append(Score(label, len(ics), mean(ics.values()) if ics else None, _t(spaced),
                                   "IC moyen (0 = aucun pouvoir de classement)"))
    diffs = []
    for d in days:
        ins, outs = [], []
        for r in by_date[d]:
            y = fwd(r["Ticker"], d, 5)
            if y is None:
                continue
            (ins if r["Status"] == "Zone d'entrée technique" else outs).append(y)
        if ins and outs:
            diffs.append(mean(ins) - mean(outs))
    out["scores"].append(Score("« Zone d'entrée technique » → 5 séances vs les autres titres", len(diffs),
                               mean(diffs) if diffs else None, _t(diffs[::5]), "écart de rendement moyen"))
    # Catalyseurs passés : une seule prévision par (titre, événement), la plus proche de l'événement.
    latest: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r["EventDate"] and r["EventDate"] >= r["Date"]:
            k = (r["Ticker"], r["EventDate"])
            if k not in latest or r["Date"] > latest[k]["Date"]:
                latest[k] = r
    err_hist, err_impl, both = [], [], []
    for (tk, ev), r in latest.items():
        s = series.get(tk)
        if not s:
            continue
        i = bisect_left(s[0], date.fromisoformat(ev))
        if i == 0 or i + 1 >= len(s[0]):
            continue
        j = i + 1 if s[0][i] == date.fromisoformat(ev) else i
        real = abs(s[1][j] / s[1][i - 1] - 1)
        hm, im = _num(r["HistMove"]), _num(r["ImpliedMove"])
        if hm is not None:
            err_hist.append(abs(real - hm))
        if im is not None:
            err_impl.append(abs(real - im))
        if hm is not None and im is not None:
            both.append((hm, im, real))
    out["events"] = {"n": len(latest), "scored_hist": len(err_hist), "scored_implied": len(err_impl),
                     "mae_hist": median(err_hist) if err_hist else None,
                     "mae_implied": median(err_impl) if err_impl else None,
                     "underpriced": [(h, i, r) for h, i, r in both if h >= 1.25 * i],
                     "both": both}
    return out


def _fmt(sc: Score) -> str:
    if sc.value is None:
        return "—"
    return f"{sc.value:+.3f}" if "IC" in sc.detail else f"{sc.value:+.2%}"


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.1%}"


def render_text(s: dict) -> str:
    out = [f"JOURNAL DES PRÉVISIONS — {s['sessions']} séance(s) enregistrée(s)"
           + (f" du {s['first']} au {s['last']}" if s["first"] else ""), ""]
    if not s["sessions"]:
        return "\n".join(out + ["  Journal vide : il se remplit à chaque collecte « Données de marché réelles »."])
    for sc in s["scores"]:
        t = "" if sc.t is None else f", t {sc.t:+.1f}"
        out.append(f"  {sc.name:62} {_fmt(sc):>8} ({sc.n} notée(s){t}) — {sc.detail}")
    e = s["events"]
    out += ["", f"  Catalyseurs suivis : {e['n']} ; notés : historique {e['scored_hist']}, options {e['scored_implied']}",
            f"    erreur médiane |réel − attendu| : historique {_pct(e['mae_hist'])}, options {_pct(e['mae_implied'])}",
            f"    « sous-évalués par les options » notés : {len(e['underpriced'])}"]
    for h, i, r in e["underpriced"][:10]:
        out.append(f"      attendu {h:.1%} (historique) vs {i:.1%} (options) → réel {r:.1%}")
    out += ["", "  Les notes n'apparaissent qu'une fois l'horizon écoulé (5 ou 21 séances, ou l'événement passé).",
            "  Rien n'est réglé sur le journal : c'est une mesure hors échantillon de l'outil tel qu'il est."]
    return "\n".join(out)


def render_html(s: dict) -> str:
    from html import escape

    head = (f"<h2>Journal des prévisions</h2><p class='muted small'>{s['sessions']} séance(s) enregistrée(s)"
            + (f" du {escape(s['first'])} au {escape(s['last'])}" if s["first"] else "")
            + f" · {s['rows']:,} prévisions. Chaque jour, l'outil enregistre ses avis, le statut de la grille d'entrée "
              "et les mouvements attendus ; ils sont notés automatiquement une fois l'horizon écoulé. Rien n'est réglé "
              "sur ce journal : c'est la mesure hors échantillon de l'outil tel qu'il est.</p>")
    if not s["sessions"]:
        return head + "<p class='empty'>Journal vide : il se remplit à chaque collecte « Données de marché réelles ».</p>"

    def cls(sc: Score) -> str:
        if sc.value is None or sc.t is None:
            return "neu"
        return "pos" if sc.value > 0 and sc.t >= 2 else "neg" if sc.value < 0 and sc.t <= -2 else "neu"

    rows = "".join(
        f"<tr><td>{escape(sc.name)}</td><td class='num'><span class='badge {cls(sc)}'>{_fmt(sc)}</span></td>"
        f"<td class='num'>{'—' if sc.t is None else f'{sc.t:+.1f}'}</td><td class='num'>{sc.n}</td>"
        f"<td class='small muted'>{escape(sc.detail)}</td></tr>" for sc in s["scores"])
    e = s["events"]
    under = "".join(f"<li>attendu {h:.1%} d'après l'historique vs {i:.1%} d'après les options → réel <strong>{r:.1%}</strong></li>"
                    for h, i, r in e["underpriced"][:15])
    return head + f"""
<section class="card"><h3>Avis et grille d'entrée</h3>
<table class="signals"><tr><th>Prévision</th><th class="num">Résultat</th><th class="num">t</th><th class="num">Notées</th><th></th></tr>{rows}</table>
<p class="small muted">t : significativité sur des fenêtres disjointes ; |t| &gt; 2 est un indice, |t| &gt; 3 une preuve raisonnable.
Tant que peu de séances sont notées, les résultats sont surtout du bruit.</p></section>
<section class="card"><h3>Catalyseurs : l'historique ou les options voient-ils juste ?</h3>
<p>{e['n']} catalyseur(s) suivi(s) ; notés : historique {e['scored_hist']}, options {e['scored_implied']}.</p>
<p>Erreur médiane |mouvement réel − attendu| : <strong>historique {_pct(e['mae_hist'])}</strong> ·
<strong>options {_pct(e['mae_implied'])}</strong> (le plus bas prévoit le mieux l'ampleur).</p>
{f'<p>Cas « sous-évalués par les options » (historique ≥ 1,25 × options) :</p><ul class="small">{under}</ul>' if under else ''}
</section>"""
