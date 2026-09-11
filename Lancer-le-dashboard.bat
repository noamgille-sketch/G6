@echo off
REM Double-click launcher for the local dashboard on Windows.
REM Installs what is missing the first time, then opens the browser.

title G6 Guard - dashboard local
cd /d "%~dp0"

echo.
echo   G6 Guard - dashboard local
echo   ==========================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo   Python n'est pas installe sur ce PC.
    echo.
    echo   Telecharge-le sur https://www.python.org/downloads/
    echo   IMPORTANT : coche "Add python.exe to PATH" pendant l'installation,
    echo   sinon cette fenetre ne le trouvera pas.
    echo.
    pause
    exit /b 1
)

echo   Verification des dependances...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo   L'installation des dependances a echoue. Regarde le message ci-dessus.
    pause
    exit /b 1
)

echo   Demarrage du serveur...
echo.
echo   Ouvre ton navigateur sur :  http://127.0.0.1:5151
echo   Pour arreter : ferme cette fenetre.
echo.

REM Local only: no account needed, the dashboard warns that it is open.
set G6_LOCAL=1
start "" http://127.0.0.1:5151
python dashboard\app.py

pause
