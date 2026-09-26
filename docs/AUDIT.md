# Audit des analyses — 26 septembre 2026

Revue en profondeur (≈ 1 h) des calculs de l'outil : exactitude des indicateurs, méthodes
statistiques, logique métier, robustesse, puis deux revues de code indépendantes des
corrections elles-mêmes. Chaque écart corrigé est couvert par un test de non-régression
(`tests/test_audit.py`).

## Contrôles effectués et résultats

| Contrôle | Méthode | Résultat |
|---|---|---|
| Exactitude des indicateurs | comparaison à une implémentation pandas de référence (SMA, EMA, RSI de Wilder, MACD, ATR, Bollinger) | écart ≤ 1e-14 ; Bollinger corrigé (écart-type de population) |
| Absence de biais structurel | 40 marchés simulés sans tendance + trajectoires miroirs (antithétiques), pipeline complet | score moyen −0,0005 ± 0,0008 (court terme), −0,0005 ± 0,0024 (moyen terme) |
| Stabilité des signaux | balayage du dernier cours par pas de 0,1 % | saut maximal 0,11 (contre 0,70 avant correction) |
| Indépendance des piliers | corrélation de rang entre piliers sur 300 avis | tendance comptée une seule fois : +0,63 → −0,06 |
| Calibration des fourchettes | couverture hors échantillon (fourchette calculée à chaque date avec les seules données connues) | 71 % (5 séances) et 65 % (63 séances) pour une cible de 68 % |
| Estimateur GARCH(1,1) | séries simulées de paramètres connus | α = 0,08, β = 0,90 retrouvés à ±0,003 en moyenne |
| Test du ratio de variance | 400 marches aléatoires à volatilité GARCH | faux « régimes » : 9,8 % (z homoscédastique) → 6,2 % (z\* robuste), cible 5 % |
| Backtest | contrôle positif (vraie tendance) et négatif (marche aléatoire), falsification des données futures | signal détecté (IC 0,95) ; rien de significatif sur l'aléatoire ; aucune fuite du futur |
| Chronologie des news | cas limites (après clôture, week-end, source peu fiable) | conforme |
| Robustesse | historiques de 10 à 300 séances, pannes d'agents, flux de l'indice en retard | aucun plantage, JSON strictement valide |
| Scénarios de démonstration | 8 jeux de données | 8/8 détectés, aucun faux positif |

## Écarts trouvés et corrigés

| # | Domaine | Écart | Correction |
|---|---|---|---|
| 1 | Indicateurs | Bollinger calculé avec l'écart-type d'échantillon (n−1) | écart-type de population (convention de J. Bollinger) |
| 2 | Alignement | rendements sur N séances et force relative comparés par position : une séance manquante décalait la fenêtre | calendrier commun avec l'indice, cours reporté ; même période pour titre et indice |
| 3 | Sentiment | lexique mot à mot : « openness to cut », « yields fall », « claims rise », « output cuts » mal orientés | expressions financières reconnues avant les mots (cf. Loughran & McDonald, 2011) |
| 4 | Macro | variations en nombre d'observations (« 3 mois » ≈ 4,3 mois sur la Fed) | durées calendaires ; mois civils pour les séries mensuelles (1er ou fin de mois) |
| 5 | Statistiques | ratio de variance homoscédastique : trop de faux régimes | z\* robuste de Lo & MacKinlay (1988) |
| 6 | Statistiques | grille GARCH grossière | recherche locale autour du meilleur point |
| 7 | Cohérence | une news publiée après la clôture « expliquait » le mouvement du jour ; une news du week-end n'expliquait pas le lundi | règle de la séance de réaction, partagée avec le facteur de Chan (2003) |
| 8 | Robustesse | fiches en échec sous 126 séances ; `NaN` dans le JSON ; largeur de marché faussée par les moyennes non calculables | fenêtres adaptatives ; `null` au lieu de `NaN` ; ratios sur les seuls titres renseignés |
| 9 | Méthode | tendance comptée deux fois à moyen terme (technique + facteurs académiques) : confiance gonflée | bloc « tendance » unique ; pilier recherche limité aux anomalies hors tendance |
| 10 | Méthode | fourchettes décalées dans le sens de l'avis, comme un objectif de cours | fourchettes d'incertitude centrées (≈ 2 chances sur 3) |
| 11 | Sentiment | absence de news interprétée comme « le ton se dégrade » (18 titres sur 30) | inflexion mesurée seulement si des news existent sur les deux périodes |
| 12 | Cohérence | deux bêtas différents sur la même fiche ; plus haut 52 semaines défini de deux façons | un seul calcul partagé |
| 13 | Biais | momentum temporel en rendement arithmétique (biais haussier) ; distance au plus haut structurellement négative et en doublon | rendements logarithmiques ; signal en doublon supprimé |
| 14 | Stabilité | Bollinger %B, confirmation par le volume et régime de volatilité discontinus | fonctions de score continues |
| 15 | Macro | niveau du VIX lu comme favorable à tous les horizons | prime de risque de variance à moyen terme (Bollerslev, Tauchen & Zhou, 2009) |
| 16 | Données manquantes | news inconnues (contrôleur indisponible) traitées comme « aucune news » | le facteur s'abstient |
| 17 | Cohérence | fourchettes de l'indice sans GARCH ; indice sans composante de tendance académique | GARCH et momentum temporel pour l'indice, mêmes ajustements |
| 18 | Revue n° 1 | la fusion du bloc tendance annulait l'ajustement de régime et la protection anti-krach | normalisation par les poids de base |
| 19 | Revue n° 2 | force relative sur des périodes différentes quand l'indice est en retard | fin de période alignée sur la dernière séance de l'indice |
| 20 | Contrat de données | ambiguïté sur la date des séries macro (période vs publication) | dates de publication exigées (point-in-time) |

## Ce que l'audit ne peut pas établir

- **Le pouvoir prédictif réel des avis.** Sur les données simulées (marches aléatoires),
  aucun facteur n'est significatif, ce qui est le résultat attendu. Il faut des données
  historiques réelles, sur une longue période et sans biais du survivant, pour conclure.
- **La calibration de la confiance.** Le pourcentage affiché mesure l'accord entre des
  piliers indépendants et la qualité des données ; ce n'est pas une probabilité de gain.

## Points à recalibrer sur données réelles

- **Alerte « mouvement inexpliqué »** (> 4 écarts-types ou volume x2,5 sans news fiable) :
  taux de fausses alertes mesuré sur titres sans événement, par semaine : 0,2 % avec des
  rendements gaussiens, 2,8 % avec des queues épaisses réalistes (Student t à 4 degrés de
  liberté), 4,3 % avec t à 3 degrés. Sur 30 titres, environ une fausse alerte par semaine ;
  sur les 500 valeurs du S&P 500, une quinzaine. Le seuil devra être ajusté sur l'historique
  réel (par exemple au 99,5e centile empirique des rendements de chaque titre).

## Revérifier

```bash
python -m unittest discover -s tests      # dont tests/test_audit.py
python -m sp500_analyzer --backtest       # aucun « ◀ significatif » attendu sur données simulées
```
