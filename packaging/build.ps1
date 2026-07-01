# One-click build of the SkillOpt Studio desktop app (cross-platform PowerShell).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m pip install --upgrade pip
pip install -e ".[build]"

Write-Host "Building SkillOpt Studio with PyInstaller..."
pyinstaller --noconfirm (Join-Path "packaging" "skillopt_studio.spec")

Write-Host ""
Write-Host "Done. App bundle is in: dist/SkillOptStudio/"
if ($IsWindows) {
    Write-Host "Run it:  dist\SkillOptStudio\SkillOptStudio.exe"
} else {
    Write-Host "Run it:  ./dist/SkillOptStudio/SkillOptStudio"
}
