# Suivi bordage

Comptage de la production des postes de bordage de couettes, à la place des feuilles papier.

- **Sur chaque poste, une tablette.** L'opératrice appuie sur son nom, puis sur de gros boutons :
  *Couette terminée*, *Début de panne*, *Fin de panne*, *Changement d'OF* et *Problème qualité* (ce dernier ouvre la liste des défauts).
  Elle ne voit ni graphique ni pourcentage. Seul son nombre de couettes du quart s'affiche, et on peut le masquer.
- **Le chef de production et la supply chain** se connectent avec leur compte depuis n'importe quel PC du réseau. Ils y trouvent :
  l'état des postes en direct, le rendement en % de chaque opératrice par quart, la production par heure ou par jour, les pannes, les défauts et la production par OF.
  Un export Excel est disponible.

## Installation (une seule fois)

Il faut un PC qui reste allumé dans l'atelier (le « serveur »), sur le même réseau Wi-Fi que les tablettes.

1. Installer Python : https://www.python.org/downloads/ (cocher **« Add python.exe to PATH »**).
2. Copier ce dossier `bordage` sur le PC.
3. Double-cliquer sur **`Lancer-suivi-bordage.bat`**. La fenêtre affiche l'adresse, par exemple `http://192.168.1.50:8080`.
4. Ouvrir cette adresse dans un navigateur et créer le compte administrateur (le tien).
5. Dans **Comptes** : créer le compte du chef de production, puis celui de la supply chain.
6. Dans **Opératrices** : saisir le prénom de chaque opératrice.
7. Dans **Cadences** : les responsables (chef de production ou supply chain) saisissent la cadence attendue de chaque poste, en couettes par heure. Tant qu'elle n'est pas renseignée, les couettes sont comptées mais aucun rendement n'est affiché, et un bandeau le signale sur le tableau de bord.
8. Dans **Réglages** : vérifier les horaires des quarts (par défaut 5h–13h, 13h–21h, 21h–5h, avec 30 min de pause chacun).

À prévoir côté informatique :
- donner au PC serveur une **adresse IP fixe** (sinon les tablettes ne le retrouveront plus après un redémarrage) ;
- autoriser le port 8080 dans le pare-feu Windows (Windows le demande au premier lancement : cocher « réseau privé ») ;
- lancer `Lancer-suivi-bordage.bat` au démarrage du PC (raccourci dans `shell:startup`).

## Préparer une tablette

1. Dans **Postes & tablettes**, copier le lien du poste (par exemple `http://192.168.1.50:8080/t/Xy12…`).
2. Sur la tablette, ouvrir ce lien dans Chrome, puis menu ⋮ → **Ajouter à l'écran d'accueil**.
3. Dans les réglages Android, garder l'écran toujours allumé pendant la charge et désactiver la mise en veille. Pour que l'opératrice ne puisse pas sortir de l'appli, activer l'**épinglage d'écran**, ou installer une appli kiosque comme *Fully Kiosk Browser*.

Le lien suffit à identifier le poste : pas de mot de passe à saisir sur la tablette.

**Si le Wi-Fi coupe**, la tablette continue de fonctionner : les clics sont gardés en mémoire avec leur heure exacte et renvoyés dès que le réseau revient. L'en-tête de la tablette indique « Hors ligne — N clic(s) en attente ».

## Comment le rendement est calculé

Pour chaque opératrice, sur chaque quart :

| | |
|---|---|
| Temps de présence | de l'appui sur son nom jusqu'à « Changer d'opératrice » (ou jusqu'à la fin du quart si elle oublie) |
| Pause | pause du quart, au prorata du temps de présence |
| Temps de panne | de « Début de panne » à « Fin de panne », pendant sa présence (arrêté à la fin du quart si la fin de panne est oubliée) |
| Temps productif | présence − pause − panne |
| Couettes attendues | temps productif (en heures) × cadence du poste |
| **Rendement** | couettes réalisées ÷ couettes attendues × 100 |
| Disponibilité | temps productif ÷ (présence − pause) × 100 |

Exemple : 7 h de présence, 20 min de pause, 40 min de panne, donc 6 h productives. À 12 couettes/h, on attend 72 couettes ; elle en a fait 65, soit un rendement de **90,3 %**.

Le rendement d'une opératrice ne tient donc pas compte des pannes : elle n'est pas pénalisée quand la machine est arrêtée.

Quand un responsable change une cadence, il choisit à partir de quel jour elle s'applique. Les rendements des jours d'avant restent calculés avec l'ancienne cadence. L'historique des cadences (qui a saisi quoi, et quand) est visible dans **Cadences**.

Les OF s'écrivent « OF » suivi de chiffres (par exemple OF241507). Sur la tablette, l'opératrice ne tape que les chiffres.

À la fin de chaque quart, la tablette revient automatiquement à la liste des noms.

## Corriger une erreur

- L'opératrice peut annuler sa dernière couette pendant 60 secondes (bouton « Annuler la dernière couette »).
- Le chef de production peut annuler n'importe quel clic dans le **Journal** : ce clic n'est plus compté, et on peut le rétablir.

## Rôles

| | Tableau de bord, journal, export, cadences | Annuler un clic, gérer les opératrices et les défauts | Postes, comptes, réglages |
|---|---|---|---|
| Supply chain | ✔ | | |
| Chef de production | ✔ | ✔ | |
| Administrateur | ✔ | ✔ | ✔ |

## Sauvegarde

Toutes les données sont dans le seul fichier `data/bordage.sqlite3`. Le copier régulièrement ailleurs (clé USB, serveur de fichiers) suffit pour les sauvegarder.

## Essayer avec de fausses données

Double-cliquer sur **`Lancer-demo.bat`**. Il remplit une base séparée (dossier `demo-data`) avec 2 semaines de fausse production pour 12 opératrices, puis ouvre le navigateur.

- Panel responsable : `admin` / `demo123`
- Tablettes : les liens des 4 postes s'affichent dans la fenêtre noire. On peut les ouvrir dans un autre onglet, ou sur un téléphone connecté au même Wi-Fi.
- Pour repartir de zéro : supprimer le dossier `demo-data`.

La vraie base n'est pas touchée.

## Pour les développeurs

- `app.py` contient les pages et l'API, `stats.py` le calcul du rendement (sans dépendance, testé dans `tests/`), et `db.py` le schéma SQLite.
- Tout est enregistré comme une suite d'événements (`events`). Les sessions et les pannes sont reconstituées à partir de ce journal, ce qui permet le mode hors ligne et l'annulation de clics.
- Tests : `python -m pytest tests`
