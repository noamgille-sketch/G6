@echo off
REM Double-clic pour lancer le serveur du suivi bordage.
title Suivi bordage - serveur
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

python run.py
pause
