# Build Axiodrasil Launcher (onedir -> dist/AxiodrasilLauncher/)
# Usage (from repo root):
#   pip install -r launcher/requirements-launcher.txt
#   .\launcher\build_exe.ps1

param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "Project root: $ProjectRoot"
Write-Host "Installing launcher deps..."
& $Python -m pip install -r (Join-Path $PSScriptRoot "requirements-launcher.txt")

$distName = "AxiodrasilLauncher"
$entry = Join-Path $PSScriptRoot "run.py"

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name $distName `
    --paths $ProjectRoot `
    --hidden-import launcher `
    --hidden-import launcher.app `
    --hidden-import launcher.stack `
    --collect-all customtkinter `
    --distpath (Join-Path $ProjectRoot "dist") `
    --workpath (Join-Path $ProjectRoot "build\launcher") `
    --specpath (Join-Path $ProjectRoot "build\launcher") `
    $entry

$outDir = Join-Path $ProjectRoot "dist\$distName"
Write-Host ""
Write-Host "Done. Output: $outDir"
Write-Host "Run: $outDir\$distName.exe"
Write-Host "Tip: 日常也可双击 launcher\一键开聊.cmd（无需打包）。"
Write-Host "Tip: 若找不到仓库，设置 AX_PROJECT_ROOT 为仓库根路径。"
