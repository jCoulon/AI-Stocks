# Méthodologie — pilier « recherche »

Ce document décrit les facteurs issus de la littérature académique utilisés par l'agent
`chercheur` (`sp500_analyzer/analysis/research.py`), leur implémentation, leur pondération
et leurs limites. **Ce n'est pas un conseil en investissement** : ces facteurs décrivent des
régularités statistiques moyennes observées sur de larges échantillons historiques, pas
des prévisions fiables pour un titre donné.

## 1. Principe

- **Classement transversal.** La plupart des articles trient les actions en déciles selon
  une caractéristique puis comparent les rendements futurs des déciles extrêmes. L'outil
  reproduit cette logique : chaque facteur est converti en **percentile** dans l'univers
  analysé, puis en score `direction × (2 × percentile − 1)` dans [−1, +1].
- **Facteurs temporels** (momentum temporel, dérive après news, attention) : notés sur
  la valeur propre du titre, sans classement.
- **Pondération** selon la robustesse attendue *sur de grandes capitalisations américaines*
  (voir §4), puis ajustement selon le régime statistique du titre et du marché (§3).
- **Pilier du score final** : 20 % de l'avis court terme ; à moyen terme, les facteurs de
  tendance rejoignent le bloc « tendance » (35 %) et les autres facteurs forment le pilier
  « recherche » (25 %) — voir limite n° 7.

## 2. Facteurs

| Facteur | Mesure implémentée | Sens | Horizon | Poids | Source |
|---|---|---|---|---|---|
| Momentum 12-1 | rendement de t−12 mois à t−1 mois (le dernier mois est exclu) | + | MT | 1,0 | Jegadeesh & Titman (1993) |
| Momentum temporel | rendement 12 mois ÷ volatilité annualisée (126 j) | + | MT | 0,8 | Moskowitz, Ooi & Pedersen (2012) ; mise à l'échelle par la volatilité : Barroso & Santa-Clara (2015) |
| Plus haut 52 semaines | cours ÷ plus haut des 252 dernières séances | + | MT | 0,7 | George & Hwang (2004) |
| Momentum sectoriel | rendement moyen 6 mois du secteur | + | MT | 0,6 | Moskowitz & Grinblatt (1999) |
| Volatilité idiosyncratique | écart-type annualisé des résidus de la régression des rendements journaliers sur l'indice (63 j) | − | MT | 0,6 | Ang, Hodrick, Xing & Zhang (2006) |
| Bêta | pente de la régression sur l'indice (252 j) | − | MT | 0,4 | Frazzini & Pedersen (2014) |
| Retournement 1 mois | rendement des 21 dernières séances | − | CT | 0,6 | Jegadeesh (1990) ; Lehmann (1990) |
| Effet MAX | plus forte hausse journalière des 21 dernières séances | − | CT/MT | 0,6 | Bali, Cakici & Whitelaw (2011) |
| Prime de volume | log(volume moyen 5 j ÷ volume moyen des 50 j précédents) | + | CT | 0,5 | Gervais, Kaniel & Mingelgrin (2001) |
| Dérive / retournement après news | pour chaque mouvement ≥ 2 σ des 5 dernières séances : continuation s'il est expliqué par une news de source fiable, retournement (demi-poids) sinon | ± | CT/MT | 0,4 | Chan (2003) |
| Choc d'attention | log du buzz social (3 j vs 11 j précédents), **comptes de moins de 30 jours exclus** | + | CT | 0,4 | Da, Engelberg & Gao (2011) ; Barber & Odean (2008) |
| Retournement post-attention | même mesure | − | MT | 0,3 | Da, Engelberg & Gao (2011) |

Notes d'implémentation :

- Da, Engelberg & Gao mesurent l'attention par le volume de recherches Google ; faute de
  cette donnée, le buzz sur les réseaux sociaux sert d'approximation. Leur résultat :
  hausse de l'attention → cours plus élevés sur ~2 semaines, puis retournement dans l'année.
- Le choc d'attention exclut les comptes récents : une campagne coordonnée (détectée par
  l'agent contrôleur) fabrique du buzz sans refléter l'attention réelle des investisseurs.
- La dérive après news repose sur les news **retenues par le contrôleur** (les rumeurs non
  confirmées sont exclues).

## 3. Diagnostics et ajustements

**Régime statistique — ratio de variance** (Lo & MacKinlay, 1988). Sur les 250 derniers
rendements journaliers, `VR(5) = Var(rendements sur 5 j) / (5 × Var(rendements sur 1 j))`,
avec la statistique **z\* robuste à l'hétéroscédasticité** de l'article (la version
homoscédastique signale à tort un régime dans ~10 % des cas sur des rendements à
volatilité groupée, contre ~6 % pour z\*, au seuil nominal de 5 % — vérifié par simulation).
`z* > 1,96` : tendance (autocorrélation positive) ;
`z* < −1,96` : retour à la moyenne. Le poids des facteurs de momentum est multiplié par
`1 + 0,5 × clip(z*/2)` et celui des facteurs de retournement par `1 − 0,5 × clip(z*/2)`.

**Risque de krach du momentum** (Daniel & Moskowitz, 2016). Les pires pertes du momentum
surviennent lors des rebonds de marché qui suivent une baisse prolongée. Si l'indice est
en baisse sur 12 mois mais en hausse sur le dernier mois, le poids des facteurs de
momentum est divisé par deux.

**Volatilité prévue — GARCH(1,1)** (Bollerslev, 1986).
`σ²ₜ₊₁ = ω + α·ε²ₜ + β·σ²ₜ`, estimé par maximum de vraisemblance (grille sur α, β) avec
ciblage de variance `ω = σ²_LT × (1 − α − β)`, puis recherche locale autour du meilleur
point (vérifié sur séries simulées : α = 0,08, β = 0,90 retrouvés en moyenne à ±0,003). La variance cumulée sur h séances,
`Σₖ [σ²_LT + (α+β)^(k−1) × (σ²ₜ₊₁ − σ²_LT)]`, remplace la règle « racine du temps » pour
les fourchettes de cours à 5 séances (court terme) et 63 séances (moyen terme).

Ces fourchettes (±1 écart-type, soit environ 2 chances sur 3) sont **centrées sur le cours
actuel** : elles mesurent l'incertitude, ce ne sont pas des objectifs de cours. Couverture
mesurée hors échantillon (fourchette calculée à chaque date avec les seules données
disponibles) : 71 % à 5 séances et 65 % à 63 séances, pour une cible de 68 %.

## 4. Limites connues — à lire avant toute utilisation

1. **Déclin après publication.** Sur 97 facteurs, les rendements sont inférieurs de 26 %
   hors échantillon et de 58 % après publication (McLean & Pontiff, 2016).
2. **Réplication.** Une fois les micro-capitalisations neutralisées et les rendements
   pondérés par la capitalisation, 65 % de 452 anomalies ne passent pas le seuil |t| > 1,96,
   et 82 % échouent avec le seuil de tests multiples |t| > 2,78 (Hou, Xue & Zhang, 2020).
   L'univers analysé ici (grandes valeurs du S&P 500) est celui où les anomalies sont
   les plus faibles : les poids en tiennent compte.
3. **Tests multiples.** Harvey, Liu & Zhu (2016) recommandent |t| > 3 pour un nouveau
   facteur : c'est le seuil retenu par le backtest.
4. **Chan (2003)** trouve la dérive après news et le retournement sans news surtout parmi
   les petites valeurs ; le facteur a donc un poids faible.
5. **Approximations.** Les mesures sont simplifiées (pas de neutralisation taille /
   valeur, univers de 30 titres, attention mesurée par les réseaux sociaux).
6. **Biais du survivant.** Le backtest utilise la composition *actuelle* de l'univers :
   les titres sortis de l'indice (faillites, rachats, déclassements) en sont absents, ce
   qui embellit les résultats historiques. Un backtest sur données réelles doit utiliser
   la composition de l'indice à chaque date.
7. **Double comptage.** Les facteurs de tendance académiques et la tendance technique
   mesurent le même phénomène (corrélation de rang ≈ 0,6 entre les deux piliers). À moyen
   terme ils sont donc regroupés dans un seul bloc « tendance » ; le pilier « recherche »
   ne garde que les anomalies indépendantes (corrélation résiduelle ≈ −0,06). Sans cela,
   la tendance aurait pesé environ 60 % de l'avis et gonflé l'accord apparent entre piliers.

## 5. Contrôles de neutralité et de stabilité

- **Absence de biais structurel** : sur 40 marchés simulés sans tendance (marches
  aléatoires, chacune doublée de sa trajectoire miroir où chaque hausse devient une baisse
  identique), le score moyen vaut −0,0005 ± 0,0008 à court et à moyen terme. Les scores
  fondés sur des rendements utilisent des **rendements logarithmiques**, symétriques
  (le rendement arithmétique, +50 % puis −33 %, biaisait le momentum temporel vers la
  hausse). Les asymétries résiduelles (≤ 0,03) proviennent des moyennes mobiles
  arithmétiques standard.
- **Continuité** : une variation de 0,1 % du cours ne fait pas varier un signal de plus de
  0,2 (auparavant jusqu'à 0,7 au franchissement d'une bande de Bollinger).

## 6. Validation : backtest point-in-time

`python -m sp500_analyzer --backtest` (`analysis/backtest.py`) :

- à chaque date t, les facteurs sont calculés sur l'historique **tronqué à t** ; un test
  vérifie qu'une modification des données postérieures à t ne change aucun facteur ;
- **coefficient d'information (IC)** : corrélation de rang de Spearman entre le score et le
  rendement futur sur h = 5 et 21 séances ;
- dates espacées de h séances (pas de chevauchement), t = IC moyen ÷ (écart-type ÷ √n) ;
- **contrôle positif** (tests) : dans un univers fictif où chaque titre garde sa tendance,
  le backtest détecte bien le momentum (IC ≈ 0,95) ; **contrôle négatif** : sur une
  marche aléatoire, aucun facteur n'atteint |t| > 3.

Seuls les facteurs calculables sur les cours sont backtestés : l'historique point-in-time
des news et des réseaux sociaux n'est pas disponible dans les sources actuelles.

**Sur les données simulées, le backtest ne valide aucun facteur** (les cours y sont une
marche aléatoire) : il valide la mécanique. La validation des facteurs exige de vraies
données historiques, idéalement sur plusieurs décennies et un univers large.

## 7. Références

- Ang, A., Hodrick, R., Xing, Y. & Zhang, X. (2006). The Cross-Section of Volatility and Expected Returns. *Journal of Finance*.
- Bali, T., Cakici, N. & Whitelaw, R. (2011). Maxing Out: Stocks as Lotteries and the Cross-Section of Expected Returns. *Journal of Financial Economics*, 99, 427–446.
- Barber, B. & Odean, T. (2008). All That Glitters: The Effect of Attention and News on the Buying Behavior of Individual and Institutional Investors. *Review of Financial Studies*.
- Barroso, P. & Santa-Clara, P. (2015). Momentum Has Its Moments. *Journal of Financial Economics*.
- Bollerslev, T. (1986). Generalized Autoregressive Conditional Heteroskedasticity. *Journal of Econometrics*.
- Chan, W. S. (2003). Stock Price Reaction to News and No-News: Drift and Reversal After Headlines. *Journal of Financial Economics*, 70, 223–260.
- Da, Z., Engelberg, J. & Gao, P. (2011). In Search of Attention. *Journal of Finance*, 66(5), 1461–1499.
- Daniel, K. & Moskowitz, T. (2016). Momentum Crashes. *Journal of Financial Economics*.
- Frazzini, A. & Pedersen, L. H. (2014). Betting Against Beta. *Journal of Financial Economics*.
- George, T. & Hwang, C.-Y. (2004). The 52-Week High and Momentum Investing. *Journal of Finance*.
- Gervais, S., Kaniel, R. & Mingelgrin, D. (2001). The High-Volume Return Premium. *Journal of Finance*, 56(3), 877–919.
- Harvey, C., Liu, Y. & Zhu, H. (2016). … and the Cross-Section of Expected Returns. *Review of Financial Studies*.
- Hou, K., Xue, C. & Zhang, L. (2020). Replicating Anomalies. *Review of Financial Studies*, 33(5), 2019–2133.
- Jegadeesh, N. (1990). Evidence of Predictable Behavior of Security Returns. *Journal of Finance*.
- Jegadeesh, N. & Titman, S. (1993). Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency. *Journal of Finance*.
- Lehmann, B. (1990). Fads, Martingales, and Market Efficiency. *Quarterly Journal of Economics*.
- Lo, A. & MacKinlay, A. C. (1988). Stock Market Prices Do Not Follow Random Walks: Evidence from a Simple Specification Test. *Review of Financial Studies*.
- McLean, R. D. & Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? *Journal of Finance*, 71, 5–32.
- Moskowitz, T. & Grinblatt, M. (1999). Do Industries Explain Momentum? *Journal of Finance*.
- Moskowitz, T., Ooi, Y. H. & Pedersen, L. H. (2012). Time Series Momentum. *Journal of Financial Economics*.
