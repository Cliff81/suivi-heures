# Mettre le site en ligne (accès depuis n'importe où)

Objectif : que les salariés puissent saisir leurs heures depuis leur
téléphone, **où qu'ils soient** (4G, hors du bureau).

L'application est déjà prête pour l'hébergement (serveur de production
**gunicorn**, configuration par variables d'environnement, base SQLite sur
disque persistant). Il reste à la déposer chez un hébergeur — ce qui
nécessite **ton** compte (je ne peux pas le créer à ta place).

---

## ⚠️ À savoir avant (important)

1. **Données personnelles (RGPD).** Les heures des salariés sont des données
   personnelles. En les mettant en ligne, choisis un hébergement avec serveurs
   **en Europe** (région UE) et préviens/informe tes salariés. Garde un mot de
   passe fort pour chaque compte.
2. **Coût.** Pour que la base ne soit pas effacée à chaque redémarrage, il faut
   un **disque persistant**, ce qui implique une offre payante (≈ 7 €/mois chez
   la plupart des hébergeurs). Les offres « gratuites » effacent les données et
   « s'endorment » (lenteur au réveil).
3. **HTTPS.** L'hébergeur fournit le HTTPS automatiquement (cadenas). On a activé
   les cookies sécurisés via la variable `HTTPS_ONLY=1`.
4. **Sauvegarde.** Pense à télécharger régulièrement `heures.db` (ou l'export
   Excel) comme sauvegarde.

---

## Option recommandée : Render (simple, région Frankfurt = UE)

Le fichier `render.yaml` est déjà prêt. Étapes :

1. Mets le dossier du projet sur **GitHub** (dépôt privé).
2. Crée un compte sur https://render.com → **New** → **Blueprint**.
3. Sélectionne ton dépôt : Render lit `webapp/render.yaml` et configure tout
   (serveur, disque persistant `/data`, variables `SECRET_KEY`, `HTTPS_ONLY`,
   `SUIVI_DB=/data/heures.db`).
4. Vérifie la région **Frankfurt** puis lance le déploiement.
5. Tu obtiens une URL du type `https://suivi-heures.onrender.com`.
6. **Premier démarrage** : la base est vide → connecte-toi avec `admin / admin`,
   change le mot de passe, crée les comptes des salariés (onglet *Comptes*).

### Reprendre ta base actuelle (heures.db)
La base en ligne démarre vide. Pour repartir de tes données existantes :
- via le *Shell* Render, copie ton `heures.db` dans `/data/heures.db`, **ou**
- recrée les salariés/comptes et saisis les heures depuis l'interface.
(Je peux te détailler la copie du fichier le moment venu.)

---

## Mettre à jour une base existante

Le schéma se met à jour tout seul à la première ouverture : il n'y a aucune
commande de migration à lancer, et **aucune saisie n'est touchée**.

Sur une base antérieure à la planification de tournées, la mise à jour est
**purement additive** :

- sept tables nouvelles (`clients`, `journees`, `journee_salaries`,
  `courses`, `optimisations`, `geo_cache`, `trajet_cache`) ;
- trois colonnes nouvelles sur `salaries` (`adresse`, `telephone`, `notes`),
  toutes facultatives ;
- `jours`, `payees`, `conges_pris`, `jour_pauses`, `users` : inchangées, au
  contenu près.

Deux points à connaître :

- **L'application bureau continue de fonctionner** sur la même base, en
  lecture comme en écriture : elle nomme ses colonnes et ignore les nouvelles.
- **Le retour en arrière reste possible.** Une version antérieure du serveur
  rouvre la base migrée sans difficulté ; les tables de planification restent
  en place sans être lues.

Prenez tout de même une copie de `heures.db` avant la première mise à jour :
c'est gratuit et cela rend toute erreur réversible.

## Variables d'environnement utilisées
| Variable | Rôle | Exemple |
|---|---|---|
| `SECRET_KEY` | Clé de session (générée, à garder secrète) | (auto) |
| `SUIVI_DB` | Chemin de la base sur le disque persistant | `/data/heures.db` |
| `HTTPS_ONLY` | Cookies sécurisés derrière HTTPS | `1` |
| `PORT` | Port d'écoute (fourni par l'hébergeur) | (auto) |
| `SUIVI_CARTO_CLE` | Clé du service de cartographie, pour les **durées de trajet et l'optimisation**. Sans elle, les durées se saisissent à la main et l'attribution automatique est indisponible. | (vide) |
| `SUIVI_GEO` | Géocodeur : `ban` (Base Adresse Nationale, défaut), `carto` (le service de cartographie), `auto` (BAN puis repli) | `ban` |
| `SUIVI_GEO_URL` | Service de géocodage | `https://api-adresse.data.gouv.fr/search/` |
| `SUIVI_CARTO_URL` | Service utilisé | `https://api.openrouteservice.org` |
| `SUIVI_CARTO_PAYS` | Pays privilégié au géocodage | `FRA` |
| `SUIVI_CARTO_PROFIL` | Profil de trajet | `driving-car` |

### Tournées et données personnelles
Les fiches clients contiennent des données de santé (nom, adresse, type de
transport). Le traitement est découpé pour limiter ce qui sort :

- **Les adresses** vont à la **Base Adresse Nationale**, service public
  français : elles ne quittent pas la France, et aucune clé n'est nécessaire.
- **Seules les coordonnées** (latitude, longitude) partent ensuite vers le
  service de cartographie, pour les durées de trajet et l'optimisation.
  OpenRouteService héberge en Allemagne (UE).

Les coordonnées d'un domicile restent une donnée de localisation : le
transfert est réduit, pas supprimé. Il a sa place dans votre registre de
traitements. Chaque adresse et chaque trajet n'est demandé qu'une fois, le
résultat est conservé en base.

`SUIVI_GEO=carto` renvoie le géocodage vers la cartographie — nécessaire
seulement pour des adresses hors de France, que la Base Adresse Nationale ne
connaît pas.

## Alternatives
- **Hébergeurs français / UE** : Scalingo, Clever Cloud (RGPD, données en France).
  Même principe (gunicorn + `requirements.txt` + `Procfile`), mais ils
  privilégient une base **PostgreSQL** managée plutôt que SQLite sur disque —
  cela demande une petite adaptation du code (je peux la faire si tu choisis
  cette voie).
- **Fly.io** : supporte les volumes persistants pour garder SQLite.

## Lancement local de production (test)
```
cd webapp
pip install -r requirements.txt
SECRET_KEY=xxx gunicorn app:app --workers 2 --bind 0.0.0.0:5000
```
