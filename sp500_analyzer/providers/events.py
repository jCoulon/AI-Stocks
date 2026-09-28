"""Calendrier des catalyseurs datés : publications de résultats (API publique Nasdaq), fins de
lock-up estimées après une introduction en bourse, et calendrier saisi à la main (Fed...).

Fichiers :
  <dossier>/events/<TICKER>.json   prochaine publication + dates des publications passées
  <dossier>/events/calendar.csv    événements saisis à la main : Date,Ticker,Event,Note
                                   (Ticker = MARCHE pour un événement de marché ; une société
                                   liée comme OPENAI touche les titres qui lui sont liés)
La prochaine date de résultats est une photographie du jour du téléchargement ; les dates
passées (tableau des « surprises » de BPA) permettent de mesurer la réaction habituelle du titre.
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..universe import LINKS
from .fundamentals import NASDAQ_API, NASDAQ_HEADERS

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], 1)}
LOCKUP_DAYS = 180  # durée usuelle du lock-up d'une introduction en bourse américaine


@dataclass(frozen=True)
class Event:
    ticker: str          # MARCHE pour un événement de marché
    day: date
    kind: str            # "resultats", "lockup", "marche", "autre"
    label: str
    confirmed: bool = True
    timing: str = ""     # "après clôture", "avant ouverture" ou ""
    note: str = ""


def _parse_us_date(text: str) -> Optional[date]:
    """« Nov 19, 2025 », « 11/19/2025 » ou « 2025-11-19 » -> date."""
    if m := re.search(r"\b([A-Z][a-z]{2})[a-z]*\.? (\d{1,2}), (\d{4})", text or ""):
        month = MONTHS.get(m.group(1).lower())
        if month:
            return date(int(m.group(3)), month, int(m.group(2)))
    if m := re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text or ""):
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text or ""):
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def parse_earnings_date(payload: dict) -> Optional[dict]:
    """Prochaine publication d'après /analyst/<sym>/earnings-date : date, estimée ou confirmée,
    moment de la publication."""
    data = payload.get("data") or {}
    announcement, text = data.get("announcement") or "", data.get("reportText") or ""
    day = _parse_us_date(announcement) or _parse_us_date(text)
    if day is None:
        return None
    low = text.lower()
    timing = "après clôture" if "after market close" in low else "avant ouverture" if "before market open" in low else ""
    return {"date": day.isoformat(), "estimated": "*" in announcement or "estimated" in low, "timing": timing}


def parse_surprise_dates(payload: dict) -> list[str]:
    """Dates des publications passées d'après /company/<sym>/earnings-surprise."""
    rows = (((payload.get("data") or {}).get("earningsSurpriseTable") or {}).get("rows")) or []
    days = {_parse_us_date(r.get("dateReported") or "") for r in rows}
    return sorted(d.isoformat() for d in days if d)


def nasdaq_events(ticker: str, get: Callable[[str], str]) -> dict:
    sym = urllib.parse.quote(ticker.lower())
    errors = []
    out: dict = {"next_earnings": None, "past_earnings": []}
    for key, url, parse in (("next_earnings", f"{NASDAQ_API}/analyst/{sym}/earnings-date", parse_earnings_date),
                            ("past_earnings", f"{NASDAQ_API}/company/{sym}/earnings-surprise", parse_surprise_dates)):
        try:
            out[key] = parse(json.loads(get(url)))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    if len(errors) == 2:
        raise errors[0]
    return out


def download_events(out_dir: Path, tickers: list[str], pause: float = 0.8, log=print, get=None,
                    today: Optional[date] = None) -> list[str]:
    folder = out_dir / "events"
    folder.mkdir(parents=True, exist_ok=True)
    if get is None:
        opener = urllib.request.build_opener()
        opener.addheaders = list(NASDAQ_HEADERS.items())
        get = lambda url: opener.open(url, timeout=30).read().decode("utf-8", "replace")  # noqa: E731
    errors, failures = [], 0
    for ticker in tickers:
        path = folder / f"{ticker}.json"
        try:
            data = nasdaq_events(ticker, get)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Calendrier {ticker} (Nasdaq) : {type(e).__name__}: {str(e)[:120]}")
            failures += 1
            if failures == 3 and failures == len(errors):
                errors.append("Calendrier : Nasdaq refuse les requêtes — arrêt")
                return errors
            continue
        # On garde les publications passées déjà connues (le tableau Nasdaq n'en montre que 4).
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data["past_earnings"] = sorted(set(old.get("past_earnings", [])) | set(data["past_earnings"]))
        data = {"ticker": ticker, "fetched": (today or date.today()).isoformat(), "source": "Nasdaq", **data}
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        log(f"  calendrier {ticker:6} prochains résultats {data['next_earnings']}, "
            f"{len(data['past_earnings'])} publication(s) passée(s)")
        time.sleep(pause)
    return errors


def load_events(root: Path, ticker: str) -> Optional[dict]:
    path = root / "events" / f"{ticker}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_calendar(root: Path) -> list[Event]:
    """Événements saisis à la main (événements de marché, dates annoncées par les sociétés)."""
    path = root / "events" / "calendar.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [Event(r["Ticker"].strip().upper(), date.fromisoformat(r["Date"].strip()),
                      "marche" if r["Ticker"].strip().upper() == "MARCHE" else "autre", r["Event"].strip(),
                      note=(r.get("Note") or "").strip())
                for r in csv.DictReader(line for line in f if not line.startswith("#")) if r.get("Date")]


def ticker_events(root: Path, ticker: str, first_bar: Optional[date], history_start: Optional[date],
                  as_of: date) -> list[Event]:
    """Événements datés d'un titre postérieurs à as_of.

    Publications passées postérieures à as_of : utiles pour revoir l'écran à une date antérieure
    (ces dates étaient en général annoncées quelques semaines à l'avance)."""
    out: list[Event] = []
    data = load_events(root, ticker) or {}
    seen: set[date] = set()
    for d in data.get("past_earnings", []):
        day = date.fromisoformat(d)
        if day > as_of:
            seen.add(day)
            out.append(Event(ticker, day, "resultats", "Résultats trimestriels"))
    nxt = data.get("next_earnings")
    if nxt:
        day = date.fromisoformat(nxt["date"])
        if day > as_of and all(abs((day - s).days) > 20 for s in seen):
            out.append(Event(ticker, day, "resultats", "Résultats trimestriels", not nxt.get("estimated"),
                             nxt.get("timing", ""), "date estimée par Nasdaq" if nxt.get("estimated") else ""))
    # Introduction récente : le premier cours est nettement postérieur au début de l'historique.
    if first_bar and history_start and first_bar > history_start + timedelta(days=30):
        day = first_bar + timedelta(days=LOCKUP_DAYS)
        if day > as_of:
            out.append(Event(ticker, day, "lockup", "Fin du lock-up (estimée)", False, "",
                             f"introduction le {first_bar:%d/%m/%Y} + {LOCKUP_DAYS} j ; la date exacte figure dans "
                             "le prospectus (elle peut être avancée, p. ex. après une publication de résultats)"))
    calendar = [e for e in load_calendar(root) if e.day > as_of]
    out += [e for e in calendar if e.ticker == ticker]
    # Événements des sociétés liées (universe.LINKS), p. ex. une annonce d'OpenAI pour Cerebras.
    for link in LINKS.get(ticker, []):
        out += [Event(ticker, e.day, "lie", f"[{link.name}] {e.label}", note="; ".join(
                    x for x in (e.note, f"lien : {link.relation} (poids {link.weight:.0%})") if x))
                for e in calendar if e.ticker == link.entity]
    return sorted(out, key=lambda e: e.day)


def market_events(root: Path, as_of: date, horizon: int) -> list[Event]:
    return [e for e in load_calendar(root) if e.ticker == "MARCHE" and as_of < e.day <= as_of + timedelta(days=horizon)]
