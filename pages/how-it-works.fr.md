# Comment fonctionne Sol-0

[English](how-it-works.en.md) · [Journal](../journal/README.md) · [Atlas](../atlas/README.md) · [Premières fois](../firsts/README.md)

Sol-0 est un rover simulé. Il vit sur une planète procédurale, roule avec quelques très petits réseaux de neurones et apprend seul. Une GitHub Action planifiée lui fait vivre un « sol » quatre fois par jour, puis publie les images affichées sur la page de profil.

## Tout ce qui est affiché est réel

- L'image du panneau CAM-1 est exactement l'entrée reçue par le cerveau du rover, calculée par le moteur de simulation.
- Chaque neurone, chaque connexion, chaque commande de roue, chaque valeur de télémétrie, chaque case de la carte, chaque barre de progression et chaque ligne du journal vient de l'état réel de la simulation et des vrais réseaux. Rien n'est décoratif et aucune animation n'est scriptée en dehors du calcul.
- Le journal n'est pas écrit par un modèle de langage. Chaque phrase est un modèle dont les nombres, et chaque adjectif ou cause, sont reliés à un fait calculé pendant le sol. Si le fait manque, la phrase n'est pas écrite.
- Mêmes entrées, mêmes sorties : le générateur aléatoire, à entiers seulement, est écrit pour ce projet ; n'importe quel sol peut être rejoué à l'identique.

## Un sol

Un sol dure 1 200 pas de temps de 72 secondes, soit 24 heures simulées ; il commence à 05:00 heure locale. À chaque sol, le rover roule, enregistre ce qu'il perçoit, puis apprend. La planète est générée à la demande à partir d'une graine : le terrain (roche, sable, poussière, glace), les dunes, le soleil et les saisons. Des événements rares peuvent survenir : tempêtes de poussière, gisements rares, anomalies, impacts de comète. Chacun a un effet réel sur la simulation (une tempête réduit par exemple la vue et la puissance solaire).

## Les cerveaux

De petits perceptrons multicouches écrits avec numpy seulement, sans framework d'apprentissage profond :

- **M0**, le pilote : 24 entrées, 16 neurones cachés, 2 sorties (roue gauche et roue droite). Entraîné par stratégies d'évolution, en essayant 48 copies perturbées sur des parcours simulés.
- **M1**, le prédicteur : à partir des commandes de roues, de l'inclinaison et du glissement, il prédit de combien le rover avancera vraiment. Il est noté par un R² sur des sols qui ne lui ont pas servi à apprendre.
- **M2**, l'encodeur visuel : il comprime l'image de la caméra en 8 nombres.
- **M3**, le gestionnaire d'énergie : il choisit entre rouler, chercher le soleil et dormir.

La cible de navigation est une règle simple lue sur la carte, pas un plan appris : la direction, parmi 8, qui compte le plus de cellules inexplorées.

## Les stades

Un stade n'est franchi que lorsque son critère est atteint et qu'une durée minimale est écoulée. Les seuils ci-dessous sont des valeurs initiales, recalibrables ; la barre de progression affiche toujours la valeur réelle et le seuil courant.

| Stade | Nom | Critère (valeur initiale) |
|---|---|---|
| 0 | AWAKENING | 200 couples commande-effet enregistrés |
| 1 | I CAN MOVE | R² du prédicteur d'au moins 0,70 sur 3 sols de suite |
| 2 | LEARNING TO DRIVE | au moins 16 parcours de test réussis sur 20 |
| 3 | ENERGY | 20 sols de suite sans panne, avec au moins 20 cellules parcourues éveillé |
| 4 | SAMPLING | au moins 10 échantillons à gain positif parmi les 20 derniers |
| 5 | ANALYSIS | 10 sols de suite avec un ARI d'au moins 0,8 |

À la date de ce texte, le code ne connaît que les stades 0 à 3 (les stades 4 et 5 sont prévus). Un rover qui atteint le dernier stade connu garde un apprentissage d'entretien et écrit dans son journal qu'il attend une mise à jour logicielle.

## Mode sûr

Le rover n'est jamais dans un état terminal. Après un sol fini ensablé ou basculé, le mode sûr le dégage ou le redresse ; après un sol entier sous le seuil de panne de la batterie, il la recharge ; après trois sols de suite à moins de 2 cellules parcourues éveillé, il double le bruit d'exploration pendant un sol. Chaque intervention est un fait calculé et a sa ligne dans le journal : la machinerie n'agit jamais en silence.

## Pages

- [Journal](../journal/README.md) : une entrée par sol, en français et en anglais.
- [Premières fois](../firsts/README.md) : les moments fondateurs, chacun avec un tag Git.
- [Atlas](../atlas/README.md) : substances et formes de vie, quand le rover saura les analyser.

Coût : zéro. Runners GitHub standard, dépôt public, aucune API payante, aucun secret.
