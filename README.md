# AI-Stocks — Analyseur des mouvements du S&P 500

Outil d'**analyse de données de marché** qui croise quatre familles de sources pour
chaque action du S&P 500 :

| Pilier | Données | Exemples d'indicateurs |
|---|---|---|
| **Technique** (charts) | Cours OHLCV journaliers | RSI, MACD, EMA20, SMA50/200, Bollinger, volumes, force relative vs S&P |
| **Sentiment** | News + réseaux sociaux | Ton des titres pondéré par la fiabilité de la source et la fraîcheur, ton social, buzz |
| **Macro / éco** | Taux, inflation, emploi, PMI, pétrole, VIX, put/call, AAII | Régime de marché, sensibilité sectorielle (taux, pétrole, cycle, courbe) |
| **Recherche** | Cours, volumes, news retenues, social | Facteurs publiés : momentum, retournement, plus haut 52 sem., volatilité idiosyncratique, effet MAX, prime de volume, dérive après news, attention, GARCH… ([méthodologie](docs/METHODOLOGIE.md)) |
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
python -m sp500_analyzer --detail UNH         # rapport complet + fiche d'un titre
python -m sp500_analyzer -s NVDA -s TSLA      # analyse par action : uniquement les fiches
python -m sp500_analyzer --html rapport.html  # rapport HTML autonome (clair/sombre, mobile)
python -m sp500_analyzer --json rapport.json  # export complet pour d'autres outils
python -m sp500_analyzer --seed 7             # autre jeu de données simulées
python -m sp500_analyzer --backtest           # validation point-in-time des facteurs de recherche
```

Tests : `python -m unittest discover -s tests`

## Application Mac

L'analyseur existe aussi en **application de bureau** : fenêtre native macOS (WebKit),
liste des 30 titres avec recherche et tri, vue marché, fiche détaillée de chaque action
avec graphique interactif, avis de Claude à la demande, relance de l'analyse (date, jeu
de données) et export du rapport HTML. Navigation au clavier : `↑` / `↓` pour changer de titre,
`/` pour rechercher, `⌘R` pour relancer l'analyse.

### Installer la version construite

Chaque push construit l'application sur un runner macOS (GitHub Actions, workflow
*Application macOS*) et publie `SP500-Analyzer-macOS-arm64.dmg` dans les artefacts du run.

1. Télécharger l'artefact, ouvrir le `.dmg`, glisser **SP500 Analyzer** dans *Applications*.
2. L'application est signée ad hoc mais **non notariée** par Apple : au premier lancement,
   faire clic droit → **Ouvrir** → **Ouvrir** (ou `xattr -dr com.apple.quarantine "/Applications/SP500 Analyzer.app"`).

La version construite cible les Mac Apple Silicon (M1 et suivants).

### Construire soi-même (sur un Mac)

```bash
pip install ".[app,llm]" pyinstaller
bash packaging/macos/build.sh        # → dist/SP500 Analyzer.app et dist/SP500-Analyzer-macOS-<arch>.dmg
```

### Lancer sans empaqueter

```bash
pip install ".[app]"                 # pywebview
python -m sp500_analyzer.app         # fenêtre native
python -m sp500_analyzer.app --browser   # ou dans le navigateur (tout système)
```

### Avis de Claude (bouton)

Chaque fiche d'action, ainsi que la vue marché, propose un bouton **« Demander l'avis de
Claude »**. Claude reçoit le dossier complet produit par les agents (avis de l'outil, signaux
de chaque pilier, facteurs de recherche, alertes de cohérence, niveaux clés, news, pairs,
contexte de marché) et rédige un **second avis argumenté**, affiché au fil de l'eau :
verdict court et moyen terme avec sa conviction, ce qui soutient le titre, ce qui inquiète,
ce qu'il surveillerait, et s'il est d'accord ou non avec l'outil. Il ne dispose d'aucune
autre source que ce dossier.

- **Payant, uniquement sur demande** : un appel à l'API Anthropic (`claude-opus-5`) par clic,
  de l'ordre de quelques centimes de dollar selon la longueur de la réflexion.
- **Mis en cache** pour l'analyse en cours : revenir sur la fiche ne coûte rien ;
  « Régénérer » relance un appel. Une nouvelle analyse invalide le cache.
- **Arrêter** interrompt l'appel en cours.
- **Clé API** : lue dans `ANTHROPIC_API_KEY` ou le profil `ant auth login`. Une application
  lancée depuis le Finder ne voit pas les variables du terminal : si aucune clé n'est trouvée,
  l'application propose de la coller ; elle est gardée en mémoire le temps de la session,
  jamais écrite sur disque.

Sécurité : l'interface est servie par un serveur interne qui n'écoute que sur
`127.0.0.1`. L'API exige un jeton de session propre à chaque lancement et un en-tête
`Host` local, pour qu'aucune page web ne puisse piloter l'application ni déclencher
d'appels payants à Claude.

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
| `strategiste` | Confronte les avis et rend le verdict court / moyen terme | technicien, controleur, *economiste*, *sentiment*, *chercheur* |
| `chercheur` | Calcule les facteurs académiques et les classe dans l'univers ; régime (ratio de variance), GARCH | collecteur (indice), *collecteurs et contrôleurs de tous les titres* |
| `chef-strategiste` | Agrège : indice, largeur de marché, news macro | strategiste (indice), *tous les titres* |
| `analyste-titre` | Rédige la fiche détaillée de chaque action (voir ci-dessous) | chef-strategiste, collecteur, controleur |
| `redacteur` (option `--llm`) | Claude rédige une synthèse en français à partir des seules conclusions chiffrées | chef-strategiste |

*En italique : dépendances facultatives.*

L'orchestrateur :

- **planifie** un graphe de tâches (6 tâches par titre, 188 pour l'univers complet) ;
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

## Analyse par action

`python -m sp500_analyzer -s META` affiche la fiche complète d'un titre ; dans le rapport
HTML, chaque titre a la sienne (ouverte d'office quand on cible 3 titres ou moins) :

- **Thèse** : avis court / moyen terme, pilier qui pèse le plus, rang dans le secteur, prudence si données incohérentes.
- **Points forts / risques** : signaux propres au titre en priorité (le contexte macro, commun à tous, en appoint),
  catalyseurs confirmés par la réaction du cours, alertes de données, proximité d'une résistance, volatilité élevée.
- **Performance** sur 1 semaine, 1 / 3 / 6 mois, 1 an, en absolu et relative au S&P 500.
- **Risque** : volatilité annualisée, ATR, bêta vs S&P 500, repli maximal sur 6 mois.
- **Niveaux clés** : supports / résistances (pivots des 60 dernières séances), moyennes 50/200 j, extrêmes 52 semaines.
- **Catalyseurs** : news des 7 derniers jours, ton, réaction du cours le jour même, et news écartées par le contrôleur.
- **Réseaux sociaux** : volume, ton, buzz, part de comptes récents, score de manipulation.
- **Pairs** : comparaison avec les autres titres du même secteur.
- **Graphique 6 mois** (HTML) : cours, moyennes 50/200 j, supports / résistances, info-bulle au survol.

## Facteurs issus de la recherche académique

L'agent `chercheur` ajoute un pilier fondé sur des résultats publiés en finance empirique,
chacun cité dans la fiche du titre. Le détail des formules, des pondérations et des
limites est dans **[docs/METHODOLOGIE.md](docs/METHODOLOGIE.md)**.

- **Momentum** : 12-1 mois (Jegadeesh & Titman, 1993), temporel ajusté de la volatilité
  (Moskowitz, Ooi & Pedersen, 2012 ; Barroso & Santa-Clara, 2015), plus haut 52 semaines
  (George & Hwang, 2004), sectoriel (Moskowitz & Grinblatt, 1999).
- **Retournement et « loterie »** : retournement 1 mois (Jegadeesh, 1990 ; Lehmann, 1990),
  effet MAX (Bali, Cakici & Whitelaw, 2011).
- **Risque** : volatilité idiosyncratique (Ang et al., 2006), bêta (Frazzini & Pedersen, 2014).
- **Volume, news, attention** : prime de volume (Gervais, Kaniel & Mingelgrin, 2001),
  dérive après news / retournement sans news (Chan, 2003), attention
  (Da, Engelberg & Gao, 2011 ; Barber & Odean, 2008).
- **Diagnostics** : régime tendance / retour à la moyenne par le ratio de variance
  (Lo & MacKinlay, 1988), risque de krach du momentum (Daniel & Moskowitz, 2016),
  volatilité prévue GARCH(1,1) (Bollerslev, 1986).

Les poids tiennent compte du déclin des anomalies après publication (McLean & Pontiff, 2016)
et de leur faiblesse sur les grandes capitalisations (Hou, Xue & Zhang, 2020).
`--backtest` mesure le pouvoir prédictif de chaque facteur sans biais d'anticipation
(IC de Spearman, seuil |t| > 3 de Harvey, Liu & Zhu, 2016). Sur les données simulées,
il valide la mécanique, pas les facteurs.

## Audit des analyses

Les calculs ont été audités en profondeur : comparaison des indicateurs à une implémentation
de référence, tests d'absence de biais sur marchés neutres (trajectoires antithétiques),
stabilité, indépendance des piliers, calibration hors échantillon des fourchettes, contrôles
positif et négatif du backtest, robustesse aux données dégradées. Vingt écarts ont été
corrigés, chacun couvert par un test. Détail : **[docs/AUDIT.md](docs/AUDIT.md)**.

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
  agents/advisor.py     Avis de Claude à la demande (dossier complet, réponse en continu)
  providers/base.py     Interface DataProvider (à implémenter pour de vraies données)
  providers/mock.py     Données simulées déterministes (cours, news, social, macro)
  analysis/indicators.py  Indicateurs techniques (pur Python)
  analysis/technical.py   Pilier technique
  analysis/sentiment.py   Pilier sentiment (lexique financier, fiabilité des sources)
  analysis/macro.py       Pilier macro + sensibilités sectorielles
  analysis/coherence.py   Contrôles de qualité et recoupement des sources
  analysis/scoring.py     Pondération des piliers, confiance, fourchettes
  analysis/stock.py       Fiche par action : thèse, niveaux clés, catalyseurs, risques, pairs
  analysis/research.py    Facteurs académiques, ratio de variance, GARCH(1,1)
  analysis/backtest.py    Backtest point-in-time (IC de Spearman)
  engine.py             Point d'entrée programmatique (run_analysis)
  app/                  Application de bureau : serveur local, interface (ui.html), lanceur pywebview
packaging/macos/        Icône, spécification PyInstaller, script de build .app / .dmg
  report.py             Rendu terminal / JSON / HTML
  universe.py           30 valeurs du S&P 500, profils sectoriels, fiabilité des sources
```

Poids des piliers (`analysis/scoring.py`) :

| Horizon | Technique | Sentiment | Macro | Recherche |
|---|---|---|---|---|
| Court terme | 40 % | 25 % | 15 % | 20 % |
| Moyen terme | 35 % (tendance technique + facteurs de momentum) | 10 % | 30 % | 25 % (anomalies hors tendance) |

Les fourchettes de cours (≈ 2 chances sur 3) reposent sur une prévision de volatilité
GARCH(1,1) et sont centrées sur le cours actuel : ce sont des mesures d'incertitude, pas
des objectifs de cours.

## Brancher de vraies données

Implémenter `DataProvider` (`providers/base.py`) : `price_history`, `news`,
`social_posts`, `macro`, `trading_days`, `universe`, `index`. Par exemple : une API de
cours, un flux de news, l'API d'un réseau social, et FRED pour la macro. Le reste du
pipeline ne change pas.
