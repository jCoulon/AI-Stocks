"""Téléchargement de vraies news, de dépôts réglementaires et de séries macro (sources gratuites).

- News : GDELT DOC 2.0 (articles de presse du monde entier, sans clé). L'API ne remonte que
  ~3 mois en arrière ; seuls les articles en anglais de sources connues sont conservés
  (liste NEWS_DOMAINS), les reprises d'un même titre sont dédoublonnées.
- Dépôts SEC : EDGAR (8-K, 10-Q, 10-K, 6-K...), historique complet, horodaté à la seconde.
  Faits officiels sans « ton » : ils expliquent les mouvements de prix mais n'entrent pas
  dans le calcul du sentiment (voir universe.EVENT_SOURCES).
- Macro : FRED (Réserve fédérale de St. Louis), sans clé. Les séries mensuelles sont datées
  de leur date de publication approximative (prudente), pas de la période mesurée.

Fichiers écrits (lus par RealDataProvider) :
  <dossier>/news/<TICKER>.csv et news/MARCHE.csv  Published,Source,Domain,Title,Url
  <dossier>/sec/<TICKER>.csv                      Published,Form,Items,Title,Url
  <dossier>/macro/<clé>.csv                        Date,Value
"""

from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
MARKET = "MARCHE"  # fichier des news de marché (ticker None)
SEC_SOURCE = "SEC EDGAR"

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_DAYS = 88  # l'API DOC ne couvre que les 3 derniers mois
GDELT_PAUSE = 8.0    # GDELT demande au plus une requête toutes les 5 s (IP de GitHub partagées : marge)
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"

# Domaine -> nom de source (fiabilité définie dans universe.SOURCE_RELIABILITY).
NEWS_DOMAINS: dict[str, str] = {
    "reuters.com": "Reuters", "bloomberg.com": "Bloomberg", "wsj.com": "WSJ", "ft.com": "Financial Times",
    "cnbc.com": "CNBC", "marketwatch.com": "MarketWatch", "barrons.com": "Barron's",
    "apnews.com": "Associated Press", "nytimes.com": "New York Times", "economist.com": "The Economist",
    "washingtonpost.com": "Washington Post", "bbc.com": "BBC", "bbc.co.uk": "BBC",
    "theguardian.com": "The Guardian", "axios.com": "Axios", "cnn.com": "CNN", "latimes.com": "Los Angeles Times",
    "fortune.com": "Fortune", "forbes.com": "Forbes", "businessinsider.com": "Business Insider",
    "yahoo.com": "Yahoo Finance", "morningstar.com": "Morningstar", "investors.com": "Investor's Business Daily",
    "foxbusiness.com": "Fox Business", "thestreet.com": "TheStreet", "nasdaq.com": "Nasdaq",
    "seekingalpha.com": "Seeking Alpha", "benzinga.com": "Benzinga", "fool.com": "The Motley Fool",
    "zacks.com": "Zacks", "investing.com": "Investing.com", "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge", "statnews.com": "STAT", "fiercepharma.com": "FiercePharma",
    "businesswire.com": "Business Wire", "prnewswire.com": "PR Newswire", "globenewswire.com": "GlobeNewswire",
}

# Requêtes GDELT (texte intégral des articles). Noms d'entreprise précis pour limiter les
# homonymes (« Apple » le fruit, « Visa » le document de voyage...).
GDELT_QUERIES: dict[str, str] = {
    "AAPL": '("Apple Inc" OR "Apple shares" OR "Apple stock" OR "Tim Cook")',
    "MSFT": '"Microsoft"',
    "NVDA": '"Nvidia"',
    "AVGO": '"Broadcom"',
    "AMD": '("Advanced Micro Devices" OR "AMD shares" OR "AMD stock" OR "Lisa Su")',
    "INTC": '("Intel Corp" OR "Intel shares" OR "Intel stock" OR "Intel chips" OR "Intel CEO")',
    "GOOGL": '("Alphabet Inc" OR "Google parent" OR "Alphabet shares" OR "Sundar Pichai")',
    "META": '("Meta Platforms" OR "Mark Zuckerberg" OR "Meta shares" OR "Meta stock")',
    "NFLX": '"Netflix"',
    "DIS": '("Walt Disney" OR "Disney shares" OR "Disney stock" OR "Disney CEO")',
    "AMZN": '("Amazon.com" OR "Amazon shares" OR "Amazon stock" OR "Andy Jassy" OR "Amazon Web Services")',
    "TSLA": '"Tesla"',
    "HD": '"Home Depot"',
    "JPM": '("JPMorgan" OR "Jamie Dimon")',
    "BAC": '"Bank of America"',
    "GS": '"Goldman Sachs"',
    "V": '("Visa Inc" OR "Visa shares" OR "Visa stock")',
    "UNH": '"UnitedHealth"',
    "JNJ": '("Johnson & Johnson" OR "Johnson and Johnson")',
    "PFE": '"Pfizer"',
    "LLY": '"Eli Lilly"',
    "XOM": '"Exxon"',
    "CVX": '"Chevron"',
    "CAT": '("Caterpillar Inc" OR "Caterpillar shares" OR "Caterpillar stock")',
    "BA": '"Boeing"',
    "WMT": '"Walmart"',
    "KO": '"Coca-Cola"',
    "PG": '("Procter & Gamble" OR "Procter and Gamble")',
    "NEE": '"NextEra"',
    "AMT": '"American Tower"',
    "IREN": '("IREN Limited" OR "IREN shares" OR "IREN stock" OR "Iris Energy")',
    # Focus IA (hors S&P 500)
    "TSM": '("TSMC" OR "Taiwan Semiconductor")',
    "ARM": '"Arm Holdings"',
    "MU": '"Micron"',
    "SMCI": '("Super Micro Computer" OR "Supermicro")',
    "VRT": '"Vertiv"',
    "ANET": '"Arista Networks"',
    "NBIS": '"Nebius"',
    "CRWV": '"CoreWeave"',
    "CIFR": '"Cipher Mining"',
    "WULF": '"TeraWulf"',
    "APLD": '"Applied Digital"',
    "CORZ": '"Core Scientific"',
    "PLTR": '"Palantir"',
    "AI": '"C3.ai"',
    "SOUN": '"SoundHound"',
    "BBAI": '"BigBear.ai"',
    "PATH": '"UiPath"',
    "CBRS": '"Cerebras"',
    "FIGR": '"Figure Technology"',
    "AIP": '"Arteris"',
    "ORCL": '"Oracle"',
    MARKET: '("Wall Street" OR "S&P 500" OR "Federal Reserve" OR "stock market")',
}

# Sociétés non cotées suivies pour leurs liens avec des titres (voir universe.LINKS).
ENTITY_QUERIES: dict[str, str] = {
    "OPENAI": '"OpenAI"',
}

# Items des formulaires 8-K (les annexes 9.01 ne sont pas reprises dans le titre).
SEC_8K_ITEMS: dict[str, str] = {
    "1.01": "accord important conclu", "1.02": "fin d'un accord important", "1.03": "faillite",
    "1.05": "incident de cybersécurité", "2.01": "acquisition ou cession d'actifs",
    "2.02": "résultats trimestriels", "2.03": "nouvelle dette", "2.04": "accélération d'une dette",
    "2.05": "coûts de restructuration", "2.06": "dépréciation d'actifs", "3.01": "risque de radiation de la cote",
    "3.02": "émission d'actions non enregistrée", "3.03": "modification des droits des actionnaires",
    "4.01": "changement d'auditeur", "4.02": "comptes antérieurs non fiables",
    "5.01": "changement de contrôle", "5.02": "départ ou nomination de dirigeants",
    "5.03": "modification des statuts", "5.07": "vote des actionnaires", "7.01": "communication financière",
    "8.01": "autres événements",
}
SEC_FORMS: dict[str, str] = {
    "8-K": "événement important", "10-Q": "rapport trimestriel", "10-K": "rapport annuel",
    "6-K": "rapport d'émetteur étranger", "20-F": "rapport annuel (émetteur étranger)",
    "40-F": "rapport annuel (émetteur étranger)",
}

# Séries FRED : clé de l'outil -> (identifiant FRED, transformation, décalage de publication).
#   "daily:N"  : valeur quotidienne connue N jours après la date d'observation ;
#   "monthly:J": valeur du mois M publiée au plus tard le jour J du mois M+1 (prudent).
FRED_SERIES: dict[str, tuple[str, str, str]] = {
    "us10y": ("DGS10", "level", "daily:0"),
    "us2y": ("DGS2", "level", "daily:0"),
    "fed_funds": ("DFF", "level", "daily:1"),
    "vix": ("VIXCLS", "level", "daily:0"),
    "wti": ("DCOILWTICO", "level", "daily:1"),
    "cpi_yoy": ("CPIAUCSL", "yoy", "monthly:16"),       # CPI publié vers le 10-15 du mois suivant
    "unemployment": ("UNRATE", "level", "monthly:10"),  # emploi publié le 1er ou 2e vendredi
}

_TITLE_KEY = re.compile(r"[^a-z0-9]+")


def title_key(title: str) -> str:
    """Clé de dédoublonnage d'un titre (casse et ponctuation ignorées)."""
    return _TITLE_KEY.sub(" ", title.lower()).strip()


def http_get(url: str, headers: Optional[dict] = None, retries: int = 4, timeout: float = 30.0,
             backoff: float = 5.0,
             retry_if: Callable[[str], bool] = lambda body: False, sleep: Callable[[float], None] = time.sleep) -> str:
    """GET avec nouvelles tentatives espacées (429, 5xx, coupures réseau ou réponse refusée)."""
    delay = backoff
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sp500-analyzer research)",
                                                       **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            if attempt < retries and retry_if(body):
                sleep(delay)
                delay *= 2
                continue
            return body
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            retryable = not isinstance(e, urllib.error.HTTPError) or e.code in (429, 500, 502, 503, 504)
            if attempt == retries or not retryable:
                raise
            sleep(delay)
            delay *= 2
    raise RuntimeError("inaccessible")


# ------------------------------------------------------------------------------ GDELT


def source_for_domain(domain: str) -> Optional[str]:
    domain = domain.lower().removeprefix("www.")
    for known, name in NEWS_DOMAINS.items():
        if domain == known or domain.endswith("." + known):
            return name
    return None


def _gdelt_time(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


def parse_gdelt(body: str) -> list[dict]:
    """Articles d'une réponse GDELT ; lève ValueError si l'API a répondu par un message texte."""
    body = body.strip()
    if not body:
        return []
    if not body.startswith("{"):
        raise ValueError(f"GDELT : {body[:200]}")
    return json.loads(body).get("articles") or []


def gdelt_articles(query: str, start: datetime, end: datetime, sleep=time.sleep, retries: int = 3) -> list[dict]:
    params = {"query": f"{query} sourcelang:english", "mode": "artlist", "format": "json",
              "maxrecords": "250", "sort": "datedesc",
              "startdatetime": _gdelt_time(start), "enddatetime": _gdelt_time(end)}
    body = http_get(f"{GDELT_URL}?{urllib.parse.urlencode(params)}", timeout=45, retries=retries, backoff=20.0,
                    retry_if=lambda b: b.lstrip().lower().startswith("please limit"), sleep=sleep)
    return parse_gdelt(body)


def to_news_rows(articles: list[dict]) -> list[tuple[datetime, str, str, str, str]]:
    """(publication heure de New York, source, domaine, titre, url) des sources connues,
    reprises d'un même titre dédoublonnées (la première parution est gardée)."""
    rows: dict[str, tuple] = {}
    for a in articles:
        source = source_for_domain(a.get("domain", ""))
        title = html.unescape((a.get("title") or "").strip())
        if not source or len(title) < 15:
            continue
        try:
            seen = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        published = seen.astimezone(NEW_YORK).replace(tzinfo=None)
        key = title_key(title)
        if key not in rows or published < rows[key][0]:
            rows[key] = (published, source, a.get("domain", ""), title, a.get("url", ""))
    return sorted(rows.values())


WINDOW_ANCHOR = date(2026, 1, 5)  # lundi : fenêtres hebdomadaires fixes d'un lancement à l'autre


def news_windows(start: date, end: date, days: int = 7) -> list[tuple[date, date]]:
    """Fenêtres [début, fin) de `days` jours alignées sur WINDOW_ANCHOR, de la première
    commençant à `start` ou après (GDELT ne remonte pas plus loin) jusqu'à celle contenant `end`."""
    first = WINDOW_ANCHOR + timedelta(days=days * -(-(start - WINDOW_ANCHOR).days // days))
    out, day = [], first
    while day <= end:
        out.append((day, day + timedelta(days=days)))
        day += timedelta(days=days)
    return out


def read_news_rows(path: Path) -> list[tuple[datetime, str, str, str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return [(datetime.fromisoformat(r["Published"]), r["Source"], r["Domain"], r["Title"], r["Url"])
                for r in csv.DictReader(f)]


def rebuild_ticker_file(folder: Path, ticker: str) -> int:
    """Fusionne les fenêtres téléchargées d'un titre dans news/<TICKER>.csv (dédoublonné)."""
    rows: dict[tuple, tuple] = {}
    for path in sorted((folder / "fenetres" / ticker).glob("*.csv")):
        for row in read_news_rows(path):
            key = title_key(row[3])
            if key not in rows or row[0] < rows[key][0]:
                rows[key] = row
    write_news_csv(folder / f"{ticker}.csv", sorted(rows.values()))
    return len(rows)


def download_windows(folder: Path, tickers: list[str], windows: list[tuple[date, date]], fetch_rows,
                     label: str, pause: float, budget_minutes: float, today: date,
                     log=print, clock=time.monotonic, sleep=time.sleep) -> list[str]:
    """Télécharge des news fenêtre par fenêtre jusqu'à épuisement du budget de temps.

    `fetch_rows(ticker, début, fin)` renvoie les lignes de news d'une fenêtre. Chaque fenêtre
    réussie est enregistrée (<folder>/fenetres/<TICKER>/<début>.csv) et n'est plus
    retéléchargée ; les fenêtres refusées (limite de débit) sont retentées lors d'un passage
    suivant ou d'un prochain lancement. La fenêtre en cours (pas encore close) est toujours
    retéléchargée. <folder>/<TICKER>.csv rassemble les fenêtres disponibles et
    <folder>/couverture.csv indique, par titre, la part des fenêtres obtenues."""
    deadline = clock() + budget_minutes * 60

    def cached(ticker: str, w: tuple[date, date]) -> Path:
        return folder / "fenetres" / ticker / f"{w[0].isoformat()}.csv"

    # Les semaines les plus récentes d'abord : ce sont les plus utiles à l'analyse du jour.
    todo = [(t, w) for w in reversed(windows) for t in tickers if not cached(t, w).exists() or w[1] > today]
    log(f"  {label} : {len(todo)} fenêtre(s) à télécharger sur {len(windows) * len(tickers)}")
    passes = 0
    while todo and clock() < deadline:
        passes += 1
        failed = []
        for ticker, w in todo:
            if clock() >= deadline:
                failed.append((ticker, w))
                continue
            try:
                rows = fetch_rows(ticker, datetime.combine(w[0], datetime.min.time()),
                                  datetime.combine(w[1], datetime.min.time()))
            except Exception as e:  # noqa: BLE001 — refus ou erreur : fenêtre retentée plus tard
                failed.append((ticker, w))
                log(f"  ✗ {label} {ticker} {w[0]} : {type(e).__name__}: {str(e)[:120]}")
            else:
                path = cached(ticker, w)
                path.parent.mkdir(parents=True, exist_ok=True)
                write_news_csv(path, rows)
                n = rebuild_ticker_file(folder, ticker)
                log(f"  {label} {ticker:6} {w[0]} : {len(rows):3} titres retenus, {n} au total")
            sleep(pause)
        todo = failed
        log(f"  {label} : passage {passes} terminé, {len(todo)} fenêtre(s) restante(s)")
    write_coverage(folder, tickers, windows)
    return [f"{label} : {len(todo)} fenêtre(s) non obtenue(s) (limite de débit) — relancer pour compléter"] if todo else []


def download_news(out_dir: Path, tickers: list[str], start: date, end: date, window_days: int = 7,
                  pause: float = GDELT_PAUSE, budget_minutes: float = 60.0, today: Optional[date] = None,
                  log=print, clock=time.monotonic, sleep=time.sleep) -> list[str]:
    """News GDELT par fenêtres hebdomadaires mises en cache (voir download_windows)."""
    known = [t for t in tickers if t in GDELT_QUERIES]
    errors = [f"news {t} : pas de requête GDELT définie" for t in tickers if t not in GDELT_QUERIES]

    def fetch(ticker: str, start_dt: datetime, end_dt: datetime):
        return to_news_rows(gdelt_articles(GDELT_QUERIES[ticker], start_dt, end_dt, retries=0))

    errors += download_windows(out_dir / "news", known, news_windows(start, end, window_days), fetch, "GDELT",
                               pause, budget_minutes, today or date.today(), log, clock, sleep)
    return errors


def write_coverage(folder: Path, tickers: list[str], windows: list[tuple[date, date]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["Ticker,Fenetres,Obtenues,Articles"]
    for t in tickers:
        done = sum((folder / "fenetres" / t / f"{w[0].isoformat()}.csv").exists() for w in windows)
        n = len(read_news_rows(folder / f"{t}.csv")) if (folder / f"{t}.csv").exists() else 0
        lines.append(f"{t},{len(windows)},{done},{n}")
    (folder / "couverture.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_news_csv(path: Path, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Published", "Source", "Domain", "Title", "Url"])
        for published, source, domain, title, url in rows:
            w.writerow([published.strftime("%Y-%m-%d %H:%M"), source, domain, title, url])


# -------------------------------------------------------------------------------- SEC


def sec_rows(submissions: dict, cik: int, start: date) -> list[tuple[datetime, str, str, str, str]]:
    """(dépôt heure de New York, formulaire, items, titre, url) depuis `start`.

    acceptanceDateTime est exprimé en heure de l'Est malgré son suffixe « Z » (convention
    d'EDGAR) : un 8-K de résultats publié après la clôture est accepté vers 16h05.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    out = []
    for i, form in enumerate(recent.get("form", [])):
        if form not in SEC_FORMS:
            continue
        try:
            accepted = datetime.fromisoformat(recent["acceptanceDateTime"][i][:19])
        except (KeyError, IndexError, ValueError):
            continue
        if accepted.date() < start:
            continue
        items = [it.strip() for it in (recent.get("items", [""] * (i + 1))[i] or "").split(",") if it.strip()]
        described = [SEC_8K_ITEMS[it] for it in items if it in SEC_8K_ITEMS]
        title = f"Dépôt SEC {form} : " + (", ".join(described) if described else SEC_FORMS[form])
        acc = recent["accessionNumber"][i].replace("-", "")
        doc = (recent.get("primaryDocument") or [""] * (i + 1))[i]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
        out.append((accepted, form, " ".join(items), title, url))
    return sorted(out)


def download_sec(out_dir: Path, tickers: list[str], start: date, user_agent: str,
                 pause: float = 0.3, log=print) -> list[str]:
    folder = out_dir / "sec"
    folder.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
    try:
        mapping = json.loads(http_get(SEC_TICKERS_URL, headers=headers, retries=2))
    except Exception as e:  # noqa: BLE001
        return [f"SEC : liste des sociétés inaccessible ({type(e).__name__}: {e})"]
    cik_of = {v["ticker"].upper().replace("-", "."): int(v["cik_str"]) for v in mapping.values()}
    errors = []
    for ticker in tickers:
        cik = cik_of.get(ticker)
        if cik is None:
            errors.append(f"SEC {ticker} : CIK introuvable")
            continue
        try:
            rows = sec_rows(json.loads(http_get(SEC_SUBMISSIONS_URL.format(cik=cik), headers=headers)), cik, start)
        except Exception as e:  # noqa: BLE001
            errors.append(f"SEC {ticker} : {type(e).__name__}: {e}")
            log(f"  ✗ SEC {ticker} : {type(e).__name__}: {e}")
            if isinstance(e, urllib.error.HTTPError) and e.code == 403:
                errors.append("SEC : accès refusé (403) — renseigner le secret SEC_USER_AGENT")
                return errors
            continue
        with open(folder / f"{ticker}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Published", "Form", "Items", "Title", "Url"])
            for accepted, form, items, title, url in rows:
                w.writerow([accepted.strftime("%Y-%m-%d %H:%M:%S"), form, items, title, url])
        log(f"  SEC  {ticker:6} {len(rows):4} dépôts")
        time.sleep(pause)
    return errors


# ------------------------------------------------------------------------------- FRED


def parse_fred_csv(body: str) -> list[tuple[date, float]]:
    rows = []
    for line in body.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2 or parts[1].strip() in ("", "."):
            continue
        try:
            rows.append((date.fromisoformat(parts[0].strip()), float(parts[1])))
        except ValueError:
            continue
    return rows


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def publication_dated(obs: list[tuple[date, float]], transform: str, timing: str) -> list[tuple[date, float]]:
    """Applique la transformation (niveau / glissement annuel) puis date chaque point de sa
    publication : sans cela, le backtest utiliserait des chiffres pas encore connus."""
    if transform == "yoy":
        by_month = {(d.year, d.month): v for d, v in obs}
        obs = [(d, round((v / by_month[(d.year - 1, d.month)] - 1) * 100, 3))
               for d, v in obs if (d.year - 1, d.month) in by_month]
    kind, _, n = timing.partition(":")
    if kind == "monthly":
        return [(_add_months(d, 1).replace(day=int(n)), v) for d, v in obs]
    return [(d + timedelta(days=int(n)), v) for d, v in obs]


# ------------------------------------------------- sources macro de repli (sans clé)
# FRED peut être lent ou refuser certains serveurs : chaque série a une source officielle
# (ou de marché) de secours, interrogée si FRED échoue.
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")
NYFED_EFFR_URL = "https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate={start}&endDate={end}"
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/{series}?startyear={start}&endyear={end}"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5y&interval=1d"


def parse_treasury_csv(body: str, column: str) -> list[tuple[date, float]]:
    """Courbe des taux du Trésor américain (colonnes « Date » au format MM/JJ/AAAA, « 2 Yr »...)."""
    rows = list(csv.DictReader(body.strip().splitlines()))
    out = []
    for r in rows:
        try:
            out.append((datetime.strptime(r["Date"], "%m/%d/%Y").date(), float(r[column])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def parse_nyfed_effr(body: str) -> list[tuple[date, float]]:
    return sorted((date.fromisoformat(r["effectiveDate"]), float(r["percentRate"]))
                  for r in json.loads(body).get("refRates", []) if r.get("percentRate") is not None)


def parse_bls(body: str) -> list[tuple[date, float]]:
    """Série mensuelle BLS : (premier jour du mois mesuré, valeur)."""
    payload = json.loads(body)
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS : {payload.get('message') or payload.get('status')}")
    out = []
    for s in payload["Results"]["series"]:
        for r in s["data"]:
            if r["period"].startswith("M") and r["period"] != "M13" and r["value"] not in ("-", ""):
                out.append((date(int(r["year"]), int(r["period"][1:]), 1), float(r["value"])))
    return sorted(out)


def parse_yahoo_closes(body: str) -> list[tuple[date, float]]:
    result = (json.loads(body).get("chart", {}).get("result") or [None])[0]
    if not result:
        return []
    closes = result["indicators"]["quote"][0]["close"]
    return [(datetime.fromtimestamp(ts, NEW_YORK).date(), round(c, 4))
            for ts, c in zip(result["timestamp"], closes) if c is not None]


def _fallback(key: str, start: date, end: date) -> tuple[str, list[tuple[date, float]]]:
    """(nom de la source, observations) de secours pour une clé macro."""
    if key in ("us10y", "us2y"):
        column = "10 Yr" if key == "us10y" else "2 Yr"
        obs = []
        for year in range(start.year, end.year + 1):
            obs += parse_treasury_csv(http_get(TREASURY_URL.format(year=year), retries=1), column)
            time.sleep(0.5)
        return "Trésor américain", obs
    if key == "fed_funds":
        return "Fed de New York (EFFR)", parse_nyfed_effr(
            http_get(NYFED_EFFR_URL.format(start=start.isoformat(), end=end.isoformat()), retries=1))
    if key in ("cpi_yoy", "unemployment"):
        series = "CUUR0000SA0" if key == "cpi_yoy" else "LNS14000000"
        return "BLS", parse_bls(http_get(BLS_URL.format(series=series, start=start.year, end=end.year), retries=1))
    if key in ("vix", "wti"):
        symbol = "%5EVIX" if key == "vix" else "CL%3DF"
        return "Yahoo Finance", parse_yahoo_closes(http_get(YAHOO_CHART_URL.format(symbol=symbol), retries=1))
    raise KeyError(key)


def download_macro(out_dir: Path, start: date, log=print, end: Optional[date] = None) -> list[str]:
    """Séries macro depuis FRED, ou depuis la source de secours de chaque série si FRED échoue
    (après un premier échec, FRED n'est plus interrogé pour gagner du temps)."""
    folder = out_dir / "macro"
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    fetch_from = date(start.year - 2, 1, 1)  # historique pour les glissements annuels / trimestriels
    end = end or date.today()
    fred_ok = True
    for key, (series, transform, timing) in FRED_SERIES.items():
        obs, source = [], ""
        if fred_ok:
            try:
                obs = parse_fred_csv(http_get(FRED_URL.format(series=series, start=fetch_from.isoformat()),
                                              retries=1, timeout=20))
                source = f"FRED {series}"
            except Exception as e:  # noqa: BLE001
                fred_ok = False
                log(f"  ✗ FRED {series} : {type(e).__name__}: {e} — sources de secours utilisées")
        if not obs:
            try:
                source, obs = _fallback(key, fetch_from, end)
            except Exception as e:  # noqa: BLE001
                errors.append(f"macro {key} : FRED et source de secours en échec ({type(e).__name__}: {e})")
                log(f"  ✗ {key} : {type(e).__name__}: {e}")
                continue
        points = publication_dated(obs, transform, timing)
        if not points:
            errors.append(f"macro {key} : aucune observation ({source})")
            continue
        (folder / f"{key}.csv").write_text(
            "Date,Value\n" + "".join(f"{d.isoformat()},{v}\n" for d, v in points), encoding="utf-8")
        log(f"  macro {key:13} ({source}) {len(points)} points, dernier {points[-1][0]} = {points[-1][1]}")
        time.sleep(0.5)
    return errors
