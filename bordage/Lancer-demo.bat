@echo off
REM Double-clic : lance le suivi bordage avec 2 semaines de FAUSSES donnees,
REM pour voir le rendu. La vraie base n est pas touchee.
title Suivi bordage - DEMO
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python n est pas installe sur ce PC.
    echo   Telecharge-le sur https://www.python.org/downloads/
    echo   IMPORTANT : coche "Add python.exe to PATH" pendant l installation.
    echo.
    pause
    exit /b 1
)

echo   Verification des dependances...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo   L installation des dependances a echoue. Regarde le message ci-dessus.
    pause
    exit /b 1
)

set BORDAGE_DATA=%~dp0demo-data
python demo.py
echo.
echo   ======== MODE DEMO : fausses donnees ========
echo   Panel responsable : identifiant admin / mot de passe demo123
echo   Pour repartir de zero : supprime le dossier demo-data
echo.
start "" http://127.0.0.1:8080
python run.py
pause
