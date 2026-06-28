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

## Variables d'environnement utilisées
| Variable | Rôle | Exemple |
|---|---|---|
| `SECRET_KEY` | Clé de session (générée, à garder secrète) | (auto) |
| `SUIVI_DB` | Chemin de la base sur le disque persistant | `/data/heures.db` |
| `HTTPS_ONLY` | Cookies sécurisés derrière HTTPS | `1` |
| `PORT` | Port d'écoute (fourni par l'hébergeur) | (auto) |

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
