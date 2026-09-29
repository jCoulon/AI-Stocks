"""Serveur local de l'application : sert l'interface et une petite API JSON / HTML.

L'interface est la même dans la fenêtre native macOS (pywebview) et dans un
navigateur. Le serveur n'écoute que sur 127.0.0.1 ; les requêtes qui déclenchent
un calcul exigent un jeton de session et un en-tête Host local, pour qu'une page
web tierce ne puisse pas piloter l'application (ni lancer d'appels payants à Claude).
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from ..agents.advisor import AdvisorError, AdvisorUnavailable, ClaudeAdvisor
from ..models import MarketReport
from ..orchestrator import Orchestrator
from ..providers.base import DataProvider
from ..providers.mock import MockDataProvider
from ..providers.pointintime import PointInTimeProvider
from ..universe import AI_THEME
from ..report import (
    CHART_JS, REPORT_CSS, disclaimer, html_agents, html_market, html_stock_detail, html_stock_header,
    render_html, summarize_trace,
)

DEFAULT_AS_OF = date(2026, 9, 25)
MARKET = "__MARKET__"  # identifiant de la vue marché pour les avis Claude
ProviderFactory = Callable[[date, int], DataProvider]


UNIVERSE_LABELS = {"sp500": "S&P 500", "ia": "Focus IA", "tout": "S&P 500 + IA"}


class AppState:
    """Rapport courant et paramètres de l'analyse ; recalcul à la demande.

    Deux sources : données simulées (S&P 500 seulement) ou données réelles lues dans
    `data_dir` (S&P 500, focus IA ou les deux). Avec les données réelles, une séance
    antérieure est analysée sur une vue « point-in-time » (rien de postérieur n'est visible)."""

    def __init__(self, provider_factory: ProviderFactory = None, as_of: date | None = None, seed: int = 42,
                 advisor: Optional[ClaudeAdvisor] = None, data_dir: Optional[Path] = None):
        self.provider_factory = provider_factory
        #: Fichier de la liste de surveillance (None : ~/.sp500_analyzer/watchlist.json ou SP500_WATCHLIST)
        self.watchlist_file = None
        self.data_dir = Path(data_dir) if data_dir else None
        self.source = "reel" if self.data_dir and not provider_factory else "simule"
        self.universe = "tout" if self.source == "reel" else "sp500"
        self._real: dict[str, object] = {}  # RealDataProvider par univers (chargé une fois)
        self.as_of, self.seed, self.use_llm = as_of, seed, False
        self.report: Optional[MarketReport] = None
        self.error = ""
        self.simulated = True
        self.generation = 0  # incrémenté à chaque analyse : invalide le cache des avis Claude
        self.advisor = advisor or ClaudeAdvisor()
        self.advice_cache: dict[tuple[int, str], str] = {}
        self._lock = threading.Lock()

    def real_provider(self, universe: str):
        from ..providers.realdata import RealDataProvider

        if universe not in self._real:
            self._real[universe] = RealDataProvider(self.data_dir, universe=universe)
        return self._real[universe]

    def set_data_dir(self, path: Path) -> None:
        self.data_dir, self._real = Path(path), {}
        self.source, self.universe, self.as_of = "reel", "tout", None

    def _provider(self) -> DataProvider:
        if self.provider_factory:
            return self.provider_factory(self.as_of or DEFAULT_AS_OF, self.seed)
        if self.source == "simule":
            return MockDataProvider(as_of=self.as_of or DEFAULT_AS_OF, seed=self.seed)
        base = self.real_provider(self.universe)
        if self.as_of and self.as_of < base.as_of:
            return PointInTimeProvider(base, self.as_of)
        return base

    def refresh(self, as_of: date | None = None, seed: int | None = None, use_llm: bool | None = None,
                source: str | None = None, universe: str | None = None) -> MarketReport:
        with self._lock:
            if source in ("simule", "reel") and source != self.source:
                if source == "reel" and not self.data_dir:
                    raise ValueError("aucun dossier de données réelles : choisissez-en un")
                self.source, as_of = source, None  # la date par défaut dépend de la source
                self.as_of = None
                self.universe = "tout" if source == "reel" else "sp500"
            if universe in UNIVERSE_LABELS and self.source == "reel":
                self.universe = universe
            if as_of is not None:
                self.as_of = as_of
            if seed is not None:
                self.seed = seed
            if use_llm is not None:
                self.use_llm = use_llm
            provider = self._provider()
            self.simulated = isinstance(provider, MockDataProvider)
            self.report = Orchestrator(provider, use_llm=self.use_llm).run()
            self.generation += 1
            return self.report

    def asymmetry_html(self) -> str:
        """Écran d'asymétrie du focus IA pour l'analyse courante (données réelles)."""
        from ..analysis.asymmetry import build_row, html_asymmetry, score_rows
        from ..providers.fundamentals import load_fundamentals

        r = self.current()
        if self.source != "reel":
            return '<p class="empty">L\'écran d\'asymétrie nécessite les données réelles.</p>'
        provider = self._provider()
        labels = {t.security.ticker: (t.short.label, t.medium.label) for t in r.tickers}
        rows = []
        for sec in provider.universe():
            if sec.ticker not in AI_THEME:
                continue
            bars = provider.price_history(sec.ticker)
            if len(bars) < 30:
                continue
            row = build_row(sec.ticker, sec.name, AI_THEME[sec.ticker], bars, load_fundamentals(self.data_dir, sec.ticker))
            row.short_label, row.medium_label = labels.get(sec.ticker, ("", ""))
            rows.append(row)
        return html_asymmetry(score_rows(rows))

    def besttry_html(self, horizon: int = 60) -> str:
        """Écran « Best try » : catalyseurs datés des titres de l'univers courant (données réelles)."""
        from ..analysis.besttry import html_besttry, screen

        r = self.current()
        if self.source != "reel":
            return '<p class="empty">L\'écran « Best try » nécessite les données réelles.</p>'
        provider = self._provider()
        labels = {t.security.ticker: (t.short.label, t.medium.label) for t in r.tickers}
        rows, market, fetched = screen(provider, self.data_dir, horizon, labels)
        return html_besttry(rows, provider.as_of, horizon, market, fetched)

    def polymarket_html(self) -> str:
        """Écran Polymarket (rapport produit par le workflow « Polymarket »)."""
        import json

        from ..analysis.polymarket import render_html

        path = self.data_dir / "polymarket" / "report.json" if self.data_dir else None
        return render_html(json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None)

    def watchlist_html(self) -> str:
        """Liste de surveillance de l'utilisateur, avec les conditions d'entrée de chaque titre."""
        from ..analysis.watchlist import assess, load_watchlist, render_html
        from ..providers.events import load_events
        from ..providers.fundamentals import load_fundamentals

        r = self.current()
        tickers = load_watchlist(self.watchlist_file)
        by = {t.security.ticker: t for t in r.tickers}
        real = self.source == "reel" and self.data_dir
        views, missing = [], []
        for tk in tickers:
            t = by.get(tk)
            if t is None:
                missing.append(tk)
                continue
            fund = load_fundamentals(self.data_dir, tk) if real else None
            ev = (load_events(self.data_dir, tk) or {}).get("next_earnings") if real else None
            nxt = (date.fromisoformat(ev["date"]), "Résultats" + (" (date estimée)" if ev.get("estimated") else "")) if ev else None
            views.append(assess(t, fund, nxt, r.as_of, r.macro_summary))
        return render_html(views, missing, r.as_of, tickers, sorted(by))

    def update_watchlist(self, add: str = "", remove: str = "") -> list[str]:
        from ..analysis.watchlist import load_watchlist, save_watchlist

        tickers = load_watchlist(self.watchlist_file)
        if add:
            tickers.append(add.strip().upper())
        if remove:
            tickers = [t for t in tickers if t != remove.strip().upper()]
        return save_watchlist(tickers, self.watchlist_file)

    def advice_key(self, ticker: str) -> tuple[int, str]:
        self.current()
        return self.generation, ticker

    def current(self) -> MarketReport:
        return self.report or self.refresh()

    def summary(self) -> dict:
        r = self.current()
        writer = next((t for t in r.trace if t["agent"] == "redacteur"), None)
        real = self.source == "reel"
        return {
            "as_of": r.as_of.isoformat(),
            "as_of_max": self.real_provider(self.universe).as_of.isoformat() if real else None,
            "source": self.source,
            "universe": self.universe,
            "universe_label": UNIVERSE_LABELS[self.universe] if real else "S&P 500 (données simulées)",
            "real_available": bool(self.data_dir),
            "data_dir": str(self.data_dir) if self.data_dir else None,
            "coverage": self.real_provider(self.universe).coverage() if real else None,
            "asymmetry": real and self.universe != "sp500"
                         and any((self.data_dir / "fundamentals").glob("*.json")),
            "besttry": real,
            "polymarket": bool(self.data_dir and (self.data_dir / "polymarket" / "report.json").exists()),
            "seed": self.seed,
            "llm": self.use_llm,
            "llm_status": None if writer is None else {"status": writer["status"], "error": writer["error"]},
            "disclaimer": disclaimer(r),
            "index": {"close": r.index.last_close, "week": r.index.week_return,
                      "short": r.index.short.label, "medium": r.index.medium.label},
            "agents": summarize_trace(r.trace),
            "tickers": [
                {
                    "ticker": t.security.ticker,
                    "name": t.security.name,
                    "sector": t.security.sector,
                    "theme": AI_THEME.get(t.security.ticker),
                    "close": t.last_close,
                    "week": t.week_return,
                    "short": {"label": t.short.label, "score": t.short.score, "confidence": t.short.confidence},
                    "medium": {"label": t.medium.label, "score": t.medium.score, "confidence": t.medium.confidence},
                    "alerts": sum(f.severity != "info" for f in t.flags),
                }
                for t in r.tickers
            ],
        }


def ui_html(token: str) -> str:
    page = resources.files(__package__).joinpath("ui.html").read_text(encoding="utf-8")
    return (page.replace("/*REPORT_CSS*/", REPORT_CSS)
                .replace("/*CHART_JS*/", CHART_JS)
                .replace("__TOKEN__", token))


def make_handler(state: AppState, token: str, port_ref: list[int]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SP500Analyzer"

        def log_message(self, fmt, *args):  # silence : pas de journal HTTP dans la console
            pass

        # ------------------------------------------------------------- utilitaires
        def _send(self, status: int, body: str | bytes, ctype: str, extra: dict | None = None) -> None:
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, status: int = 200) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def _local_host(self) -> bool:
            # Protège contre le « DNS rebinding » : seul un Host local est accepté.
            host = self.headers.get("Host", "")
            return host in (f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}")

        def _authorized(self) -> bool:
            return self._local_host() and secrets.compare_digest(self.headers.get("X-App-Token", ""), token)

        # ----------------------------------------------------------------- routes
        def do_GET(self):
            if not self._local_host():
                return self._send(HTTPStatus.FORBIDDEN, "Hôte non autorisé", "text/plain; charset=utf-8")
            url = urlparse(self.path)
            path = url.path
            try:
                if path == "/":
                    return self._send(200, ui_html(token), "text/html; charset=utf-8")
                if not self._authorized():
                    return self._json({"error": "jeton invalide"}, HTTPStatus.FORBIDDEN)
                if path == "/api/summary":
                    return self._json(state.summary())
                if path == "/api/market":
                    r = state.current()
                    return self._send(200, html_market(r) + html_agents(r), "text/html; charset=utf-8")
                if path == "/api/asymmetry":
                    return self._send(200, state.asymmetry_html(), "text/html; charset=utf-8")
                if path == "/api/watchlist":
                    return self._send(200, state.watchlist_html(), "text/html; charset=utf-8")
                if path == "/api/polymarket":
                    return self._send(200, state.polymarket_html(), "text/html; charset=utf-8")
                if path == "/api/besttry":
                    return self._send(200, state.besttry_html(), "text/html; charset=utf-8")
                if path.startswith("/api/stock/"):
                    ticker = path.rsplit("/", 1)[-1].upper()
                    t = next((x for x in state.current().tickers if x.security.ticker == ticker), None)
                    if t is None:
                        return self._json({"error": f"titre inconnu : {ticker}"}, HTTPStatus.NOT_FOUND)
                    return self._send(200, html_stock_header(t) + html_stock_detail(t), "text/html; charset=utf-8")
                if path.startswith("/api/advice/"):
                    ticker = path.rsplit("/", 1)[-1].upper()
                    cached = state.advice_cache.get(state.advice_key(ticker))
                    if cached is None:
                        return self._json({"error": "aucun avis en cache"}, HTTPStatus.NOT_FOUND)
                    return self._json({"ticker": ticker, "text": cached})
                if path == "/api/export":
                    r = state.current()
                    name = f"analyse-{state.universe}-{r.as_of.isoformat()}.html"
                    return self._send(200, render_html(r), "text/html; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="{name}"'})
                return self._json({"error": "introuvable"}, HTTPStatus.NOT_FOUND)
            except Exception as e:  # noqa: BLE001 — l'erreur est renvoyée à l'interface
                return self._json({"error": f"{type(e).__name__}: {e}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("objet JSON attendu")
            return data

        def _advice(self) -> None:
            """Avis de Claude diffusé en continu (texte brut, connexion fermée en fin de réponse)."""
            try:
                params = self._body()
            except (ValueError, json.JSONDecodeError) as e:
                return self._json({"error": f"paramètres invalides : {e}"}, HTTPStatus.BAD_REQUEST)
            ticker = str(params.get("ticker", MARKET)).upper()
            report = state.current()
            if ticker != MARKET and not any(t.security.ticker == ticker for t in report.tickers):
                return self._json({"error": f"titre inconnu : {ticker}"}, HTTPStatus.NOT_FOUND)
            key = state.advice_key(ticker)
            if not params.get("refresh") and key in state.advice_cache:
                return self._send(200, state.advice_cache[key], "text/plain; charset=utf-8")
            chunks = state.advisor.stream(report, None if ticker == MARKET else ticker, state.simulated)
            try:  # erreurs avant le premier morceau : réponse JSON explicite
                first = next(chunks, "")
            except AdvisorUnavailable as e:
                return self._json({"error": str(e), "needs_key": e.needs_key}, HTTPStatus.SERVICE_UNAVAILABLE)
            except AdvisorError as e:
                return self._json({"error": str(e)}, HTTPStatus.BAD_GATEWAY)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.close_connection = True
            parts = [first]
            try:
                self.wfile.write(first.encode("utf-8"))
                self.wfile.flush()
                for chunk in chunks:
                    parts.append(chunk)
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                chunks.close()  # l'utilisateur a arrêté : on coupe l'appel, rien n'est mis en cache
                return
            except (AdvisorError, AdvisorUnavailable) as e:
                self.wfile.write(f"\n\n⚠ Avis interrompu : {e}".encode("utf-8"))
                return
            state.advice_cache[key] = "".join(parts)

        def do_POST(self):
            if not self._authorized():
                return self._json({"error": "jeton invalide"}, HTTPStatus.FORBIDDEN)
            path = urlparse(self.path).path
            if path == "/api/advice":
                return self._advice()
            if path == "/api/credentials":
                try:
                    key = str(self._body().get("api_key", "")).strip()
                except (ValueError, json.JSONDecodeError) as e:
                    return self._json({"error": f"paramètres invalides : {e}"}, HTTPStatus.BAD_REQUEST)
                if not key:
                    return self._json({"error": "clé vide"}, HTTPStatus.BAD_REQUEST)
                state.advisor.set_api_key(key)  # gardée en mémoire seulement, jamais écrite sur disque
                return self._json({"ok": True})
            if path == "/api/watchlist":
                try:
                    params = self._body()
                    state.update_watchlist(str(params.get("add", "")), str(params.get("remove", "")))
                    return self._send(200, state.watchlist_html(), "text/html; charset=utf-8")
                except (ValueError, json.JSONDecodeError, OSError) as e:
                    return self._json({"error": f"liste de surveillance : {e}"}, HTTPStatus.BAD_REQUEST)
            if path != "/api/refresh":
                return self._json({"error": "introuvable"}, HTTPStatus.NOT_FOUND)
            try:
                params = self._body()
                as_of = date.fromisoformat(params["as_of"]) if params.get("as_of") else None
                seed = int(params["seed"]) if params.get("seed") not in (None, "") else None
                state.refresh(as_of, seed, bool(params.get("llm", False)),
                              params.get("source"), params.get("universe"))
                return self._json(state.summary())
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                return self._json({"error": f"paramètres invalides : {e}"}, HTTPStatus.BAD_REQUEST)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    return Handler


class AppServer:
    """Serveur HTTP local lancé dans un thread d'arrière-plan."""

    def __init__(self, state: AppState | None = None, port: int = 0):
        self.state = state or AppState()
        self.token = secrets.token_urlsafe(24)
        port_ref = [0]
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.state, self.token, port_ref))
        self.port = port_ref[0] = self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> "AppServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="sp500-app-server", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
