# Suivi des heures — version Web

Même application que la version bureau (Saisie, Récapitulatif, Récap global,
Conversion, Salariés, conformité légale, compteur de congés, export Excel),
mais accessible dans un navigateur, avec **comptes utilisateurs**.

La logique de calcul et la base **`heures.db`** sont **partagées** avec
l'application bureau (le fichier `heures.db` du dossier parent).

## Démarrer

### Windows
Double-cliquez sur **`run_web.bat`**.

### macOS / Linux
Double-cliquez sur **`run_web.command`**
(ou dans un terminal : `python3 app.py`).

Le script installe Flask + openpyxl, démarre le serveur, puis ouvre
le navigateur sur **http://127.0.0.1:5000**.
Laissez la fenêtre du terminal ouverte ; fermez-la pour arrêter le serveur.

## Connexion

- Compte par défaut : **admin / admin**
- Changez-le immédiatement dans l'onglet **Comptes** (réservé aux
  administrateurs), où vous pouvez aussi créer d'autres utilisateurs.

## Accès depuis d'autres postes du réseau (optionnel)

Par défaut le site n'est accessible que depuis le PC qui l'héberge
(`127.0.0.1`). Pour le rendre accessible aux autres postes du bureau,
lancez :

```
python3 app.py            # puis, pour ouvrir au réseau local :
```
modifiez la dernière ligne de `app.py` en `host="0.0.0.0"`, puis
connectez les autres postes à `http://IP-DU-PC:5000`.

## Emplacement de la base

Par défaut : `../heures.db` (à côté de l'app bureau).
Pour en utiliser une autre, définissez la variable d'environnement
`SUIVI_DB` avec le chemin voulu.

## Planification des tournées

L'onglet **Tournées** (administrateur) prépare la journée d'un salarié : on
pose les courses dans l'ordre de passage, et les horaires se déduisent tout
seuls. Le salarié retrouve sa tournée en lecture seule dans **Ma tournée**.

Ce qui entre dans le calcul :

- le **départ** se fait du domicile du salarié (onglet *Salariés*, champ
  « adresse de départ »), ou d'une adresse propre à la tournée ;
- le **trajet** entre deux adresses, donné par le service de cartographie
  quand il est configuré, sinon saisi à la main dans le déroulé ;
- le **stationnement**, compté à chaque arrêt ;
- l'**installation** de la personne dans le véhicule, prise sur sa fiche
  client (ou par défaut selon le type : valide 5 min, fauteuil 10, brancard
  15), comptée à la prise en charge **et** à la dépose ;
- le **repos** de la journée, placé après la course de votre choix.

Chaque course peut porter une **heure de rendez-vous à destination** :
l'écran affiche l'avance ou le retard prévu, et signale les retards.

### Adresses et durées de trajet
Les adresses sont localisées par la **Base Adresse Nationale**, le service
public français : gratuit, sans clé, et les adresses ne quittent pas la
France. Pendant le calcul, l'écran affiche l'adresse *retenue* en face de
celle que vous avez saisie — si le rapprochement est mauvais, vous le voyez
tout de suite et vous corrigez la fiche.

Les durées de trajet et l'attribution automatique, elles, passent par le
service de cartographie et demandent une clé (`SUIVI_CARTO_CLE`, voir
`DEPLOIEMENT.md`). Sans clé, les durées se saisissent à la main la première
fois puis sont mémorisées, et les courses s'attribuent à la main.

Une durée corrigée à la main est marquée *manuel* : elle prime sur le service
et resservira à toutes les tournées qui font le même trajet.

## Notes techniques

- `core.py` : logique métier réutilisée (constantes, classe `DB`, calculs)
  — identique à l'app bureau, sans Tkinter.
- `tournee.py` : déroulé horaire d'une tournée (fonction pure, sans base ni
  réseau). `carto.py` : accès au service de cartographie et mémorisation des
  coordonnées et des durées.
- Les tables de la planification (`clients`, `tournees`, `tournee_courses`,
  `geo_cache`, `trajet_cache`) sont propres à la version web : l'application
  bureau ne les lit jamais et continue de fonctionner sur la même base.
- `app.py` : serveur Flask (routes, authentification, export Excel).
- `templates/`, `static/` : interface web.
