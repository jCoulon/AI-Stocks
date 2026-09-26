# AI-Stocks — Analyseur des mouvements du S&P 500

Outil d'**analyse de données de marché** qui croise quatre familles de sources pour
chaque action du S&P 500 :

| Pilier | Données | Exemples d'indicateurs |
|---|---|---|
| **Technique** (charts) | Cours OHLCV journaliers | RSI, MACD, EMA20, SMA50/200, Bollinger, volumes, force relative vs S&P |
| **Sentiment** | News + réseaux sociaux | Ton des titres pondéré par la fiabilité de la source et la fraîcheur, ton social, buzz |
| **Macro / éco** | Taux, inflation, emploi, PMI, pétrole, VIX, put/call, AAII | Régime de marché, sensibilité sectorielle (taux, pétrole, cycle, courbe) |
| **Cohérence** | Toutes les sources | Contrôle qualité et recoupement des sources (voir ci-dessous) |

Il produit un **avis à court terme (1-2 semaines)** et **à moyen terme (1-3 mois)** :
un score de -1 (baissier) à +1 (haussier), un libellé, un **niveau de confiance** et
une fourchette de cours indicative.

> ⚠️ **Ce n'est pas un conseil en investissement.** L'outil résume des indicateurs
> statistiques ; il ne prédit pas le marché. La confiance est volontairement plafonnée à 80 %.
>
> ⚠️ **Les données actuelles sont SIMULÉES** (semaine du 21 au 25 septembre 2026).

## Démarrage rapide

Python ≥ 3.10, aucune dépendance externe.

```bash
python -m sp500_analyzer                      # rapport complet dans le terminal
python -m sp500_analyzer -t NVDA -t META      # uniquement ces titres, avec le détail des signaux
python -m sp500_analyzer --detail UNH         # rapport complet + détail d'un titre
python -m sp500_analyzer --html rapport.html  # rapport HTML autonome (clair/sombre, mobile)
python -m sp500_analyzer --json rapport.json  # export complet pour d'autres outils
python -m sp500_analyzer --seed 7             # autre jeu de données simulées
```

Tests : `python -m unittest discover -s tests`

## Le moteur de cohérence

Le but est de ne retenir que les données **cohérentes entre elles** et d'abaisser la
confiance quand les sources se contredisent :

| Contrôle | Alerte | Effet |
|---|---|---|
| Séances manquantes, OHLC incohérent, cours périmés | `MISSING_BARS`, `OHLC_INCONSISTENT`, `STALE_PRICES` | Baisse de la qualité des données |
| Mouvement > 4σ ou volume ×2,5 sans news fiable | `UNEXPLAINED_MOVE` | Poids du pilier technique réduit |
| Info rapportée uniquement par une source peu fiable, non recoupée sous 48 h | `UNCONFIRMED_RUMOR` | News exclue du calcul |
| Messages quasi identiques martelés par des comptes récents | `SUSPECTED_BOTS` | Poids des réseaux sociaux réduit |
| Engouement social sans news fiable | `HYPE_WITHOUT_CONFIRMATION` | Baisse de la cohérence |
| Réaction du prix le jour de la news à l'inverse de son ton | `PRICE_NEWS_DIVERGENCE` | Baisse de la cohérence |
| Réaction du prix dans le sens de la news | `CONFIRMED_BY_NEWS` | Information |

La **confiance** combine l'accord entre piliers, l'intensité du signal, la qualité des
données et la cohérence des sources.

## Scénarios simulés de la semaine dernière

Les cours de la semaine du 21 au 25/09/2026 sont fictifs et scénarisés pour exercer le moteur :

- **Fed** : statu quo mercredi, ton accommodant → taux longs en baisse ; **OPEC+** → pétrole en hausse.
- **NVDA, JPM, LLY, AAPL, XOM** : hausse confirmée par des news de sources fiables.
- **TSLA, PFE, BA** : baisse confirmée (guidance réduite, essai clinique arrêté, inspections FAA).
- **UNH** : news négative (enquête DOJ) mais titre en hausse → divergence.
- **AMD** : +8 % sans aucune news → mouvement inexpliqué.
- **META** : rumeur d'un site peu fiable + campagne de comptes récents → rumeur exclue, social dévalué.
- **INTC** : séance du mardi absente du flux de cours.

## Architecture

```
sp500_analyzer/
  providers/base.py     Interface DataProvider (à implémenter pour de vraies données)
  providers/mock.py     Données simulées déterministes (cours, news, social, macro)
  analysis/indicators.py  Indicateurs techniques (pur Python)
  analysis/technical.py   Pilier technique
  analysis/sentiment.py   Pilier sentiment (lexique financier, fiabilité des sources)
  analysis/macro.py       Pilier macro + sensibilités sectorielles
  analysis/coherence.py   Contrôles de qualité et recoupement des sources
  analysis/scoring.py     Pondération des piliers, confiance, fourchettes
  engine.py             Orchestration
  report.py             Rendu terminal / JSON / HTML
  universe.py           30 valeurs du S&P 500, profils sectoriels, fiabilité des sources
```

Poids des piliers (`analysis/scoring.py`) :

| Horizon | Technique | Sentiment | Macro |
|---|---|---|---|
| Court terme | 50 % | 30 % | 20 % |
| Moyen terme | 45 % | 15 % | 40 % |

## Brancher de vraies données

Implémenter `DataProvider` (`providers/base.py`) : `price_history`, `news`,
`social_posts`, `macro`, `trading_days`, `universe`, `index`. Par exemple : une API de
cours, un flux de news, l'API d'un réseau social, et FRED pour la macro. Le reste du
pipeline ne change pas.
