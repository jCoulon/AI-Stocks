"""Écran Polymarket : quels portefeuilles ont réellement un avantage, où les contrats étaient-ils
sous-évalués, comment et quand les meilleurs investissent — et le suivi de leurs derniers ordres.

Chaque ordre est traité comme un pari tenu jusqu'à la résolution :
  achat de l'issue i au prix p  -> coût p,     gain 1 si i gagne ;
  vente de l'issue i au prix p  -> coût 1 − p, gain 1 si i perd (équivaut à acheter l'autre issue).
Rendement d'un portefeuille sur un marché = (gains − coûts) / coûts, pondéré par les montants.
L'avantage est jugé par marché (et non par ordre, les ordres d'un même marché étant liés) :
t = rendement moyen par marché / erreur type ; il faut au moins MIN_MARKETS marchés.

Test de persistance : les portefeuilles sont classés sur les marchés résolus pendant les deux
premiers tiers de la période, puis on mesure le rendement des meilleurs sur le dernier tiers.
Si les « meilleurs » ne battent pas la moyenne ensuite, leur classement tenait surtout à la
chance — et les copier ne sert à rien. Ce n'est pas un conseil d'investissement.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median, stdev
from typing import Iterable, Optional

from ..providers.polymarket import Market, Trade

MIN_MARKETS = 8
TOP_N = 20
PRICE_BUCKETS = [(0.0, 0.1), (0.1, 0.25), (0.25, 0.4), (0.4, 0.6), (0.6, 0.75), (0.75, 0.9), (0.9, 1.0)]
HORIZON_BUCKETS = [(0, 1 / 24, "< 1 h"), (1 / 24, 1, "1 h – 1 j"), (1, 7, "1 – 7 j"), (7, 30, "7 – 30 j"),
                   (30, 1e9, "> 30 j")]


LATE_HOURS = 6  # ordres passés plus de 6 h après la fin prévue : résultat en général déjà connu


def is_late(t: Trade, m: Market) -> bool:
    return bool(m.end) and t.ts > m.end.timestamp() + LATE_HOURS * 3600


def bet(t: Trade, m: Market) -> Optional[tuple[float, float, float]]:
    """(prix payé pour l'issue réellement achetée, mise en $, gain net en $) — None si inexploitable
    (marché non résolu, prix extrême, ou ordre passé une fois le résultat connu : ce n'est plus une
    prévision mais du « ramassage » quasi sans risque)."""
    if m.winner is None or not 0.005 < t.price < 0.995 or t.size <= 0 or is_late(t, m):
        return None
    if t.side == "BUY":
        cost, win = t.price, t.outcome_index == m.winner
    else:
        cost, win = 1 - t.price, t.outcome_index != m.winner
    stake = t.size * cost
    return cost, stake, t.size * (1.0 if win else 0.0) - stake


def _t(xs: list[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    s = stdev(xs)
    return mean(xs) / (s / math.sqrt(len(xs))) if s > 0 else None


def wallet_stats(trades: Iterable[Trade], markets: dict[str, Market]) -> dict[str, dict]:
    # wallet -> marché -> [mise, gain net, écart type du gain si les prix étaient justes]
    per = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
    names: dict[str, str] = {}
    n_orders: dict[str, int] = defaultdict(int)
    for t in trades:
        m = markets.get(t.condition_id)
        b = bet(t, m) if m else None
        if not b:
            continue
        acc = per[t.wallet][t.condition_id]
        acc[0] += b[1]
        acc[1] += b[2]
        # Si le prix c était la vraie probabilité, le gain d'une part serait X − c, X ~ Bernoulli(c) :
        # écart type sqrt(c(1−c)). Ordres d'un même marché supposés parfaitement liés (prudent).
        acc[2] += t.size * math.sqrt(b[0] * (1 - b[0]))
        n_orders[t.wallet] += 1
        if t.name:
            names[t.wallet] = t.name
    out = {}
    for w, by_market in per.items():
        rois = [pnl / stake for stake, pnl, _ in by_market.values() if stake > 0]
        stake = sum(v[0] for v in by_market.values())
        pnl = sum(v[1] for v in by_market.values())
        sd = math.sqrt(sum(v[2] ** 2 for v in by_market.values()))
        out[w] = {"wallet": w, "name": names.get(w, ""), "markets": len(rois), "orders": n_orders[w],
                  "stake": stake, "pnl": pnl, "roi": pnl / stake if stake else 0.0,
                  "mean_roi": mean(rois) if rois else 0.0, "z": pnl / sd if sd > 0 else None,
                  "win_rate": sum(r > 0 for r in rois) / len(rois) if rois else 0.0}
    return out


def rank_wallets(stats: dict[str, dict], min_markets: int = MIN_MARKETS) -> list[dict]:
    """Classement par z : gain réalisé rapporté à ce que le hasard produirait si les prix payés
    étaient les vraies probabilités. Un gros gain sur trois outsiders chanceux ou des centaines
    d'achats à 0,99 gagnés d'avance ne donnent qu'un z modeste ; seul un avantage régulier à des
    prix incertains donne un z élevé. Avec des dizaines de milliers de portefeuilles, il faut
    z > 4,5 environ pour que la chance devienne peu plausible."""
    ok = [s for s in stats.values() if s["markets"] >= min_markets and s["z"] is not None]
    return sorted(ok, key=lambda s: -s["z"])


def persistence(trades: list[Trade], markets: dict[str, Market], top_n: int = TOP_N) -> dict:
    ends = sorted(m.end for m in markets.values() if m.end)
    if len(ends) < 30:
        return {"ok": False, "reason": "trop peu de marchés résolus"}
    cut = ends[len(ends) * 2 // 3]
    a = {c: m for c, m in markets.items() if m.end and m.end < cut}
    b = {c: m for c, m in markets.items() if m.end and m.end >= cut}
    ranked = rank_wallets(wallet_stats([t for t in trades if t.condition_id in a], a))
    top = {s["wallet"] for s in ranked[:top_n]}
    later = wallet_stats([t for t in trades if t.condition_id in b], b)
    top_later = [later[w] for w in top if w in later]
    others = [s for w, s in later.items() if w not in top and s["markets"] >= 3]
    top_rois = [s["roi"] for s in top_later]
    other_rois = [s["roi"] for s in others]
    pooled = lambda ss: sum(s["pnl"] for s in ss) / sum(s["stake"] for s in ss) if ss and sum(s["stake"] for s in ss) else None  # noqa: E731
    diff_t = None
    if len(top_rois) >= 3 and len(other_rois) >= 3:
        se = math.sqrt(stdev(top_rois) ** 2 / len(top_rois) + stdev(other_rois) ** 2 / len(other_rois))
        diff_t = (mean(top_rois) - mean(other_rois)) / se if se else None
    return {"ok": True, "cut": cut.date().isoformat(), "ranked_on": len(a), "tested_on": len(b),
            "top_active_later": len(top_later), "top_roi": pooled(top_later), "others_roi": pooled(others),
            "top_mean_roi": mean(top_rois) if top_rois else None,
            "others_mean_roi": mean(other_rois) if other_rois else None, "diff_t": diff_t}


def calibration(trades: Iterable[Trade], markets: dict[str, Market]) -> list[dict]:
    """Par tranche de prix payé : fréquence réelle de gain vs prix. Fréquence > prix = issues
    sous-évaluées dans cette tranche (le biais « favori-outsider » des marchés de paris prédit
    plutôt l'inverse pour les outsiders : Thaler & Ziemba, 1988 ; Snowberg & Wolfers, 2010)."""
    acc = [[0.0, 0.0, 0.0, 0] for _ in PRICE_BUCKETS]  # mise, parts gagnantes, parts, ordres
    by_cat = defaultdict(lambda: [0.0, 0.0])
    for t in trades:
        m = markets.get(t.condition_id)
        b = bet(t, m) if m else None
        if not b:
            continue
        cost, stake, pnl = b
        k = next(i for i, (lo, hi) in enumerate(PRICE_BUCKETS) if lo <= cost < hi or (hi == 1.0 and cost >= lo))
        shares = stake / cost
        acc[k][0] += stake
        acc[k][1] += (pnl + stake)  # parts gagnantes (1 $ chacune)
        acc[k][2] += shares
        acc[k][3] += 1
        by_cat[m.category][0] += stake
        by_cat[m.category][1] += pnl
    rows = []
    for (lo, hi), (stake, won, shares, n) in zip(PRICE_BUCKETS, acc):
        if n:
            price = stake / shares
            freq = won / shares
            rows.append({"bucket": f"{lo:.0%}–{hi:.0%}", "orders": n, "stake": stake, "price": price,
                         "win_freq": freq, "edge": freq - price, "roi": won / stake - 1})
    return rows


def category_roi(trades: Iterable[Trade], markets: dict[str, Market]) -> list[dict]:
    acc = defaultdict(lambda: [0.0, 0.0, set()])
    for t in trades:
        m = markets.get(t.condition_id)
        b = bet(t, m) if m else None
        if b:
            acc[m.category][0] += b[1]
            acc[m.category][1] += b[2]
            acc[m.category][2].add(m.condition_id)
    return sorted(({"category": c, "stake": s, "roi": p / s if s else 0, "markets": len(ms)}
                   for c, (s, p, ms) in acc.items() if len(ms) >= 3), key=lambda r: -r["stake"])


def habits(trades: Iterable[Trade], markets: dict[str, Market], wallets: set[str]) -> dict:
    """Répartition des mises (en %) des portefeuilles choisis vs de tous : heure (UTC), jour,
    délai avant la fin du marché, prix payé, catégorie ; taille médiane des ordres."""
    groups = {"top": defaultdict(lambda: defaultdict(float)), "all": defaultdict(lambda: defaultdict(float))}
    sizes = {"top": [], "all": []}
    for t in trades:
        m = markets.get(t.condition_id)
        b = bet(t, m) if m else None
        if not b:
            continue
        cost, stake, _ = b
        when = datetime.fromtimestamp(t.ts, timezone.utc)
        days_left = (m.end - when).total_seconds() / 86400 if m.end else None
        keys = {"hour": f"{when.hour:02d}h", "weekday": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"][when.weekday()],
                "price": next(f"{lo:.0%}–{hi:.0%}" for lo, hi in PRICE_BUCKETS if lo <= cost < hi or (hi == 1.0 and cost >= lo)),
                "category": m.category}
        if days_left is not None:
            keys["horizon"] = next((lab for lo, hi, lab in HORIZON_BUCKETS if lo <= days_left < hi), "après la fin")
        for g in ("all", "top") if t.wallet in wallets else ("all",):
            for k, v in keys.items():
                groups[g][k][v] += stake
            sizes[g].append(stake)
    out = {}
    for g, dims in groups.items():
        out[g] = {k: {v: s / sum(d.values()) for v, s in sorted(d.items())} for k, d in dims.items()}
        out[g]["median_stake"] = median(sizes[g]) if sizes[g] else None
    return out


def monitor_rows(recent: list[Trade], open_markets: dict[str, Market], wallets: dict[str, dict],
                 now: datetime, days: int = 7) -> list[dict]:
    """Derniers ordres des portefeuilles suivis sur des marchés encore ouverts, avec le prix actuel."""
    rows = []
    for t in recent:
        m = open_markets.get(t.condition_id)
        age = (now - datetime.fromtimestamp(t.ts, timezone.utc)).total_seconds() / 86400
        if not m or m.winner is not None or age > days:
            continue
        idx = t.outcome_index if t.side == "BUY" else 1 - t.outcome_index
        paid = t.price if t.side == "BUY" else 1 - t.price
        now_price = m.prices[idx] if len(m.prices) == 2 else None
        rows.append({"wallet": t.wallet, "name": wallets.get(t.wallet, {}).get("name", ""), "ts": t.ts,
                     "question": m.question or t.title, "slug": m.slug, "outcome": m.outcomes[idx],
                     "paid": paid, "now": now_price, "sure": paid >= 0.97, "stake": t.size * paid, "end": m.end.isoformat() if m.end else None,
                     "category": m.category})
    return sorted(rows, key=lambda r: -r["ts"])


def build_report(markets: dict[str, Market], trades: list[Trade], now: datetime) -> dict:
    stats = wallet_stats(trades, markets)
    ranked = rank_wallets(stats)
    top = ranked[:TOP_N]
    return {"generated": now.isoformat(), "markets": len(markets), "orders": len(trades), "wallets": len(stats),
            "period": [min(m.end for m in markets.values() if m.end).date().isoformat(),
                       max(m.end for m in markets.values() if m.end).date().isoformat()] if markets else None,
            "top": top, "persistence": persistence(trades, markets), "calibration": calibration(trades, markets),
            "categories": category_roi(trades, markets),
            "habits": habits(trades, markets, {s["wallet"] for s in top}), "monitor": [], "monitor_at": None}


# ------------------------------------------------------------------------------ rendu
def _pct(x, signed=True):
    return "—" if x is None else (f"{x:+.1%}" if signed else f"{x:.0%}")


def _price(x) -> str:
    return "—" if x is None else f"{x:.2f}"


def verdict(p: dict) -> str:
    if not p.get("ok"):
        return "Test de persistance impossible (" + p.get("reason", "données insuffisantes") + ")."
    t = p.get("diff_t")
    if t is not None and t >= 2 and (p.get("top_mean_roi") or 0) > (p.get("others_mean_roi") or 0):
        return ("Les meilleurs portefeuilles de la 1re période ont continué à faire mieux ensuite "
                f"(t {t:+.1f}) : leur avantage semble réel, pas seulement de la chance.")
    return ("Les meilleurs portefeuilles de la 1re période n'ont PAS fait nettement mieux ensuite "
            f"(t {'—' if t is None else f'{t:+.1f}'}) : leur classement tient en bonne partie à la chance ; "
            "les copier n'a pas d'intérêt démontré.")


def render_text(r: dict) -> str:
    p = r["persistence"]
    out = [f"POLYMARKET — PORTEFEUILLES ET MARCHÉS SOUS-ÉVALUÉS ({r['markets']} marchés résolus, "
           f"{r['orders']} ordres, {r['wallets']} portefeuilles ; {r['period'][0]} → {r['period'][1]})" if r.get("period")
           else "POLYMARKET — aucune donnée", "Données publiques, analyse descriptive : pas un conseil.", "",
           "  Persistance : " + verdict(p)]
    if p.get("ok"):
        out.append(f"    classés sur {p['ranked_on']} marchés (jusqu'au {p['cut']}), testés sur {p['tested_on']} : "
                   f"meilleurs {_pct(p['top_mean_roi'])} / autres {_pct(p['others_mean_roi'])} (rendement moyen)")
    out += ["", f"  {'Portefeuille':44} {'Marchés':>7} {'Mise':>10} {'Gain':>10} {'Rend.':>7} {'z':>5} {'Réussite':>8}"]
    for s in r["top"]:
        out.append(f"  {s['wallet'][:42]:42}   {s['markets']:7d} {s['stake']:10,.0f} {s['pnl']:+10,.0f} "
                   f"{_pct(s['roi']):>7} {s['z']:5.1f} {_pct(s['win_rate'], False):>8}")
    out += ["", "  Calibration (prix payé → fréquence réelle de gain) :"]
    for c in r["calibration"]:
        out.append(f"    {c['bucket']:9} {c['orders']:7d} ordres  prix moyen {c['price']:.2f}  gagne {c['win_freq']:.2f}  "
                   f"écart {c['edge']:+.3f}  rendement {_pct(c['roi'])}")
    h = r["habits"].get("top") or {}
    if h:
        out += ["", "  Habitudes des meilleurs (part des mises ; entre parenthèses : tous les portefeuilles) :"]
        base = r["habits"]["all"]
        for dim, lab in (("horizon", "délai avant la fin"), ("price", "prix payé"), ("category", "catégorie")):
            items = sorted(h.get(dim, {}).items(), key=lambda kv: -kv[1])[:5]
            out.append(f"    {lab:20} " + ", ".join(f"{k} {v:.0%} ({base.get(dim, {}).get(k, 0):.0%})" for k, v in items))
        hours = sorted(h.get("hour", {}).items(), key=lambda kv: -kv[1])[:4]
        out.append("    heures (UTC)         " + ", ".join(f"{k} {v:.0%}" for k, v in hours))
    if r["monitor"]:
        out += ["", f"  Derniers ordres des portefeuilles suivis (marchés ouverts, relevé {r['monitor_at']}) :"]
        for m in r["monitor"][:25]:
            when = datetime.fromtimestamp(m["ts"], timezone.utc).strftime("%d/%m %H:%M")
            out.append(f"    {when} {m['wallet'][:10]}… {m['outcome']:>4} à {m['paid']:.2f} (actuel "
                       f"{_price(m['now'])}) {m['stake']:8,.0f} $  {m['question'][:70]}")
    return "\n".join(out)


def render_html(r: Optional[dict]) -> str:
    from html import escape

    if not r or not r.get("period"):
        return ('<h2>Polymarket</h2><p class="empty">Aucune donnée : lancez le workflow « Polymarket » '
                '(données publiques téléchargées par GitHub Actions).</p>')
    p = r["persistence"]

    def signed(x):
        return "—" if x is None else f'<span class="{"pos" if x >= 0 else "neg"}">{x:+.1%}</span>'

    top = "".join(
        f"<tr><td><a href='https://polymarket.com/profile/{escape(s['wallet'])}' target='_blank' rel='noopener'>"
        f"<code>{escape(s['wallet'][:10])}…{escape(s['wallet'][-4:])}</code></a>"
        f"<div class='muted small'>{escape(s['name'][:30])}</div></td>"
        f"<td class='num'>{s['markets']}</td><td class='num'>{s['stake']:,.0f} $</td>"
        f"<td class='num'>{signed(s['pnl'] / s['stake'] if s['stake'] else None)}</td>"
        f"<td class='num'>{s['pnl']:+,.0f} $</td><td class='num'><strong>{s['z']:.1f}</strong></td>"
        f"<td class='num'>{s['win_rate']:.0%}</td></tr>" for s in r["top"])
    cal = "".join(
        f"<tr><td>{escape(c['bucket'])}</td><td class='num'>{c['orders']:,}</td><td class='num'>{c['price']:.2f}</td>"
        f"<td class='num'>{c['win_freq']:.2f}</td><td class='num'>{signed(c['edge'])}</td>"
        f"<td class='num'>{signed(c['roi'])}</td></tr>" for c in r["calibration"])
    cats = "".join(f"<tr><td>{escape(c['category'])}</td><td class='num'>{c['markets']}</td>"
                   f"<td class='num'>{c['stake']:,.0f} $</td><td class='num'>{signed(c['roi'])}</td></tr>"
                   for c in r["categories"][:12])
    h, base = r["habits"].get("top") or {}, r["habits"].get("all") or {}

    def bars(dim, order=None, limit=None):
        items = list(h.get(dim, {}).items())
        items = sorted(items, key=(lambda kv: order.index(kv[0]) if kv[0] in order else 99) if order else (lambda kv: -kv[1]))
        rows = []
        for k, v in items[:limit]:
            b = base.get(dim, {}).get(k, 0)
            rows.append(f"<tr><td>{escape(k)}</td><td><div class='bar'><span style='width:{v * 100:.0f}%'></span></div></td>"
                        f"<td class='num'>{v:.0%}</td><td class='num muted'>{b:.0%}</td></tr>")
        return "<table class='signals small'><tr><th></th><th>Meilleurs</th><th class='num'></th><th class='num'>Tous</th></tr>" + "".join(rows) + "</table>"

    horizons = [lab for _, _, lab in HORIZON_BUCKETS] + ["après la fin"]
    prices = [f"{lo:.0%}–{hi:.0%}" for lo, hi in PRICE_BUCKETS]
    mon = "".join(
        f"<tr><td class='small'>{datetime.fromtimestamp(m['ts'], timezone.utc):%d/%m %H:%M}</td>"
        f"<td><code>{escape(m['wallet'][:8])}…</code></td><td>{escape(m['question'][:90])}"
        f"<div class='muted small'>{escape(m['category'])}{' · fin ' + escape(m['end'][:10]) if m['end'] else ''}</div></td>"
        f"<td>{escape(m['outcome'])}{' <span class=badge>quasi certain</span>' if m.get('sure') else ''}</td><td class='num'>{m['paid']:.2f}</td>"
        f"<td class='num'>{_price(m['now'])}</td>"
        f"<td class='num'>{m['stake']:,.0f} $</td></tr>" for m in r["monitor"][:40])
    monitor = (f"<section class='card'><h3>Suivi : derniers ordres des portefeuilles suivis (marchés ouverts)</h3>"
               f"<p class='muted small'>Relevé du {escape(r['monitor_at'] or '')} (UTC). Un prix actuel déjà supérieur au prix "
               f"payé signifie que l'éventuelle sous-évaluation a déjà été corrigée.</p><div class='scroll'>"
               f"<table class='signals'><tr><th>Quand (UTC)</th><th>Portefeuille</th><th>Marché</th><th>Issue</th>"
               f"<th class='num'>Payé</th><th class='num'>Actuel</th><th class='num'>Montant</th></tr>{mon}</table></div></section>"
               if r["monitor"] else "<section class='card'><p class='muted'>Suivi : pas encore de relevé des derniers ordres.</p></section>")
    pers = ""
    if p.get("ok"):
        pers = (f"<p class='small'>Classés sur {p['ranked_on']} marchés résolus jusqu'au {escape(p['cut'])}, puis testés sur "
                f"les {p['tested_on']} suivants : rendement moyen des 20 meilleurs {signed(p['top_mean_roi'])}, des autres "
                f"{signed(p['others_mean_roi'])} ({p['top_active_later']} des 20 encore actifs).</p>")
    ok = p.get("ok") and (p.get("diff_t") or 0) >= 2
    return f"""
<h2>Polymarket — portefeuilles et marchés sous-évalués</h2>
<p class="muted small">{r['markets']} marchés binaires résolus ({escape(r['period'][0])} → {escape(r['period'][1])}),
{r['orders']:,} ordres « preneurs », {r['wallets']:,} portefeuilles · données publiques Polymarket · analyse descriptive,
pas un conseil. L'accès à Polymarket est bloqué en France (ANJ).</p>
<section class="card"><h3>Avantage réel ou chance ?</h3>
<p><span class="badge {'pos' if ok else 'neu'}">{'persistant' if ok else 'non démontré'}</span> {escape(verdict(p))}</p>{pers}</section>
<section class="card"><h3>Meilleurs portefeuilles (classés par z, au moins {MIN_MARKETS} marchés)</h3>
<p class="muted small">Chaque ordre est compté comme un pari tenu jusqu'à la résolution ; les ordres passés plus de
{LATE_HOURS} h après la fin (résultat connu) sont exclus. z = gain rapporté à ce que le hasard donnerait si les prix payés
étaient justes : acheter à 0,99 un résultat déjà connu ne rapporte presque rien en z. Parmi {r['wallets']:,} portefeuilles,
quelques z proches de 4 apparaissent par pur hasard : seul z &gt; 4,5 environ commence à être significatif.</p>
<div class="scroll"><table class="signals"><tr><th>Portefeuille</th><th class="num">Marchés</th><th class="num">Mises</th>
<th class="num">Rendement</th><th class="num">Gain</th><th class="num">z</th><th class="num">Marchés gagnants</th></tr>{top}</table></div></section>
{monitor}
<section class="card"><h3>Où les contrats étaient-ils sous-évalués ?</h3>
<p class="muted small">Par tranche de prix payé : fréquence réelle de gain. Une fréquence supérieure au prix signale des contrats
sous-évalués dans cette tranche (en moyenne, sur la période).</p>
<table class="signals"><tr><th>Prix payé</th><th class="num">Ordres</th><th class="num">Prix moyen</th><th class="num">Gagne</th>
<th class="num">Écart</th><th class="num">Rendement</th></tr>{cal}</table>
<h3>Par catégorie</h3><table class="signals"><tr><th>Catégorie</th><th class="num">Marchés</th><th class="num">Mises</th>
<th class="num">Rendement moyen des preneurs</th></tr>{cats}</table></section>
<section class="card"><h3>Comment et quand investissent les meilleurs</h3>
<p class="muted small">Part de leurs mises (colonne « Tous » : l'ensemble des portefeuilles). Taille médiane d'un ordre :
{(h.get('median_stake') or 0):,.0f} $ (tous : {(base.get('median_stake') or 0):,.0f} $).</p>
<div class="grid2"><div><h4>Délai avant la fin du marché</h4>{bars('horizon', horizons)}</div>
<div><h4>Prix payé</h4>{bars('price', prices)}</div>
<div><h4>Heure (UTC)</h4>{bars('hour', limit=24, order=[f'{i:02d}h' for i in range(24)])}</div>
<div><h4>Catégorie</h4>{bars('category', limit=8)}</div></div></section>
<section class="card small"><p>⚠ Copier un portefeuille arrive toujours après lui : le prix a souvent déjà bougé. Les
classements publics par gains mélangent talent et chance ; seul le test de persistance ci-dessus dit si l'avantage a tenu.</p>
<p>⚠ Ordres « preneurs » uniquement, jusqu'à 2 000 par marché (les plus récents) : les tout premiers ordres des marchés très
actifs peuvent manquer. Les portefeuilles sont des adresses publiques pseudonymes.</p></section>"""
