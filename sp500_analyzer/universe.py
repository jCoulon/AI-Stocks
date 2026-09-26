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
}
DEFAULT_RELIABILITY = 0.3
RELIABLE_THRESHOLD = 0.7  # source suffisante pour confirmer une info
UNRELIABLE_THRESHOLD = 0.4  # en dessous : info exclue si non confirmée


def source_reliability(source: str) -> float:
    return SOURCE_RELIABILITY.get(source, DEFAULT_RELIABILITY)
