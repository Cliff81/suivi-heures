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

## Notes techniques

- `core.py` : logique métier réutilisée (constantes, classe `DB`, calculs)
  — identique à l'app bureau, sans Tkinter.
- `app.py` : serveur Flask (routes, authentification, export Excel).
- `templates/`, `static/` : interface web.
