"""Collecte des messages StockTwits par action (réseau social dédié à la bourse).

L'API publique (sans clé) renvoie les 30 derniers messages d'un symbole, avec l'auteur, sa
date d'inscription, ses abonnés, les « likes » et, souvent, une étiquette « Bullish » /
« Bearish » choisie par l'auteur lui-même. Lancée toutes les 3 heures par le workflow
« News RSS et FinBERT », la collecte accumule un historique à partir de maintenant dans
<dossier>/social/stocktwits/<TICKER>.csv (dédoublonné par identifiant de message).
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

from ..models import SocialPost
from typing import Optional

from .realnews import NEW_YORK, http_get, title_key

STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                                 "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                   "Accept": "application/json"}
FIELDS = ["Id", "Posted", "Author", "Joined", "Followers", "Likes", "Sentiment", "Text"]
TONES = {"Bullish": 1.0, "Bearish": -1.0}


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def parse_stream(body: str) -> list[dict]:
    """Messages d'une réponse StockTwits, horodatés à New York ; ValueError si l'API refuse."""
    payload = json.loads(body)
    status = payload.get("response", {}).get("status", 200)
    if status != 200:
        raise ValueError(f"StockTwits : statut {status} {payload.get('errors', '')}")
    rows = []
    for m in payload.get("messages", []):
        user = m.get("user") or {}
        sentiment = ((m.get("entities") or {}).get("sentiment") or {}).get("basic") or ""
        text = " ".join((m.get("body") or "").split())
        if not text or "id" not in m or "created_at" not in m:
            continue
        rows.append({
            "Id": str(m["id"]),
            "Posted": _utc(m["created_at"]).astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M:%S"),
            "Author": user.get("username", ""),
            "Joined": (user.get("join_date") or "")[:10],
            "Followers": str(user.get("followers", 0)),
            "Likes": str((m.get("likes") or {}).get("total", 0)),
            "Sentiment": sentiment,
            "Text": text,
        })
    return rows


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["Posted"], r["Id"])))


def collect_stocktwits(out_dir: Path, tickers: list[str], log=print, fetch=None) -> list[str]:
    folder = out_dir / "social" / "stocktwits"
    fetch = fetch or (lambda url: http_get(url, headers=BROWSER_HEADERS, retries=1, timeout=20))
    errors = []
    for ticker in tickers:
        try:
            new = parse_stream(fetch(STOCKTWITS_URL.format(symbol=ticker.replace(".", "-"))))
        except Exception as e:  # noqa: BLE001 — un titre en échec n'empêche pas les autres
            errors.append(f"StockTwits {ticker} : {type(e).__name__}: {str(e)[:120]}")
            continue
        path = folder / f"{ticker}.csv"
        rows = {r["Id"]: r for r in read_rows(path)}
        before = len(rows)
        rows.update({r["Id"]: r for r in new})
        write_rows(path, list(rows.values()))
        log(f"  StockTwits {ticker:6} {len(new):3} messages lus, {len(rows) - before:3} nouveaux, {len(rows)} au total")
    return errors


def load_posts(path: Path, ticker: str, platform: str = "StockTwits", unknown_age: int = 0,
               tones: Optional[dict[str, float]] = None) -> list[SocialPost]:
    """Messages enregistrés -> SocialPost (ancienneté du compte au moment du message).

    `unknown_age` : ancienneté retenue quand la date d'inscription est inconnue (0 = traité
    comme un compte récent). `tones` : ton FinBERT par texte, utilisé sans étiquette d'auteur."""
    posts = []
    for r in read_rows(path):
        posted = datetime.fromisoformat(r["Posted"])
        try:
            age = (posted.date() - date.fromisoformat(r["Joined"])).days
        except ValueError:
            age = unknown_age
        tone = TONES.get(r["Sentiment"])
        if tone is None and tones:
            tone = tones.get(title_key(r["Text"]))
        posts.append(SocialPost(ticker, posted, platform, r["Author"], max(0, age),
                                int(r["Likes"] or 0), r["Text"], tone))
    return sorted(posts, key=lambda p: p.posted)
