#!/bin/bash
# ============================================================
#  Suivi des heures - version WEB (macOS / Linux)
#  Double-cliquez pour demarrer le serveur, puis ouvrez
#  http://127.0.0.1:5000 dans votre navigateur.
# ============================================================
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 introuvable. Installez-le depuis https://www.python.org/downloads/"
  read -p "Entree pour fermer."; exit 1
fi

echo "-> Installation des dependances (Flask, openpyxl)..."
python3 -m pip install --user --upgrade flask openpyxl >/dev/null

echo ""
echo "================================================================"
echo "  Serveur demarre. Ouvrez votre navigateur a l'adresse :"
echo "      http://127.0.0.1:5000"
echo "  Compte par defaut : admin / admin (a changer dans 'Comptes')."
echo "  Laissez cette fenetre ouverte. Fermez-la pour arreter."
echo "================================================================"
( sleep 2; (open http://127.0.0.1:5000 2>/dev/null || xdg-open http://127.0.0.1:5000 2>/dev/null) ) &
python3 app.py
