param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
    Remove-Item -Force -ErrorAction SilentlyContinue UnityScraper.spec
}

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller `
    --name UnityScraper `
    --noconsole `
    --onefile `
    --icon "assets\UnityScraper.ico" `
    --add-data "JSON.txt;." `
    --add-data "assets\UnityScraper.png;assets" `
    desktop_app.py

Write-Host ""
Write-Host "Build complete: $ProjectRoot\dist\UnityScraper.exe"
Write-Host "User data is stored under %LOCALAPPDATA%\UnityScraper"
