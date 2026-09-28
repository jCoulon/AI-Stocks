# Recherche de signaux sur les titres IA (septembre 2026)

Objectif : trouver des données ou des lectures qui améliorent **réellement** le score court terme
de l'outil sur l'univers IA (26 titres), c'est-à-dire sur une période qui n'a pas servi à les
choisir. Chercher « jusqu'à trouver » sur les mêmes données produit presque toujours un faux
positif ; le protocole ci-dessous a été écrit **avant** les calculs
([pré-enregistrement](recherche_ia/PREENREGISTREMENT.md), scripts dans [recherche_ia/](recherche_ia/)).

## Point de départ

Backtest de l'outil sur l'univers IA, 2026 (outil relancé chaque séance, sans donnée future) :
IC à 5 séances **−0,079 (t −2,15)** ; panier des titres jugés haussiers **−17,7 %** contre
**+46,8 %** pour l'univers IA équipondéré. Le score était donc à contresens sur ces titres.

## Protocole

- Mesure : corrélation de rang (IC) entre le signal et le rendement des 5 séances suivantes, par
  date, dates espacées de 5 séances ; t = moyenne / écart-type × √n.
- Étape 1 (découverte) : |t| ≥ 2 dans le sens attendu par la littérature.
- Étape 2 (réserve, testée **une seule fois**) : même sens, t ≥ 1,65.
- Intégration seulement si le score de l'outil s'améliore sur la réserve.

## Étape 1 — découverte

| Candidat (source) | Période | IC | t | Retenu |
|---|---|---|---|---|
| Retournement 1 mois (cours) | 2024-10 → 2026-03 | −0,038 | −0,92 | non |
| Momentum 12-1 mois | idem | +0,056 | +0,89 | non |
| Proximité du plus haut 52 sem. | idem | +0,004 | +0,10 | non |
| Effet MAX | idem | −0,021 | −0,47 | non |
| Retournement 1 semaine | idem | −0,086 | −2,23 | oui (2 ans) |
| Retournement 1 semaine | 2023-01 → 2026-03 (5 ans) | −0,035 | −1,45 | non sur 5 ans |
| Volume de news anormal (Google/GDELT/RSS) | 2026-01 → 05 | −0,040 | −0,63 | non |
| Ton FinBERT 7 jours | idem | +0,052 | +1,01 | non |
| Part des ventes à découvert 5 j (FINRA Reg SHO) | 2023-01 → 2026-03 | −0,017 | −0,85 | non |
| Part à découvert anormale 5 j − 60 j | idem | −0,004 | −0,25 | non |
| Consultations Wikipédia anormales | idem | −0,008 | −0,29 | non |
| NVDA / SMH de la veille → petites valeurs IA | idem | pente +0,02 / +0,07 | +0,38 / +1,00 | non |
| Bitcoin du week-end → lundi (ouverture → clôture) des ex-mineurs | idem | pente +0,27 | +2,20 | oui |
| Dérive après résultats (réaction 2 séances → 20 séances) | ≤ 2026-03 | écart +3,9 % | +1,67 | non |

Diagnostic de l'outil sur jan.-mai 2026 : le pilier **technique court terme** (MACD, RSI, force
relative 5 j, performance 5 séances) avait un IC de −0,126 (t −1,91) : il récompensait la hausse
récente, qui s'inverse la semaine suivante sur ces titres très volatils.

## Étape 2 — réserve (un seul essai par hypothèse)

| Hypothèse | Réserve | Résultat | Verdict |
|---|---|---|---|
| H-A retournement 1 semaine seul | 2026-04 → 09 | IC −0,096, t −1,34 | échec |
| **H-B mode IA : technique court terme lue à contre-courant** | 2026-06 → 09 | **IC +0,140, t +1,73** ; outil −0,149 ; gain +0,289 (t +1,81) | **retenue** |
| H-C sans technique court terme | 2026-06 → 09 | IC +0,018 ; gain +0,166 (t +1,85) | gain réel, score nul |
| T2 bitcoin week-end → lundi des mineurs | 2026-04 → 09 | pente +0,58, t +1,32 (20 lundis) | échec (trop peu de lundis) |

## Intégration

`analysis/scoring.py` : `CONTRARIAN_SHORT` — pour les titres du focus IA (`universe.AI_THEME`),
la contribution du pilier technique court terme est inversée ; la fiche (points forts / risques)
applique la même lecture et le signale. Les autres titres ne changent pas.

## Vérification sur l'outil complet (backtest 2026, univers IA)

| | Outil d'origine | Avec le mode IA |
|---|---|---|
| IC 5 séances, 2026 entier (jan.-mai = période de découverte) | −0,079 (t −2,15) | **+0,063 (t +2,59)** |
| Panier des titres jugés haussiers, 2026 (hors frais) | −17,7 % | **+81,6 %** (univers équipondéré +46,8 %) |
| IC 5 séances, **réserve juin-sept. seule**, moyenne de toutes les séances | −0,096 | **+0,080** |
| Réserve, selon le jour de départ des fenêtres hebdomadaires (5 décalages) | −0,05 à −0,15 | −0,02 à +0,23 (3 positifs sur 5) |
| Panier haussier, réserve, avec 0,2 % de frais par semaine | −27,3 % | +2,0 % (équipondéré −9,4 %) |

Lecture honnête : l'**amélioration** est robuste (la nouvelle version bat l'ancienne pour chacun
des 5 décalages de la réserve) ; le **niveau** positif (+0,08) est réel en moyenne mais fragile
selon les dates retenues. À 21 séances, aucun effet (IC ≈ 0).

## Limites (à lire)

- La réserve est courte (15 dates hebdomadaires) : t 1,73 est un indice, pas une preuve
  (Harvey, Liu & Zhu 2016 recommandent |t| > 3). Quatre hypothèses ont été testées sur la
  réserve : avec une correction pour tests multiples, le seuil serait ≈ 2,2.
- Le résultat est cohérent avec la littérature (retournement de court terme plus fort sur les
  titres volatils), ce qui le rend plus crédible qu'un motif sans explication.
- Rien ne garantit que le régime persiste ; à revérifier chaque mois (relancer
  `docs/recherche_ia/decomp.py` puis `decomp_an.py` sur les nouvelles semaines).
- Ce n'est pas un conseil d'investissement.
