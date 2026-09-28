# Pré-enregistrement — signaux candidats pour l'univers IA (26 titres)
Écrit le 2026-09-28 ~12:45 UTC, AVANT tout calcul sur ces signaux.

Cible : rendement futur sur 5 séances, relatif (classement transversal dans l'univers IA).
Mesure : IC de Spearman par date, dates espacées de 5 séances (fenêtres disjointes) ; t = moyenne/écart-type*sqrt(n).
Univers : titres IA avec >= 60 séances d'historique à la date.

Périodes :
- Signaux de cours / FINRA / Wikipédia : découverte 2024-10-01 → 2026-03-31 ; réserve 2026-04-01 → 2026-09-25
  (avec les cours 5 ans : découverte 2023-01 → 2026-03-31).
- Signaux de news (données depuis 2026-01) : découverte 2026-01-05 → 2026-05-29 ; réserve 2026-06-01 → 2026-09-25.

Candidats (sens attendu par la littérature) :
 P1 retournement 1 mois (-)            Jegadeesh 1990
 P2 momentum 12-1 mois (+)              Jegadeesh-Titman 1993
 P3 proximité du plus haut 52 sem. (+)  George-Hwang 2004
 P4 effet MAX 1 mois (-)                Bali-Cakici-Whitelaw 2011
 P5 momentum court 1 semaine (±)        (retournement hebdo, Lehmann 1990 : -)
 N1 volume de news anormal 5j/60j (+ à court terme puis -)   Barber-Odean 2008, Da-Engelberg-Gao 2011
 N2 ton FinBERT moyen 5j (+)            Tetlock 2007 (déjà testé sur S&P : échec)
 S1 part des ventes à découvert 5j (-)  Boehmer-Jones-Zhang 2008, Diether-Lee-Werner 2009
 S2 part à découvert anormale 5j-60j (-)
 W1 consultations Wikipédia anormales 5j/60j (+ court terme)  Da-Engelberg-Gao 2011 (proxy d'attention)
Séries temporelles (panier IA équipondéré ou mineurs) :
 T1 rendement SMH/NVDA de la veille -> rendement du jour des petites valeurs IA (+)  Hou 2007 (lead-lag)
 T2 rendement du bitcoin du week-end -> lundi des ex-mineurs IREN/CIFR/WULF/CORZ/APLD (+)
Événements :
 E1 dérive après résultats : signe de la réaction 2 séances -> rendement des 20 séances suivantes (+)  Bernard-Thomas 1989

Règle d'acceptation (fixée d'avance) :
 1. découverte : |t| >= 2 et sens conforme à la littérature (ou sens constant si ±) ;
 2. réserve (testée UNE fois) : même sens, t >= 1.65 ;
 3. intégration seulement si l'IC de l'outil combiné s'améliore sur la réserve.
Avec ~13 candidats, on s'attend à ~0.6 faux positif à l'étape 1 par hasard : l'étape 2 est décisive.

## Ajout 2026-09-28 ~13:00 UTC (après la découverte, AVANT toute réserve)
Découverte : P5 (retournement 1 semaine) t = -2.23 sur 2024-10 → 2026-03 ; seul candidat retenu à l'étape 1
(N1, N2, T1, E1, P1-P4 rejetés). Diagnostic de l'outil (jan-mai 2026) : pilier technique court terme IC -0.126, t -1.91.
Hypothèses testées UNE fois sur la réserve :
 H-A  P5 seul, IC à 5 séances, réserve 2026-04-01 → 2026-09-25 (règle : t <= -1.65).
 H-B  score court terme « mode IA » = score − 2 × contribution technique (pilier technique inversé),
      réserve 2026-06-01 → 2026-09-25 ; règle : IC(H-B) − IC(outil) > 0 avec t (différence apparillée) >= 1.65.
 H-C  score court terme sans pilier technique = score − contribution technique ; même règle.
