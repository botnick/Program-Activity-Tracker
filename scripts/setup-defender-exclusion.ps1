# One-time Defender exclusion for the Activity Tracker.
# Run as Administrator: powershell -ExecutionPolicy Bypass -File .\scripts\setup-defender-exclusion.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    Write-Host "Re-launching elevated..." -ForegroundColor Yellow
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $MyInvocation.MyCommand.Path `
        -Verb RunAs
    exit
}

# Add path-level exclusion for the whole repo so AV doesn't keep flagging
# the native binary when we rebuild it. Single-user, local-only — safe.
$nativeBuild = Join-Path $repoRoot "service\native\build"
$nativeRelease = Join-Path $repoRoot "service\native\build\Release"
$captureExe = Join-Path $repoRoot "service\native\build\tracker_capture.exe"
$captureExeRelease = Join-Path $repoRoot "service\native\build\Release\tracker_capture.exe"

Write-Host "Adding Defender exclusions..." -ForegroundColor Cyan
foreach ($path in @($nativeBuild, $nativeRelease)) {
    try {
        Add-MpPreference -ExclusionPath $path -ErrorAction Stop
        Write-Host "  + path  $path" -ForegroundColor Green
    } catch {
        Write-Host "  ! path  $path  ($($_.Exception.Message))" -ForegroundColor Yellow
    }
}
foreach ($exe in @($captureExe, $captureExeRelease)) {
    if (Test-Path $exe) {
        try {
            Add-MpPreference -ExclusionProcess $exe -ErrorAction Stop
            Write-Host "  + proc  $exe" -ForegroundColor Green
        } catch {
            Write-Host "  ! proc  $exe  ($($_.Exception.Message))" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "Done. Defender will no longer scan the native ETW binary." -ForegroundColor Green
Write-Host "To remove the exclusions later: Remove-MpPreference -ExclusionPath / -ExclusionProcess" -ForegroundColor DarkGray
