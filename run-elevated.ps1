# Launch the Activity Tracker backend with Administrator privileges so ETW
# kernel providers can be enabled. Re-spawns itself elevated when needed.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    Write-Host "Re-launching elevated..." -ForegroundColor Yellow
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $MyInvocation.MyCommand.Path `
        -Verb RunAs
    exit
}

Set-Location $repoRoot
Write-Host "Starting backend on http://127.0.0.1:8000  (admin: yes)" -ForegroundColor Green
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
