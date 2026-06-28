@echo off
REM ============================================================
REM  Suivi des heures - version WEB (Windows)
REM  Double-cliquez pour demarrer le serveur, puis ouvrez
REM  http://127.0.0.1:5000 dans votre navigateur.
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")

echo --^> Installation des dependances (Flask, openpyxl)...
%PY% -m pip install --user --upgrade flask openpyxl >nul

echo.
echo ================================================================
echo   Serveur demarre. Ouvrez votre navigateur a l'adresse :
echo       http://127.0.0.1:5000
echo   Compte par defaut : admin / admin (a changer dans 'Comptes').
echo   Laissez cette fenetre ouverte. Fermez-la pour arreter.
echo ================================================================
start "" http://127.0.0.1:5000
%PY% app.py
pause
