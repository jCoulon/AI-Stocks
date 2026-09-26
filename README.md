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

Python ≥ 3.10, aucune dépendance externe (sauf `anthropic` pour l'agent rédacteur optionnel).

```bash
python -m sp500_analyzer                      # rapport complet dans le terminal
python -m sp500_analyzer -t NVDA -t META      # uniquement ces titres, avec le détail des signaux
python -m sp500_analyzer --detail UNH         # rapport complet + détail d'un titre
python -m sp500_analyzer --html rapport.html  # rapport HTML autonome (clair/sombre, mobile)
python -m sp500_analyzer --json rapport.json  # export complet pour d'autres outils
python -m sp500_analyzer --seed 7             # autre jeu de données simulées
```

Tests : `python -m unittest discover -s tests`

## Architecture multi-agents

L'analyse est confiée à une **équipe d'agents spécialisés** coordonnés par un
**orchestrateur** (`orchestrator.py`). Les agents ne s'appellent pas entre eux : chacun
publie son résultat sur un **tableau partagé** (*blackboard*) et lit ceux de ses dépendances.

| Agent | Rôle | Dépend de |
|---|---|---|
| `collecteur` | Rassemble cours, news et messages sociaux d'un titre | — |
| `economiste` | Lit les séries macro, produit une vue par secteur | — |
| `controleur` | Audite la qualité et recoupe les sources ; fixe les consignes (news exclues, poids du social, confiance dans les cours) | collecteur |
| `technicien` | Analyse les graphiques (tendance, momentum, volumes, force relative) | collecteur (titre + indice) |
| `sentiment` | Mesure le ton des news fiables et du social, **selon les consignes du contrôleur** | controleur |
| `strategiste` | Confronte les avis et rend le verdict court / moyen terme | technicien, controleur, *economiste*, *sentiment* |
| `chef-strategiste` | Agrège : indice, largeur de marché, news macro | strategiste (indice), *tous les titres* |
| `redacteur` (option `--llm`) | Claude rédige une synthèse en français à partir des seules conclusions chiffrées | chef-strategiste |

*En italique : dépendances facultatives.*

L'orchestrateur :

- **planifie** un graphe de tâches (≈ 5 tâches par titre, 157 pour l'univers complet) ;
- **exécute en parallèle** toute tâche dont les dépendances sont prêtes (`--workers`) — le résultat est identique à une exécution séquentielle ;
- **retente** une tâche en échec (erreur passagère) ;
- **dégrade proprement** : si un agent facultatif échoue (ex. sentiment), l'avis est rendu sans ce pilier avec une alerte `AGENT_FAILURE` et une confiance réduite ; si une donnée indispensable manque pour un titre, seul ce titre est retiré du rapport ;
- **journalise** chaque tâche (statut, tentatives, durée, erreur) : `--trace`, ou `-v` pour suivre en direct.

```bash
python -m sp500_analyzer --trace            # rapport + journal des agents
python -m sp500_analyzer -v -t NVDA         # avancement des agents en direct

pip install anthropic                       # facultatif : agent rédacteur
export ANTHROPIC_API_KEY=...
python -m sp500_analyzer --llm              # ajoute la synthèse rédigée par Claude
```

Sans le paquet `anthropic` ou sans clé, l'agent rédacteur est simplement marqué
« annulé » et le reste du rapport est produit normalement. Les calculs restent
déterministes : Claude ne fait que mettre en mots les conclusions des autres agents.

Pour ajouter un agent : hériter de `agents.base.Agent`, implémenter `run(task, board)`,
puis l'enregistrer dans l'orchestrateur et l'insérer dans `Orchestrator.plan`.

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
  orchestrator.py       Plan des tâches, exécution parallèle, reprises, journal
  agents/base.py        Contrat d'agent, tâche, tableau partagé
  agents/specialists.py Agents collecteur, économiste, contrôleur, technicien, sentiment, stratégistes
  agents/writer.py      Agent rédacteur (Claude, optionnel)
  providers/base.py     Interface DataProvider (à implémenter pour de vraies données)
  providers/mock.py     Données simulées déterministes (cours, news, social, macro)
  analysis/indicators.py  Indicateurs techniques (pur Python)
  analysis/technical.py   Pilier technique
  analysis/sentiment.py   Pilier sentiment (lexique financier, fiabilité des sources)
  analysis/macro.py       Pilier macro + sensibilités sectorielles
  analysis/coherence.py   Contrôles de qualité et recoupement des sources
  analysis/scoring.py     Pondération des piliers, confiance, fourchettes
  engine.py             Point d'entrée programmatique (run_analysis)
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
