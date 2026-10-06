"""Univers d'actions du S&P 500 suivies et profils de sensibilité sectoriels."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Security


@dataclass(frozen=True)
class SecurityProfile:
    """Paramètres utilisés par le générateur de données simulées."""

    security: Security
    price: float  # cours approximatif visé en fin d'historique
    vol: float  # volatilité annualisée
    drift: float  # tendance annualisée
    popularity: int  # volume relatif de discussions sur les réseaux sociaux (1-10)
    avg_volume: int


def _p(ticker, name, sector, beta, price, vol, drift, popularity, avg_volume):
    return SecurityProfile(Security(ticker, name, sector, beta), price, vol, drift, popularity, avg_volume)


SP500_SAMPLE: list[SecurityProfile] = [
    _p("AAPL", "Apple", "Technology", 1.10, 238.0, 0.24, 0.12, 9, 52_000_000),
    _p("MSFT", "Microsoft", "Technology", 1.00, 512.0, 0.22, 0.15, 7, 21_000_000),
    _p("NVDA", "Nvidia", "Technology", 1.60, 182.0, 0.45, 0.35, 10, 190_000_000),
    _p("AVGO", "Broadcom", "Technology", 1.30, 335.0, 0.38, 0.30, 5, 22_000_000),
    _p("AMD", "Advanced Micro Devices", "Technology", 1.70, 158.0, 0.48, 0.05, 8, 45_000_000),
    _p("INTC", "Intel", "Technology", 1.20, 29.0, 0.42, -0.10, 6, 70_000_000),
    _p("GOOGL", "Alphabet", "Communication Services", 1.05, 246.0, 0.28, 0.20, 6, 30_000_000),
    _p("META", "Meta Platforms", "Communication Services", 1.25, 760.0, 0.33, 0.18, 8, 14_000_000),
    _p("NFLX", "Netflix", "Communication Services", 1.15, 1215.0, 0.32, 0.22, 5, 4_000_000),
    _p("DIS", "Walt Disney", "Communication Services", 1.05, 113.0, 0.26, -0.02, 4, 9_000_000),
    _p("AMZN", "Amazon", "Consumer Discretionary", 1.20, 228.0, 0.30, 0.14, 8, 42_000_000),
    _p("TSLA", "Tesla", "Consumer Discretionary", 2.00, 410.0, 0.60, 0.10, 10, 95_000_000),
    _p("HD", "Home Depot", "Consumer Discretionary", 1.00, 405.0, 0.22, 0.04, 3, 3_500_000),
    _p("JPM", "JPMorgan Chase", "Financials", 1.05, 305.0, 0.22, 0.16, 4, 9_000_000),
    _p("BAC", "Bank of America", "Financials", 1.20, 50.0, 0.25, 0.10, 4, 38_000_000),
    _p("GS", "Goldman Sachs", "Financials", 1.30, 770.0, 0.28, 0.18, 3, 2_200_000),
    _p("V", "Visa", "Financials", 0.90, 342.0, 0.18, 0.08, 3, 6_500_000),
    _p("UNH", "UnitedHealth", "Health Care", 0.80, 330.0, 0.35, -0.15, 5, 11_000_000),
    _p("JNJ", "Johnson & Johnson", "Health Care", 0.55, 176.0, 0.16, 0.06, 3, 7_500_000),
    _p("PFE", "Pfizer", "Health Care", 0.65, 25.0, 0.24, -0.05, 4, 40_000_000),
    _p("LLY", "Eli Lilly", "Health Care", 0.70, 790.0, 0.34, 0.10, 6, 3_800_000),
    _p("XOM", "Exxon Mobil", "Energy", 0.85, 114.0, 0.24, 0.02, 3, 15_000_000),
    _p("CVX", "Chevron", "Energy", 0.90, 158.0, 0.25, 0.01, 3, 8_000_000),
    _p("CAT", "Caterpillar", "Industrials", 1.15, 460.0, 0.28, 0.20, 3, 2_800_000),
    _p("BA", "Boeing", "Industrials", 1.40, 215.0, 0.36, 0.08, 6, 8_500_000),
    _p("WMT", "Walmart", "Consumer Staples", 0.55, 102.0, 0.17, 0.18, 4, 17_000_000),
    _p("KO", "Coca-Cola", "Consumer Staples", 0.55, 68.0, 0.14, 0.03, 2, 14_000_000),
    _p("PG", "Procter & Gamble", "Consumer Staples", 0.45, 155.0, 0.15, -0.02, 2, 7_000_000),
    _p("NEE", "NextEra Energy", "Utilities", 0.70, 74.0, 0.26, 0.05, 2, 10_000_000),
    _p("AMT", "American Tower", "Real Estate", 0.85, 198.0, 0.26, -0.03, 2, 2_500_000),
]

INDEX = Security("^GSPC", "S&P 500", "Index", 1.0)

# --------------------------------------------------------------------- Focus IA
# Titres liés à l'intelligence artificielle, hors échantillon S&P 500 (données réelles
# seulement : pas de profil simulé). Le bêta indiqué est une estimation grossière, informative.
AI_EXTRA: list[Security] = [
    Security("TSM", "Taiwan Semiconductor", "Technology", 1.2),
    Security("ARM", "Arm Holdings", "Technology", 1.8),
    Security("MU", "Micron Technology", "Technology", 1.5),
    Security("SMCI", "Super Micro Computer", "Technology", 2.0),
    Security("VRT", "Vertiv", "Industrials", 1.7),
    Security("ANET", "Arista Networks", "Technology", 1.4),
    Security("NBIS", "Nebius Group", "Technology", 2.2),
    Security("CRWV", "CoreWeave", "Technology", 2.5),
    Security("IREN", "IREN", "Technology", 2.8),
    Security("CIFR", "Cipher Mining", "Technology", 2.8),
    Security("WULF", "TeraWulf", "Technology", 2.8),
    Security("APLD", "Applied Digital", "Technology", 2.6),
    Security("CORZ", "Core Scientific", "Technology", 2.4),
    Security("PLTR", "Palantir", "Technology", 2.0),
    Security("AI", "C3.ai", "Technology", 2.0),
    Security("SOUN", "SoundHound AI", "Technology", 2.6),
    Security("BBAI", "BigBear.ai", "Technology", 2.6),
    Security("PATH", "UiPath", "Technology", 1.6),
    Security("CBRS", "Cerebras Systems", "Technology", 2.5),
    Security("AIP", "Arteris", "Technology", 1.8),
    Security("ORCL", "Oracle", "Technology", 1.3),
]

#: Autres titres suivis à la demande (hors S&P 500 et hors focus IA) : univers « tout » seulement.
OTHER_EXTRA: list[Security] = [
    Security("FIGR", "Figure Technology Solutions", "Financials", 2.0),
    Security("SHMD", "SCHMID Group", "Technology", 1.5),
]

#: Sous-thème de chaque titre du focus IA
AI_THEME: dict[str, str] = {
    "NVDA": "Puces", "AMD": "Puces", "AVGO": "Puces", "TSM": "Puces", "ARM": "Puces", "MU": "Puces (mémoire)",
    "SMCI": "Serveurs", "VRT": "Énergie / refroidissement", "ANET": "Réseau",
    "MSFT": "Hyperscaler", "GOOGL": "Hyperscaler", "META": "Hyperscaler", "AMZN": "Hyperscaler",
    "NBIS": "Néocloud", "CRWV": "Néocloud", "IREN": "Néocloud / ex-mineur", "CIFR": "Ex-mineur → HPC",
    "WULF": "Ex-mineur → HPC", "APLD": "Data centers HPC", "CORZ": "Ex-mineur → HPC",
    "PLTR": "Logiciel IA", "AI": "Logiciel IA", "SOUN": "Logiciel IA", "BBAI": "Logiciel IA",
    "PATH": "Automatisation", "CBRS": "Puces (accélérateurs IA)",
    "AIP": "IP de puces (interconnexions NoC)",
    "ORCL": "Cloud / data centers IA",
}


@dataclass(frozen=True)
class Link:
    """Société liée dont l'actualité compte aussi pour un titre (client, fournisseur, partenaire).

    `entity` : symbole d'un titre suivi (ex. MSFT) ou clé d'une société non cotée suivie par
    ses news (ENTITY_QUERIES, ex. OPENAI). `weight` : poids de ses news dans le sentiment du
    titre (1 = autant que les news du titre lui-même). Le lien joue dans les deux sens : une
    news négative sur la société liée pèse aussi négativement."""

    entity: str
    name: str
    relation: str
    weight: float


#: Liens entre sociétés (faits publics, à tenir à jour ; poids fixés à la main, non validés).
LINKS: dict[str, list[Link]] = {
    "CBRS": [Link("OPENAI", "OpenAI", "client principal : > 20 Md$ de calcul 2026-2028, bons sur ~10 % du capital", 0.5)],
    "CRWV": [Link("OPENAI", "OpenAI", "client majeur (contrats pluriannuels)", 0.3),
             Link("MSFT", "Microsoft", "client majeur", 0.3),
             Link("NVDA", "Nvidia", "fournisseur et actionnaire", 0.2)],
    "ORCL": [Link("OPENAI", "OpenAI", "client majeur : contrat de calcul pluriannuel (Stargate)", 0.4)],
    "NBIS": [Link("MSFT", "Microsoft", "client majeur (contrat pluriannuel, 2025)", 0.3)],
    "IREN": [Link("MSFT", "Microsoft", "client majeur (contrat de capacité IA, 2025)", 0.3)],
    "AMD": [Link("OPENAI", "OpenAI", "client (accord de puces 2025, bons OpenAI sur AMD)", 0.2)],
    "AVGO": [Link("OPENAI", "OpenAI", "client (puces sur mesure, 2025)", 0.2)],
    "NVDA": [Link("OPENAI", "OpenAI", "client et partenaire d'investissement (2025)", 0.15)],
}


def _securities() -> dict[str, Security]:
    return ({p.security.ticker: p.security for p in SP500_SAMPLE} | {s.ticker: s for s in AI_EXTRA}
            | {s.ticker: s for s in OTHER_EXTRA})


#: Univers analysables : échantillon S&P 500, focus IA, ou les deux.
UNIVERSES: dict[str, list[Security]] = {
    "sp500": [p.security for p in SP500_SAMPLE],
    "ia": [_securities()[t] for t in AI_THEME],
    "tout": list(_securities().values()),
}
#: Titres hors S&P 500 à télécharger en plus (cours, news, réseaux sociaux)
EXTRA_TICKERS: list[str] = [s.ticker for s in AI_EXTRA + OTHER_EXTRA]


# Sensibilité de chaque secteur aux facteurs macro (valeurs dans [-1, 1]).
#   rates    : > 0 = profite d'une baisse des taux longs
#   oil      : > 0 = profite d'une hausse du pétrole
#   cyclical : > 0 = profite d'une accélération de l'activité (PMI, emploi)
#   curve    : > 0 = profite d'une pentification de la courbe des taux
SECTOR_PROFILE: dict[str, dict[str, float]] = {
    "Technology": {"rates": 0.8, "oil": -0.2, "cyclical": 0.6, "curve": 0.1},
    "Communication Services": {"rates": 0.6, "oil": -0.2, "cyclical": 0.5, "curve": 0.1},
    "Consumer Discretionary": {"rates": 0.5, "oil": -0.5, "cyclical": 0.8, "curve": 0.2},
    "Financials": {"rates": -0.4, "oil": 0.0, "cyclical": 0.7, "curve": 1.0},
    "Health Care": {"rates": 0.2, "oil": -0.1, "cyclical": -0.2, "curve": 0.0},
    "Energy": {"rates": -0.1, "oil": 1.0, "cyclical": 0.5, "curve": 0.1},
    "Industrials": {"rates": 0.3, "oil": -0.3, "cyclical": 0.9, "curve": 0.2},
    "Consumer Staples": {"rates": 0.3, "oil": -0.3, "cyclical": -0.4, "curve": 0.0},
    "Utilities": {"rates": 1.0, "oil": -0.1, "cyclical": -0.5, "curve": -0.1},
    "Real Estate": {"rates": 1.0, "oil": -0.1, "cyclical": 0.3, "curve": 0.1},
    "Index": {"rates": 0.5, "oil": -0.2, "cyclical": 0.6, "curve": 0.2},
}

# Fiabilité éditoriale des sources (0 = inconnue / non vérifiée, 1 = agence de référence).
SOURCE_RELIABILITY: dict[str, float] = {
    "Reuters": 0.95,
    "Bloomberg": 0.95,
    "WSJ": 0.9,
    "Financial Times": 0.9,
    "CNBC": 0.8,
    "MarketWatch": 0.75,
    "STAT": 0.8,
    "FiercePharma": 0.75,
    "Barron's": 0.8,
    "Seeking Alpha": 0.5,
    "StockBuzzDaily": 0.25,
    # Sources des vraies news (GDELT, voir providers/realnews.py).
    "Associated Press": 0.9,
    "The Economist": 0.9,
    "New York Times": 0.85,
    "BBC": 0.85,
    "Washington Post": 0.8,
    "Morningstar": 0.75,
    "Axios": 0.75,
    "CNN": 0.75,
    "Los Angeles Times": 0.75,
    "The Guardian": 0.75,
    "Fortune": 0.7,
    "Investor's Business Daily": 0.7,
    "Yahoo Finance": 0.7,
    "TechCrunch": 0.7,
    "The Verge": 0.7,
    "Fox Business": 0.65,
    "Forbes": 0.6,
    "Business Insider": 0.6,
    "Nasdaq": 0.6,
    "Business Wire": 0.6,  # communiqués des entreprises : factuels mais ton toujours favorable
    "PR Newswire": 0.6,
    "GlobeNewswire": 0.6,
    "TheStreet": 0.55,
    "Investing.com": 0.55,
    "Benzinga": 0.5,
    "The Motley Fool": 0.45,
    "Zacks": 0.45,
    "SEC EDGAR": 1.0,
}
# Sources factuelles sans ton (dépôts réglementaires) : elles expliquent un mouvement de prix
# mais n'entrent pas dans la moyenne du sentiment, qu'elles tireraient artificiellement vers 0.
EVENT_SOURCES = frozenset({"SEC EDGAR"})
DEFAULT_RELIABILITY = 0.3
RELIABLE_THRESHOLD = 0.7  # source suffisante pour confirmer une info
UNRELIABLE_THRESHOLD = 0.4  # en dessous : info exclue si non confirmée


def source_reliability(source: str) -> float:
    return SOURCE_RELIABILITY.get(source, DEFAULT_RELIABILITY)
