# -*- mode: python ; coding: utf-8 -*-
# Spécification PyInstaller de l'application macOS. Lancer via packaging/macos/build.sh.
import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
VERSION = os.environ.get("APP_VERSION", "0.1.0")

hidden = collect_submodules("sp500_analyzer")
try:  # agent rédacteur (optionnel) : embarqué s'il est installé
    import anthropic  # noqa: F401

    hidden += collect_submodules("anthropic")
except ImportError:
    pass

# Instantané des données réelles (dossier data/ du dépôt) embarqué dans l'application : cours
# quotidiens, news, réseaux sociaux, macro et fondamentaux. Les barres intraday et les fenêtres
# de téléchargement brutes ne sont pas utiles à l'analyse et restent en dehors.
DATA = os.path.join(ROOT, "data")
data_files = []
for sub in ("daily", "news", "news/google", "news/rss", "social/stocktwits", "social/reddit", "macro",
            "fundamentals", "sec"):
    folder = os.path.join(DATA, sub)
    if os.path.isdir(folder) and any(f.endswith((".csv", ".json")) for f in os.listdir(folder)):
        for ext in ("*.csv", "*.json"):
            if any(f.endswith(ext[1:]) for f in os.listdir(folder)):
                data_files.append((os.path.join(folder, ext), os.path.join("data", sub)))

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "sp500_analyzer", "app", "ui.html"), "sp500_analyzer/app")] + data_files,
    hiddenimports=hidden,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SP500 Analyzer",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SP500 Analyzer")
app = BUNDLE(
    coll,
    name="SP500 Analyzer.app",
    icon=os.environ.get("APP_ICON"),
    bundle_identifier="com.aistocks.sp500analyzer",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "S&P 500 Analyzer",
        "CFBundleShortVersionString": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.finance",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Outil d'analyse — pas un conseil en investissement.",
        # L'interface est servie par un serveur local (127.0.0.1) intégré à l'application.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
