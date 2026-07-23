@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo UnityScraper Setup
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH.
    echo Install Python 3.10 or newer, then run this file again.
    exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo UnityScraper requires Python 3.10 or newer.
    python --version
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Installing runtime dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo Setup complete.
echo Run UnityScraper with:
echo   .venv\Scripts\python.exe desktop_app.py
echo.
endlocal
