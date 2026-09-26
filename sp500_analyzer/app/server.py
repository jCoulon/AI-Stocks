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
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from ..models import MarketReport
from ..orchestrator import Orchestrator
from ..providers.base import DataProvider
from ..providers.mock import MockDataProvider
from ..report import (
    CHART_JS, DISCLAIMER, REPORT_CSS, html_agents, html_market, html_stock_detail, html_stock_header,
    render_html, summarize_trace,
)

DEFAULT_AS_OF = date(2026, 9, 25)
ProviderFactory = Callable[[date, int], DataProvider]


class AppState:
    """Rapport courant et paramètres de l'analyse ; recalcul à la demande."""

    def __init__(self, provider_factory: ProviderFactory = None, as_of: date = DEFAULT_AS_OF, seed: int = 42):
        self.provider_factory = provider_factory or (lambda d, s: MockDataProvider(as_of=d, seed=s))
        self.as_of, self.seed, self.use_llm = as_of, seed, False
        self.report: Optional[MarketReport] = None
        self.error = ""
        self._lock = threading.Lock()

    def refresh(self, as_of: date | None = None, seed: int | None = None, use_llm: bool | None = None) -> MarketReport:
        with self._lock:
            if as_of is not None:
                self.as_of = as_of
            if seed is not None:
                self.seed = seed
            if use_llm is not None:
                self.use_llm = use_llm
            provider = self.provider_factory(self.as_of, self.seed)
            self.report = Orchestrator(provider, use_llm=self.use_llm).run()
            return self.report

    def current(self) -> MarketReport:
        return self.report or self.refresh()

    def summary(self) -> dict:
        r = self.current()
        writer = next((t for t in r.trace if t["agent"] == "redacteur"), None)
        return {
            "as_of": r.as_of.isoformat(),
            "seed": self.seed,
            "llm": self.use_llm,
            "llm_status": None if writer is None else {"status": writer["status"], "error": writer["error"]},
            "disclaimer": DISCLAIMER,
            "index": {"close": r.index.last_close, "week": r.index.week_return,
                      "short": r.index.short.label, "medium": r.index.medium.label},
            "agents": summarize_trace(r.trace),
            "tickers": [
                {
                    "ticker": t.security.ticker,
                    "name": t.security.name,
                    "sector": t.security.sector,
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
                if path.startswith("/api/stock/"):
                    ticker = path.rsplit("/", 1)[-1].upper()
                    t = next((x for x in state.current().tickers if x.security.ticker == ticker), None)
                    if t is None:
                        return self._json({"error": f"titre inconnu : {ticker}"}, HTTPStatus.NOT_FOUND)
                    return self._send(200, html_stock_header(t) + html_stock_detail(t), "text/html; charset=utf-8")
                if path == "/api/export":
                    r = state.current()
                    name = f"analyse-sp500-{r.as_of.isoformat()}.html"
                    return self._send(200, render_html(r), "text/html; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="{name}"'})
                return self._json({"error": "introuvable"}, HTTPStatus.NOT_FOUND)
            except Exception as e:  # noqa: BLE001 — l'erreur est renvoyée à l'interface
                return self._json({"error": f"{type(e).__name__}: {e}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self):
            if not self._authorized():
                return self._json({"error": "jeton invalide"}, HTTPStatus.FORBIDDEN)
            if urlparse(self.path).path != "/api/refresh":
                return self._json({"error": "introuvable"}, HTTPStatus.NOT_FOUND)
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                params = json.loads(self.rfile.read(length) or b"{}")
                as_of = date.fromisoformat(params["as_of"]) if params.get("as_of") else None
                seed = int(params["seed"]) if params.get("seed") not in (None, "") else None
                state.refresh(as_of, seed, bool(params.get("llm", False)))
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
