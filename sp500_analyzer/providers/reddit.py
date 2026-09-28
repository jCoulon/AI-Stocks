"""Collecte des messages Reddit par action via les flux RSS publics de recherche (sans clé).

Flux : https://www.reddit.com/r/<subs>/search.rss?q=<requête>&restrict_sr=on&sort=new
(r/wallstreetbets, r/stocks, r/investing, r/StockMarket). Flux destiné aux lecteurs RSS, pas
une API : rythme modéré, et Reddit peut refuser certains serveurs (l'échec est alors
sans conséquence). Les flux ne donnent ni likes ni date d'inscription des auteurs : la
détection des comptes récents ne s'applique pas à Reddit, et le ton vient de FinBERT.
Fichiers : <dossier>/social/reddit/<TICKER>.csv (même format que StockTwits).
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from ..universe import UNIVERSES
from .realnews import NEW_YORK, http_get
from .stocktwits import read_rows, write_rows

SUBREDDITS = "wallstreetbets+stocks+investing+StockMarket"
REDDIT_RSS = "https://www.reddit.com/r/{subs}/search.rss?q={query}&restrict_sr=on&sort=new&t=week&limit=100"
ATOM = "{http://www.w3.org/2005/Atom}"
HEADERS = {"User-Agent": "AI-Stocks/1.0 (research; RSS reader)"}
REDDIT_PAUSE = 4.0
# Symboles trop courts ou ambigus pour être cherchés seuls : on cherche le nom de l'entreprise.
AMBIGUOUS = {"V", "BA", "KO", "GS", "HD", "PG", "CAT", "DIS", "AMT", "NEE", "PFE", "JNJ", "WMT", "UNH", "LLY", "XOM",
             "CVX", "JPM", "BAC", "ARM", "MU", "AI", "PATH", "VRT"}
EXTRA_NAMES = {"IREN": "Iris Energy"}
_TAGS = re.compile(r"<[^>]+>")


def reddit_query(ticker: str) -> str:
    names = {s.ticker: s.name for s in UNIVERSES["tout"]} | EXTRA_NAMES
    name = names.get(ticker, ticker)
    return f'"{name}"' if ticker in AMBIGUOUS else f'{ticker} OR "{name}"'


def _text(entry) -> str:
    title = (entry.findtext(f"{ATOM}title") or "").strip()
    body = _TAGS.sub(" ", html.unescape(entry.findtext(f"{ATOM}content") or ""))
    body = " ".join(body.replace("submitted by", " ").split())
    body = re.sub(r"/u/\S+|\[link\]|\[comments\]", "", body).strip()
    return (title + (" — " + body[:280] if body and body != title else "")).strip()


def parse_reddit_atom(body: str) -> list[dict]:
    """Messages d'un flux Atom Reddit (horodatés à New York), au format des fichiers sociaux."""
    root = ET.fromstring(body.strip().encode("utf-8"))
    if root.tag != f"{ATOM}feed":
        raise ValueError("Reddit : réponse inattendue (page de blocage ?)")
    rows = []
    for e in root.iter(f"{ATOM}entry"):
        when = e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")
        text = _text(e)
        if not when or len(text) < 10:
            continue
        cat = e.find(f"{ATOM}category")
        rows.append({
            "Id": (e.findtext(f"{ATOM}id") or "").strip(),
            "Posted": datetime.fromisoformat(when).astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M:%S"),
            "Author": (e.findtext(f"{ATOM}author/{ATOM}name") or "").removeprefix("/u/"),
            "Joined": "", "Followers": "", "Likes": "0",
            "Sentiment": "",  # pas d'étiquette : ton FinBERT
            "Text": (f"[r/{cat.get('term')}] " if cat is not None else "") + text,
        })
    return rows


def collect_reddit(out_dir: Path, tickers: list[str], pause: float = REDDIT_PAUSE, log=print,
                   fetch=None, sleep=time.sleep) -> list[str]:
    folder = out_dir / "social" / "reddit"
    fetch = fetch or (lambda url: http_get(url, headers=HEADERS, retries=1, timeout=20))
    errors = []
    for i, ticker in enumerate(tickers):
        url = REDDIT_RSS.format(subs=SUBREDDITS, query=urllib.parse.quote(reddit_query(ticker)))
        try:
            new = parse_reddit_atom(fetch(url))
        except Exception as e:  # noqa: BLE001 — Reddit peut refuser les serveurs de GitHub
            errors.append(f"Reddit {ticker} : {type(e).__name__}: {str(e)[:120]}")
            if i == 1 and len(errors) == 2:  # deux refus d'emblée : source bloquée, inutile d'insister
                errors.append("Reddit : accès refusé depuis ce serveur — collecte interrompue")
                return errors
        else:
            path = folder / f"{ticker}.csv"
            rows = {r["Id"]: r for r in read_rows(path)}
            before = len(rows)
            rows.update({r["Id"]: r for r in new if r["Id"]})
            write_rows(path, list(rows.values()))
            log(f"  Reddit {ticker:6} {len(new):3} messages lus, {len(rows) - before:3} nouveaux, {len(rows)} au total")
        sleep(pause)
    return errors
