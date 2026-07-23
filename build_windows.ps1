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
    --add-data "VERSION;." `
    --add-data "assets;assets" `
    --hidden-import backup_gui `
    --hidden-import backup_manager `
    --hidden-import backup_service `
    --hidden-import consolemods_adapters `
    --hidden-import dat_adapters `
    --hidden-import knowledge_gui `
    --hidden-import knowledge_service `
    --hidden-import knowledge_sync `
    --hidden-import wiki_adapters `
    desktop_app.py

Write-Host ""
Write-Host "Build complete: $ProjectRoot\dist\UnityScraper.exe"
Write-Host "User data is stored under %LOCALAPPDATA%\UnityScraper"
