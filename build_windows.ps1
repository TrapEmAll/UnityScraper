param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = "python"
if (Test-Path ".venv\Scripts\python.exe") {
    $Python = ".venv\Scripts\python.exe"
}

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
}

& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller
& $Python -m PyInstaller --clean --noconfirm UnityScraper.spec

$Executable = Join-Path $ProjectRoot "dist\UnityScraper.exe"
if (-not (Test-Path $Executable)) {
    throw "PyInstaller completed without creating $Executable"
}

$Hash = (Get-FileHash $Executable -Algorithm SHA256).Hash.ToLower()
"$Hash *UnityScraper.exe" | Set-Content "$Executable.sha256"

Write-Host ""
Write-Host "Build complete: $Executable"
Write-Host "Checksum: $Executable.sha256"
Write-Host "User data: %LOCALAPPDATA%\UnityScraper"
