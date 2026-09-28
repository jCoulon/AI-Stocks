"""Vrais cours de bourse lus dans des fichiers CSV (un fichier par titre).

Format accepté (celui de Stooq et de Yahoo Finance) : une ligne d'en-tête contenant
Date, Open, High, Low, Close, Volume (insensible à la casse ; « Adj Close » ignoré).
Fichiers attendus : `<dossier>/<TICKER>.csv` pour chaque titre de l'univers et
`<dossier>/SPX.csv` pour l'indice.

Seuls les cours sont réels : cette source ne fournit ni news, ni messages sociaux,
ni séries macro. Les piliers correspondants restent vides (l'outil l'indique), et le
backtest porte alors sur les signaux calculés à partir des cours.
"""

from __future__ import annotations

import csv
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

from ..models import Bar, NewsItem, Security, Series, SocialPost
from ..universe import INDEX, SP500_SAMPLE, UNIVERSES
from .base import DataProvider

INDEX_FILE = "SPX"
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"


def stooq_symbol(ticker: str) -> str:
    return "^spx" if ticker in (INDEX.ticker, INDEX_FILE) else ticker.lower().replace(".", "-") + ".us"


def read_bars(path: Path) -> list[Bar]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = {(name or "").strip().lower(): name for name in reader.fieldnames or []}
        missing = {"date", "open", "high", "low", "close"} - set(fields)
        if missing:
            raise ValueError(f"{path.name} : colonnes manquantes {sorted(missing)}")
        bars = []
        for row in reader:
            try:
                o, h, lo, c = (float(row[fields[k]]) for k in ("open", "high", "low", "close"))
            except (TypeError, ValueError):
                continue  # ligne vide ou « null » (jour férié dans certains exports)
            vol = row.get(fields.get("volume", ""), "") or "0"
            bars.append(Bar(date.fromisoformat(row[fields["date"]][:10]), o, h, lo, c, int(float(vol))))
    bars.sort(key=lambda b: b.day)
    if not bars:
        raise ValueError(f"{path.name} : aucune cotation lisible")
    return bars


class CsvPriceProvider(DataProvider):
    def __init__(self, folder: str | Path, as_of: date | None = None, universe: str = "sp500"):
        self.folder = Path(folder)
        self._bars: dict[str, list[Bar]] = {}
        self._securities = UNIVERSES[universe]
        missing = []
        for sec in self._securities:
            path = self.folder / f"{sec.ticker}.csv"
            if path.exists():
                self._bars[sec.ticker] = read_bars(path)
            else:
                missing.append(sec.ticker)
        index_path = self.folder / f"{INDEX_FILE}.csv"
        if not index_path.exists():
            raise FileNotFoundError(f"Fichier de l'indice introuvable : {index_path}")
        self._bars[INDEX.ticker] = read_bars(index_path)
        self.missing = missing
        last = self._bars[INDEX.ticker][-1].day
        self.as_of = min(as_of, last) if as_of else last
        if as_of:
            self._bars = {t: [b for b in bars if b.day <= as_of] for t, bars in self._bars.items()}

    def universe(self) -> list[Security]:
        return [sec for sec in self._securities if sec.ticker in self._bars]

    def index(self) -> Security:
        return INDEX

    def trading_days(self) -> list[date]:
        return [b.day for b in self._bars[INDEX.ticker]]

    def price_history(self, ticker: str) -> list[Bar]:
        return list(self._bars[ticker])

    def news(self, ticker: str | None, since: datetime) -> list[NewsItem]:
        return []

    def social_posts(self, ticker: str, since: datetime) -> list[SocialPost]:
        return []

    def macro(self) -> dict[str, Series]:
        return {}


def download_stooq(folder: str | Path, tickers: list[str] | None = None, timeout: float = 30.0) -> list[str]:
    """Télécharge l'historique quotidien depuis Stooq (sans clé). Renvoie les erreurs éventuelles."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tickers = tickers or [p.security.ticker for p in SP500_SAMPLE]
    errors = []
    for ticker in [*tickers, INDEX_FILE]:
        url = STOOQ_URL.format(symbol=stooq_symbol(ticker))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 sp500-analyzer"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            errors.append(f"{ticker} : {e}")
            continue
        if not data.lower().startswith("date"):
            errors.append(f"{ticker} : réponse inattendue de Stooq ({data[:60]!r})")
            continue
        (folder / f"{ticker}.csv").write_text(data, encoding="utf-8")
    return errors
