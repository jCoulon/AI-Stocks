"""Lanceur de l'application de bureau.

- Sur macOS (ou partout où `pywebview` est installé) : fenêtre native (WebKit).
- Sinon, ou avec --browser : ouvre l'interface dans le navigateur par défaut.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import webbrowser
from pathlib import Path

from .server import AppServer, AppState

APP_NAME = "S&P 500 Analyzer"


class DesktopApi:
    """Fonctions natives exposées à l'interface (window.pywebview.api)."""

    def __init__(self, server: AppServer):
        self._server = server
        self._window = None

    def attach(self, window) -> None:
        self._window = window

    def choose_data_dir(self) -> str | None:
        """Choisir le dossier des données réelles (celui du dépôt, rempli par les workflows)."""
        import webview

        result = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(Path.home()))
        if not result:
            return None
        path = Path(result if isinstance(result, str) else result[0])
        if not (path / "daily" / "SPX.csv").exists() and (path / "data" / "daily" / "SPX.csv").exists():
            path = path / "data"  # dossier du dépôt choisi : on descend dans data/
        if not (path / "daily" / "SPX.csv").exists():
            raise ValueError(f"{path} ne contient pas de données (daily/SPX.csv introuvable)")
        self._server.state.set_data_dir(path)
        return str(path)

    def save_report(self) -> str | None:
        import webview

        from ..report import render_html

        report = self._server.state.current()
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(Path.home() / "Documents"),
            save_filename=f"analyse-{self._server.state.universe}-{report.as_of.isoformat()}.html",
        )
        if not result:
            return None
        path = result if isinstance(result, str) else result[0]
        Path(path).write_text(render_html(report), encoding="utf-8")
        return path


def find_data_dir(explicit: str | None = None) -> Path | None:
    """Dossier des données réelles : argument, variable SP500_DATA, copie embarquée dans
    l'application, ~/AI-Stocks/data, ou data/ du dépôt quand l'application tourne depuis les sources."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "data" if getattr(sys, "frozen", False) else None
    candidates = [explicit, os.environ.get("SP500_DATA"), bundled, Path.home() / "AI-Stocks" / "data",
                  Path(__file__).resolve().parents[2] / "data"]
    for c in candidates:
        if c and (Path(c) / "daily" / "SPX.csv").exists():
            return Path(c)
    return None


def self_test(server: AppServer) -> int:
    """Vérifie que le serveur répond et que l'analyse aboutit (utilisé par la CI macOS)."""
    headers = {"X-App-Token": server.token}

    def get(path: str) -> bytes:
        req = urllib.request.Request(server.url.rstrip("/") + path, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    page = get("/").decode()
    summary = json.loads(get("/api/summary"))
    stock = get(f"/api/stock/{summary['tickers'][0]['ticker']}").decode()
    if not ("initCharts" in page and summary["tickers"] and "pricechart" in stock):
        print("ÉCHEC du test : réponse inattendue de l'interface ou de l'API", file=sys.stderr)
        return 1
    source = "données réelles, " + summary["universe_label"] if summary["source"] == "reel" else "données simulées"
    if summary["asymmetry"] and "Écran d'asymétrie" not in get("/api/asymmetry").decode():
        print("ÉCHEC du test : écran d'asymétrie indisponible", file=sys.stderr)
        return 1
    print(f"OK — {len(summary['tickers'])} titres analysés ({source}), interface servie sur {server.url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sp500-analyzer-app", description=f"{APP_NAME} — application de bureau")
    parser.add_argument("--browser", action="store_true", help="Ouvrir dans le navigateur plutôt qu'en fenêtre native")
    parser.add_argument("--no-open", action="store_true", help="(avec --browser) ne pas ouvrir de navigateur")
    parser.add_argument("--port", type=int, default=0, help="Port local (défaut : choisi automatiquement)")
    parser.add_argument("--self-test", action="store_true", help="Démarrer, vérifier l'API puis quitter")
    parser.add_argument("--donnees", metavar="DOSSIER", help="Dossier des données réelles (défaut : détection auto)")
    parser.add_argument("--simule", action="store_true", help="Démarrer sur les données simulées")
    args = parser.parse_args(argv)

    data_dir = find_data_dir(args.donnees)
    state = AppState(data_dir=data_dir)
    if args.simule:
        state.source, state.universe = "simule", "sp500"
    server = AppServer(state, port=args.port).start()
    try:
        if args.self_test:
            return self_test(server)

        if not args.browser:
            try:
                import webview
            except ImportError:
                print("pywebview non installé : ouverture dans le navigateur (pip install pywebview)", file=sys.stderr)
            else:
                api = DesktopApi(server)
                window = webview.create_window(
                    APP_NAME, server.url, js_api=api, width=1320, height=880, min_size=(900, 600),
                )
                api.attach(window)
                webview.start()
                return 0

        print(f"{APP_NAME} disponible sur {server.url} (Ctrl+C pour quitter)")
        if not args.no_open:
            webbrowser.open(server.url)
        try:
            server._thread.join()
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
