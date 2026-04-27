# Bootstrap: install backend (editable) + UI deps, build the UI.
# Pass -Elevated to delegate to run-elevated.ps1 after install.

param([switch]$Elevated)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==> python -m pip install -e .[dev]" -ForegroundColor Cyan
Set-Location $repoRoot
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

Write-Host "==> npm install + build (UI)" -ForegroundColor Cyan
Set-Location (Join-Path $repoRoot "ui")
npm ci
npm run build

# MCP package install if present.
if (Test-Path (Join-Path $repoRoot "mcp\pyproject.toml")) {
    Write-Host "==> pip install -e ./mcp[dev]" -ForegroundColor Cyan
    Set-Location $repoRoot
    python -m pip install -e ".\mcp[dev]"
}

Set-Location $repoRoot
Write-Host "Bootstrap complete." -ForegroundColor Green

if ($Elevated) {
    Write-Host "==> Launching elevated backend via run-elevated.ps1" -ForegroundColor Cyan
    & (Join-Path $repoRoot "run-elevated.ps1")
}
